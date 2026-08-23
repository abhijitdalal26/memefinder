"""Curate the downloaded memes into a high-quality training set.

For every file in data/reddit:
  - parse subreddit + post id from the filename
  - look up upvotes from config/postmeta.json
  - open once (resolution, file size, format) + perceptual hash already guaranteed unique
  - apply quality gates:
        resolution >= 400x400
        file_size >= 20 KB (drop blank/textless)
        upvotes   >= UPVOTE_MIN  (captioned memes only; templates exempt)
  - passing files are MOVED into data/curated/<sub>/ (originals are NOT deleted)
  - writes data/curated_metadata.json

Nothing is deleted. To remove the low-quality leftovers later, delete data/reddit
after you've verified the curated set.
"""
import json
import re
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import (
    BASE_DIR, REDDIT_DATA_DIR, TEMPLATE_SUBREDDITS, TEMPLATE_SOURCES,
    DATA_DIR,
)

FILENAME_RE = re.compile(r"^(?P<sub>.+)_(?P<pid>[A-Za-z0-9]{4,12})\.(jpg|jpeg|png|webp)$", re.IGNORECASE)
UPVOTE_MIN = 100          # captioned memes need at least this many upvotes
MIN_RES = (400, 400)
MIN_KB = 20
CURATED_DIR = DATA_DIR / "curated"


def is_template(sub: str, source: str = "reddit") -> bool:
    if source in TEMPLATE_SOURCES:
        return True
    return sub.lower() in TEMPLATE_SUBREDDITS


def main():
    postmeta = json.load(open(BASE_DIR / "config" / "postmeta.json", encoding="utf-8"))
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BASE_DIR / "curated_metadata.json"

    # resume support
    records = []
    existing_pids = set()
    if out_path.exists():
        try:
            records = json.load(open(out_path, encoding="utf-8"))
            existing_pids = {r.get("source_id") for r in records}
        except Exception:
            records, existing_pids = [], set()
    curated_bytes = sum(p.stat().st_size for p in CURATED_DIR.rglob("*") if p.is_file())

    passed = 0
    dropped = {"too_small": 0, "too_small_file": 0, "low_upvotes": 0, "open_fail": 0, "already": 0}

    files = [f for f in REDDIT_DATA_DIR.iterdir() if f.is_file()]
    print(f"scanning {len(files)} files ({len(existing_pids)} already curated)...", flush=True)

    for f in files:
        m = FILENAME_RE.match(f.name)
        if not m:
            continue
        pid = m.group("pid")
        if pid in existing_pids:
            dropped["already"] += 1
            continue
        sub = m.group("sub")
        meta = postmeta.get(pid, {})
        upvotes = meta.get("upvotes", 0) or 0
        template = is_template(sub)

        try:
            with Image.open(f) as img:
                img.load()
                w, h = img.size
                fmt = img.format
        except Exception:
            dropped["open_fail"] += 1
            continue

        sz = f.stat().st_size
        size_kb = sz / 1024
        if w < MIN_RES[0] or h < MIN_RES[1]:
            dropped["too_small"] += 1
            continue
        if size_kb < MIN_KB:
            dropped["too_small_file"] += 1
            continue
        if not template and upvotes < UPVOTE_MIN:
            dropped["low_upvotes"] += 1
            continue

        # passing -> move into curated tree
        dest_dir = CURATED_DIR / sub
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f.name
        if dest.exists():
            pass
        else:
            shutil.move(str(f), str(dest))

        record = {
            "id": pid,
            "source": "reddit",
            "source_sub": f"r/{sub}",
            "source_id": pid,
            "source_url": f"https://www.reddit.com/r/{sub}/comments/{pid}/",
            "image_url": meta.get("url", ""),
            "image_path": str(dest.relative_to(BASE_DIR)),
            "title": (meta.get("title") or "")[:300],
            "author": meta.get("author", ""),
            "upvotes": upvotes,
            "comments": meta.get("comments", 0) or 0,
            "quality_score": round(min(upvotes / 50000, 1.0) * 0.5 + min((w * h) / (1920 * 1080), 1.0) * 0.5, 3),
            "image_type": ("square" if 0.9 <= w / h <= 1.1 else ("portrait" if w / h < 0.9 else "landscape")),
            "nsfw": bool(meta.get("over_18", False)),
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "posted_at": datetime.fromtimestamp(meta.get("created_utc", 0), tz=timezone.utc).isoformat() if meta.get("created_utc") else "",
            "resolution": [w, h],
            "format": fmt or "",
            "file_size_kb": round(size_kb, 2),
            "community_category": "template" if template else "general",
        }
        records.append(record)
        existing_pids.add(pid)
        passed += 1
        curated_bytes += sz

        if passed % 1000 == 0:
            json.dump(records, open(out_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
            print(f"  curated {passed} ({curated_bytes/1e9:.2f} GB)", flush=True)

    json.dump(records, open(out_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("\n=== CURATION SUMMARY ===")
    print(f"passed (moved to data/curated): {passed}  ({curated_bytes/1e9:.2f} GB)")
    print(f"dropped: {dropped}")
    print(f"curated set: {curated_bytes/1e9:.2f} GB  |  target was ~10-12 GB")
    print(f"wrote curated_metadata.json with {len(records)} records")


if __name__ == "__main__":
    main()
