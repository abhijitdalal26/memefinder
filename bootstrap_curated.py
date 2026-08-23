"""Fold the already-downloaded valid images into data/curated as the baseline.

Moves every image currently in data/reddit into data/curated/<sub>/, builds a
record from config/postmeta.json, and registers its hash. This becomes the
starting point for collect_to_target.py so we never re-collect what we have.
"""
import json
import re
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config.settings import BASE_DIR, DATA_DIR, TEMPLATE_SUBREDDITS
from utils.dedup import Deduplicator

FILENAME_RE = re.compile(r"^(?P<sub>.+)_(?P<pid>[A-Za-z0-9]{4,12})\.(jpg|jpeg|png|webp)$", re.IGNORECASE)
CURATED_DIR = DATA_DIR / "curated"

def main():
    postmeta = json.load(open(BASE_DIR / "config" / "postmeta.json", encoding="utf-8")) if (BASE_DIR / "config" / "postmeta.json").exists() else {}
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    dedup = Deduplicator()

    records = []
    if (BASE_DIR / "curated_metadata.json").exists():
        records = json.load(open(BASE_DIR / "curated_metadata.json", encoding="utf-8"))
    existing_pids = {r.get("source_id") for r in records}

    src_reddit = DATA_DIR / "reddit"
    moved = 0
    for f in list(src_reddit.iterdir()) if src_reddit.exists() else []:
        if not f.is_file():
            continue
        m = FILENAME_RE.match(f.name)
        if not m:
            continue
        pid, sub = m.group("pid"), m.group("sub")
        meta = postmeta.get(pid, {})
        dest_dir = CURATED_DIR / sub
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f.name
        if dest.exists():
            f.unlink(missing_ok=True)
        else:
            shutil.move(str(f), str(dest))
        if pid in existing_pids:
            moved += 1
            continue
        h = dedup.compute_hash(str(dest))
        dedup.register(hash_hex=h) if h else None
        w = 0; hgt = 0
        try:
            from PIL import Image
            with Image.open(dest) as im:
                w, hgt = im.size
        except Exception:
            pass
        records.append({
            "id": pid, "source": "reddit", "source_sub": f"r/{sub}", "source_id": pid,
            "source_url": f"https://www.reddit.com/r/{sub}/comments/{pid}/",
            "image_url": meta.get("url", ""), "image_path": str(dest.relative_to(BASE_DIR)),
            "title": (meta.get("title") or "")[:300], "author": meta.get("author", ""),
            "upvotes": meta.get("upvotes", 0) or 0, "comments": meta.get("comments", 0) or 0,
            "quality_score": 0, "image_type": "unknown", "nsfw": bool(meta.get("over_18", False)),
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "posted_at": datetime.fromtimestamp(meta.get("created_utc", 0), tz=timezone.utc).isoformat() if meta.get("created_utc") else "",
            "resolution": [w, hgt], "format": "", "file_size_kb": round(dest.stat().st_size/1024, 2),
            "community_category": "template" if sub.lower() in TEMPLATE_SUBREDDITS else "general",
        })
        existing_pids.add(pid)
        moved += 1

    json.dump(records, open(BASE_DIR / "curated_metadata.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    dedup.save()
    print(f"baseline curated: {len(records)} records ({moved} folded in / moved)")

if __name__ == "__main__":
    main()
