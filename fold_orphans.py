import json, re, sys
from pathlib import Path

sys.path.insert(0, r"D:\claude_space\MakeMeMeme")
from utils.dedup import Deduplicator

BASE_DIR = Path(r"D:\claude_space\MakeMeMeme")
CURATED_DIR = BASE_DIR / "data" / "curated"
META = BASE_DIR / "data" / "curated_metadata.json"
POSTMETA = BASE_DIR / "config" / "postmeta.json"
FILENAME_RE = re.compile(r"^(?P<sub>.+)_(?P<pid>[a-z0-9]+)(?:_(?P<hash>\w{16}))?$")
EXTS = {".jpg", ".jpeg", ".png", ".webp"}

records = json.loads(META.read_text()) if META.exists() else []
existing_ids = set(r.get("source_id") for r in records if r.get("source_id"))
postmeta = json.loads(POSTMETA.read_text()) if POSTMETA.exists() else {}

dd = Deduplicator()

added = 0
hashes_seen = set()
for f in CURATED_DIR.rglob("*"):
    if not f.is_file() or f.suffix.lower() not in EXTS:
        continue
    m = FILENAME_RE.match(f.stem)
    if not m:
        continue
    pid = m.group("pid")
    if pid in existing_ids:
        continue
    sub = (m.group("sub") or "").replace("r/", "")
    pm = postmeta.get(pid, {})
    # skip re-hashing orphans (already on disk / deduped at runtime); register record only
    h = None
    rec = {
        "source": "reddit",
        "source_sub": "r/" + sub if sub else None,
        "source_id": pid,
        "title": pm.get("title"),
        "upvotes": pm.get("score"),
        "image_path": str(f),
        "image_hash": h,
        "width": pm.get("width"),
        "height": pm.get("height"),
        "downloaded_at": pm.get("downloaded_at"),
        "is_template": False,
    }
    records.append(rec)
    existing_ids.add(pid)
    added += 1

META.write_text(json.dumps(records, indent=1))
print(f"folded {added} orphan files; new total records={len(records)}")
