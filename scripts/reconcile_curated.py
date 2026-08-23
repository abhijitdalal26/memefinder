"""Reconcile orphan files in data/curated with curated_metadata.json.

- Finds files in data/curated/**/* not referenced in curated_metadata.json
- Validates quality (resolution, file size, dedup)
- Fetches missing postmeta from Arctic Shift for upvote/title if needed
- Creates records matching collect_to_target.py schema and appends atomically
"""
import json
import re
import time
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import BASE_DIR, DATA_DIR, TEMPLATE_SUBREDDITS
from utils.dedup import Deduplicator

CURATED_DIR = DATA_DIR / "curated"
META_FILE = BASE_DIR / "curated_metadata.json"
POSTMETA_FILE = BASE_DIR / "config" / "postmeta.json"
SEEN_POSTS_FILE = BASE_DIR / "config" / "seen_reddit_posts.json"
SEEN_URLS_FILE = BASE_DIR / "config" / "seen_reddit_urls.json"

FILENAME_RE = re.compile(r"^(?P<sub>.+)_(?P<pid>[A-Za-z0-9]{4,12})\.(?:jpg|jpeg|png|webp)$", re.IGNORECASE)
MIN_RES = (400, 400)
MIN_KB = 20
UPVOTE_MIN = 5
IDS_URL = "https://arctic-shift.photon-reddit.com/api/posts/ids"
FIELDS = "id,title,score,num_comments,url,created_utc,author,over_18,spoiler,subreddit"

def load_json(path, default):
    if path.exists():
        try:
            return json.load(open(path, encoding="utf-8"))
        except:
            return default
    return default

def fetch_postmeta(pids, session):
    """Fetch metadata for pids via Arctic batch."""
    meta = {}
    BATCH = 100
    for i in range(0, len(pids), BATCH):
        batch = pids[i:i+BATCH]
        try:
            r = session.get(IDS_URL, params={"ids": ",".join(batch), "fields": FIELDS}, timeout=60)
            r.raise_for_status()
            for p in r.json().get("data", []):
                if isinstance(p, dict) and p.get("id"):
                    meta[p["id"]] = p
        except Exception as e:
            print(f"  fetch batch {i//BATCH} error: {e}")
            time.sleep(5)
            try:
                r = session.get(IDS_URL, params={"ids": ",".join(batch), "fields": FIELDS}, timeout=60)
                r.raise_for_status()
                for p in r.json().get("data", []):
                    if isinstance(p, dict) and p.get("id"):
                        meta[p["id"]] = p
            except Exception as e2:
                print(f"  retry failed: {e2}")
        print(f"  fetched {len(meta)}/{len(pids)} postmeta")
        time.sleep(0.5)
    return meta

