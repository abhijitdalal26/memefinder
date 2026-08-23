"""Backfill metadata.json records for already-downloaded reddit images.

Scans data/reddit for {subreddit}_{postid}.{ext} files, fetches post
metadata from the Arctic Shift archive by ID, and appends full records
(same schema as RedditArcticScraper) for any file missing from the catalog.
Also cleans up leftover .part files from interrupted downloads.
"""
import json
import re
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import (
    BASE_DIR,
    DATA_DIR,
    METADATA_FILE,
    REDDIT_DATA_DIR,
    MIN_RESOLUTION,
    MAX_FILE_SIZE_MB,
    SUBREDDIT_META,
    DEFAULT_SUB_META,
)
from utils.dedup import Deduplicator
from utils.quality import passes_quality_check_img, compute_quality_score, get_image_info_from_img, classify_image_type_from_info
from utils.enrichment import enrich

IDS_URL = "https://arctic-shift.photon-reddit.com/api/posts/ids"
FIELDS = (
    "id,title,score,num_comments,url,created_utc,author,over_18,"
    "post_hint,link_flair_text,spoiler,selftext,subreddit"
)
FILENAME_RE = re.compile(r"^(?P<sub>.+)_(?P<pid>[A-Za-z0-9]{4,12})\.(jpg|jpeg|png|webp)$", re.IGNORECASE)
BATCH = 100


def load_catalog() -> list:
    if METADATA_FILE.exists():
        with open(METADATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def build_record(post: dict, save_path: Path, img, info, listing_tag: str) -> dict:
    subreddit = post.get("subreddit") or "unknown"
    pid = post.get("id", "")
    url = post.get("url", "")
    created = post.get("created_utc", 0)
    sub_meta = SUBREDDIT_META.get(subreddit.lower(), DEFAULT_SUB_META)
    record = {
        "id": str(uuid.uuid4()),
        "source": "reddit",
        "source_sub": f"r/{subreddit}",
        "source_listing": listing_tag,
        "source_id": pid,
        "source_url": f"https://www.reddit.com/r/{subreddit}/comments/{pid}/",
        "image_url": url,
        "image_path": str(save_path.relative_to(BASE_DIR)),
        "title": (post.get("title") or "")[:300],
        "author": post.get("author", ""),
        "upvotes": post.get("score", 0),
        "comments": post.get("num_comments", 0),
        "quality_score": compute_quality_score(
            upvotes=post.get("score", 0),
            comments=post.get("num_comments", 0),
            resolution=info["resolution"] if info else (0, 0),
        ),
        "image_type": classify_image_type_from_info(info),
        "nsfw": False,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "posted_at": datetime.fromtimestamp(created, tz=timezone.utc).isoformat() if created else "",
        "resolution": [info["width"], info["height"]] if info else [0, 0],
        "format": info["format"] if info else "",
        "file_size_kb": info["file_size_kb"] if info else 0,
        "flair": (post.get("link_flair_text") or "")[:100],
        "post_hint": post.get("post_hint") or "",
        "selftext": (post.get("selftext") or "")[:500],
        "community_category": sub_meta["category"],
        "community_audience": sub_meta["audience"],
        "backfilled": True,
    }
    enrich(record, img=img)
    return record


def main():
    session = requests.Session()
    session.headers.update({"User-Agent": "MakeMeMemeDatasetCollector/1.0"})
    dedup = Deduplicator()

    catalog = load_catalog()
    known_ids = {m["source_id"] for m in catalog if m.get("source") == "reddit" and "source_id" in m}
    print(f"Catalog has {len(known_ids)} reddit records")

    # cleanup .part leftovers
    parts = list(REDDIT_DATA_DIR.glob("*.part"))
    for p in parts:
        p.unlink(missing_ok=True)
    if parts:
        print(f"Deleted {len(parts)} stale .part files")

    # scan files
    orphans: dict[str, Path] = {}
    skipped = 0
    for f in REDDIT_DATA_DIR.iterdir():
        if not f.is_file():
            continue
        m = FILENAME_RE.match(f.name)
        if not m:
            continue
        pid = m.group("pid")
        if pid in known_ids:
            skipped += 1
            continue
        orphans[pid] = f
    print(f"{skipped} files already cataloged | {len(orphans)} orphan files to recover")

    pids = sorted(orphans)
    added = 0
    bad_files = 0
    seen_cfg = Path(__file__).resolve().parent / "config"
    seen_urls = set(json.load(open(seen_cfg / "seen_reddit_urls.json", encoding="utf-8")))

    for i in range(0, len(pids), BATCH):
        batch = pids[i:i + BATCH]
        try:
            r = session.get(IDS_URL, params={"ids": ",".join(batch), "fields": FIELDS}, timeout=90)
            r.raise_for_status()
            posts = {p["id"]: p for p in r.json().get("data", []) if isinstance(p, dict) and p.get("id")}
        except Exception as e:
            print(f"batch {i//BATCH}: fetch error {str(e)[:80]}, retrying once")
            try:
                time.sleep(10)
                r = session.get(IDS_URL, params={"ids": ",".join(batch), "fields": FIELDS}, timeout=90)
                r.raise_for_status()
                posts = {p["id"]: p for p in r.json().get("data", []) if isinstance(p, dict) and p.get("id")}
            except Exception as e2:
                print(f"batch {i//BATCH}: failed again ({str(e2)[:60]}), skipping batch")
                continue

        for pid in batch:
            path = orphans[pid]
            post = posts.get(pid)
            if not post:
                # post no longer archived; drop file if it can't be identified at all
                bad_files += 1
                continue
            if post.get("over_18") or post.get("spoiler"):
                path.unlink(missing_ok=True)
                bad_files += 1
                continue
            img = None
            try:
                img = Image.open(path)
                img.load()
            except Exception:
                if img is not None:
                    img.close()
                path.unlink(missing_ok=True)
                bad_files += 1
                continue
            with img:
                ok, _ = passes_quality_check_img(img, str(path), MIN_RESOLUTION, MAX_FILE_SIZE_MB)
                if not ok:
                    path.unlink(missing_ok=True)
                    bad_files += 1
                    continue
                h = dedup.compute_hash_from_img(img)
                if h is None or dedup.is_duplicate(hash_hex=h):
                    path.unlink(missing_ok=True)
                    bad_files += 1
                    continue
                dedup.register(hash_hex=h)
                info = get_image_info_from_img(img, str(path))
            record = build_record(post, path, img, info, "arctic_history_backfill")
            catalog.append(record)
            seen_urls.add(post.get("url", ""))
            known_ids.add(pid)
            added += 1

        print(f"[{min(i+BATCH, len(pids))}/{len(pids)}] +{added} recovered, {bad_files} dropped", flush=True)

    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

    src_meta = DATA_DIR / "reddit" / "_metadata.json"
    src_meta.parent.mkdir(parents=True, exist_ok=True)
    with open(src_meta, "w", encoding="utf-8") as f:
        json.dump([m for m in catalog if m.get("source") == "reddit"], f, indent=2, ensure_ascii=False)

    json.dump(sorted(seen_urls), open(seen_cfg / "seen_reddit_urls.json", "w"), indent=0)
    dedup.save()
    print(f"\nDone: {added} records recovered, {bad_files} invalid files removed")
    print(f"Catalog size: {len(catalog)}")


if __name__ == "__main__":
    import time
    main()