def main(dry_run=False):
    print("=== Reconcile Curated Orphans ===")
    records = load_json(META_FILE, [])
    print(f"Loaded {len(records)} records from {META_FILE}")
    existing_ids = {r.get("source_id") for r in records if r.get("source_id")}
    postmeta = load_json(POSTMETA_FILE, {})
    if isinstance(postmeta, list):
        postmeta = {}
    # postmeta is dict pid -> {upvotes, ...}
    seen_posts = set(load_json(SEEN_POSTS_FILE, []))
    seen_urls = set(load_json(SEEN_URLS_FILE, []))
    dedup = Deduplicator()

    # Find all files
    all_files = [p for p in CURATED_DIR.rglob("*") if p.is_file() and p.suffix.lower() != ".part"]
    print(f"Found {len(all_files)} files on disk (excl .part)")
    orphans = []
    by_sub = Counter()
    miss_pat = 0
    for f in all_files:
        m = FILENAME_RE.match(f.name)
        if not m:
            miss_pat += 1
            continue
        pid = m.group("pid")
        sub = m.group("sub")
        if pid not in existing_ids:
            orphans.append((f, pid, sub))
            by_sub[sub] += 1
    print(f"Orphans not in metadata: {len(orphans)} (miss_pat {miss_pat})")
    print("By sub:", by_sub.most_common(10))
    if not orphans:
        print("No orphans, nothing to do.")
        return

    # Determine which orphans need postmeta fetch
    need_fetch = [pid for _, pid, _ in orphans if pid not in postmeta]
    print(f"Need to fetch postmeta for {len(need_fetch)} pids")
    fetched = {}
    if need_fetch and not dry_run:
        session = requests.Session()
        session.headers.update({"User-Agent": "MakeMeMemeReconcile/1.0"})
        fetched = fetch_postmeta(need_fetch, session)
        print(f"Fetched {len(fetched)} new postmeta")
        # merge into postmeta for saving later
        for pid, p in fetched.items():
            postmeta[pid] = {
                "upvotes": p.get("score", 0) or 0,
                "comments": p.get("num_comments", 0) or 0,
                "title": (p.get("title") or "")[:300],
                "author": p.get("author", ""),
                "created_utc": p.get("created_utc", 0) or 0,
                "url": p.get("url", ""),
                "subreddit": p.get("subreddit", ""),
                "over_18": bool(p.get("over_18")),
                "spoiler": bool(p.get("spoiler")),
            }
        # save postmeta atomically
        tmp = POSTMETA_FILE.with_suffix(".tmp")
        json.dump(postmeta, open(tmp, "w", encoding="utf-8"))
        tmp.replace(POSTMETA_FILE)
        print(f"Saved postmeta {len(postmeta)} to {POSTMETA_FILE}")
    elif dry_run and need_fetch:
        print(f"DRY RUN: would fetch {len(need_fetch)} pids, skipping")

    if dry_run:
        # Fast path: just estimate without heavy image ops
        print(f"DRY RUN: would process {len(orphans)} orphans with quality/dedup checks")
        # sample 5
        for f, pid, sub in orphans[:5]:
            print(f"  sample {f.name} sub={sub} pid={pid} size={f.stat().st_size/1024:.1f}KB")
        return

    # Process orphans
    added = 0
    dropped = Counter()
    new_records = []
    for f, pid, sub in orphans:
        # Use postmeta if available, else fallback to file-derived
        pm = postmeta.get(pid, {})
        # If fetched meta says NSFW/spoiler, delete file
        # fetched raw may have over_18 flag
        # Check that: if pm has over_18 but original file was already filtered, but reconcile should respect
        # We have stored postmeta with over_18 bool
        if pm.get("over_18") or pm.get("spoiler"):
            dropped["nsfw_spoiler"] += 1
            if not dry_run:
                f.unlink(missing_ok=True)
            continue
        # Image checks
        try:
            with Image.open(f) as img:
                img.load()
                w, h = img.size
                fmt = img.format
        except Exception:
            dropped["open_fail"] += 1
            if not dry_run:
                f.unlink(missing_ok=True)
            continue
        sz_kb = f.stat().st_size / 1024
        if w < MIN_RES[0] or h < MIN_RES[1]:
            dropped["too_small"] += 1
            if not dry_run:
                f.unlink(missing_ok=True)
            continue
        if sz_kb < MIN_KB:
            dropped["too_small_file"] += 1
            if not dry_run:
                f.unlink(missing_ok=True)
            continue
        is_template = sub.lower() in TEMPLATE_SUBREDDITS
        up = pm.get("upvotes", 0) or 0
        # if we have no postmeta upvotes and not template, skip upvote gate? Use placeholder 100 to keep
        # but we fetched, so we have up; if still missing, treat as 0 and gate will drop
        if not is_template and up < UPVOTE_MIN:
            # if pm missing entirely, we don't know upvote, keep it (assume it passed at collection)
            if pid not in postmeta and not fetched:
                # no info, keep
                pass
            else:
                dropped["low_upvotes"] += 1
                if not dry_run:
                    f.unlink(missing_ok=True)
                continue
        # Dedup
        try:
            hsh = dedup.compute_hash(str(f))
        except:
            hsh = None
        if hsh is None or dedup.is_duplicate(hash_hex=hsh):
            dropped["duplicate"] += 1
            if not dry_run:
                f.unlink(missing_ok=True)
            continue
        dedup.register(hash_hex=hsh)

        # Build record matching collect_to_target.py:303-314
        # Try to get title/author from pm, fallback to empty
        title = (pm.get("title") or "")[:300]
        author = pm.get("author", "")
        comments = pm.get("comments", 0) or 0
        created_utc = pm.get("created_utc", 0) or 0
        image_url = pm.get("url", "")
        # If image_url missing, we can't know, leave empty but keep record
        record = {
            "id": str(uuid.uuid4()),
            "source": "reddit",
            "source_sub": f"r/{sub}",
            "source_id": pid,
            "source_url": f"https://www.reddit.com/r/{sub}/comments/{pid}/",
            "image_url": image_url,
            "image_path": str(f.relative_to(BASE_DIR)),
            "title": title,
            "author": author,
            "upvotes": up,
            "comments": comments,
            "quality_score": round(min(up/50000,1.0)*0.5 + min((w*h)/(1920*1080),1.0)*0.5, 3),
            "image_type": ("square" if 0.9 <= w/h <= 1.1 else ("portrait" if w/h < 0.9 else "landscape")),
            "nsfw": False,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "posted_at": datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat() if created_utc else "",
            "resolution": [w, h],
            "format": fmt or "",
            "file_size_kb": round(sz_kb, 2),
            "community_category": "template" if is_template else "general",
        }
        # Enrich with utils? We can call enrich for humor_signal etc but keep lightweight
        try:
            from utils.enrichment import enrich
            enrich(record, img=Image.open(f))
        except:
            pass
        new_records.append(record)
        seen_posts.add(pid)
        if image_url:
            seen_urls.add(image_url)
        added += 1
        if added % 500 == 0:
            print(f"  processed {added} added, {sum(dropped.values())} dropped")

    print(f"\n=== Reconcile Summary ===")
    print(f"Added: {added}")
    print(f"Dropped: {dict(dropped)}")
    print(f"Orphans total: {len(orphans)}")
    if dry_run:
        print("DRY RUN - no files written")
        return

    # Append to records and save atomically
    records.extend(new_records)
    tmp = META_FILE.with_suffix(".tmp")
    json.dump(records, open(tmp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    tmp.replace(META_FILE)
    print(f"Wrote {len(records)} records to {META_FILE}")

    # Save seen sets atomically
    tmp = SEEN_POSTS_FILE.with_suffix(".tmp")
    json.dump(sorted(seen_posts), open(tmp, "w", encoding="utf-8"), indent=0)
    tmp.replace(SEEN_POSTS_FILE)
    tmp = SEEN_URLS_FILE.with_suffix(".tmp")
    json.dump(sorted(seen_urls), open(tmp, "w", encoding="utf-8"), indent=0)
    tmp.replace(SEEN_URLS_FILE)
    dedup.save()
    print(f"Saved seen_posts {len(seen_posts)}, seen_urls {len(seen_urls)}, dedup {dedup.get_stats()}")
    # also update curated_metadata in data/ ifexists? keep both
    data_meta = DATA_DIR / "curated_metadata.json"
    if data_meta.exists() or True:
        tmp = data_meta.with_suffix(".tmp")
        json.dump(records, open(tmp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        tmp.replace(data_meta)
        print(f"Mirrored to {data_meta}")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    main(dry_run=args.dry_run)
