"""Fetch post metadata (upvotes, title, etc.) for every downloaded reddit image.

Produces config/postmeta.json = {pid: {...}} so the curation step can apply
an upvote-quality gate without re-hashing or re-downloading anything.

- Concurrent API fetches (thread pool) -> much faster than sequential.
- Resumable: saves incrementally; re-running skips already-fetched pids.
- Non-destructive: never deletes or moves files.
"""
import json
import re
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import BASE_DIR, REDDIT_DATA_DIR

IDS_URL = "https://arctic-shift.photon-reddit.com/api/posts/ids"
FIELDS = "id,title,score,num_comments,url,created_utc,author,over_18,spoiler,subreddit"
FILENAME_RE = re.compile(r"^(?P<sub>.+)_(?P<pid>[A-Za-z0-9]{4,12})\.(jpg|jpeg|png|webp)$", re.IGNORECASE)
BATCH = 150
WORKERS = 12
SAVE_EVERY = 10  # batches

OUT = Path(__file__).resolve().parent / "config" / "postmeta.json"


def load_existing() -> dict:
    if OUT.exists():
        try:
            return json.load(open(OUT, encoding="utf-8"))
        except Exception:
            pass
    return {}


def scan_files() -> dict:
    """pid -> subreddit (from filename)."""
    out = {}
    for f in REDDIT_DATA_DIR.iterdir():
        if not f.is_file():
            continue
        m = FILENAME_RE.match(f.name)
        if m:
            out[m.group("pid")] = m.group("sub")
    return out


def fetch_batch(ids: list, session: requests.Session, fields: str):
    try:
        r = session.get(IDS_URL, params={"ids": ",".join(ids), "fields": fields}, timeout=90)
        r.raise_for_status()
        return {p["id"]: p for p in r.json().get("data", []) if isinstance(p, dict) and p.get("id")}
    except Exception as e:
        # retry once after a short backoff
        try:
            time.sleep(5)
            r = session.get(IDS_URL, params={"ids": ",".join(ids), "fields": fields}, timeout=90)
            r.raise_for_status()
            return {p["id"]: p for p in r.json().get("data", []) if isinstance(p, dict) and p.get("id")}
        except Exception:
            return {}


def main():
    existing = load_existing()
    files = scan_files()
    todo = [pid for pid in files if pid not in existing]
    print(f"files on disk: {len(files)} | already have meta: {len(existing)} | to fetch: {len(todo)}", flush=True)

    if not todo:
        print("Nothing to fetch.")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": "MakeMeMemeDatasetCollector/1.0"})
    meta = dict(existing)
    lock = Lock()
    done = 0
    failed = 0

    def worker(ids):
        return fetch_batch(ids, session, FIELDS)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
        futures = [pool.submit(worker, b) for b in batches]
        for i, fut in enumerate(as_completed(futures), 1):
            res = fut.result()
            with lock:
                for pid, post in res.items():
                    meta[pid] = {
                        "upvotes": post.get("score", 0) or 0,
                        "comments": post.get("num_comments", 0) or 0,
                        "title": (post.get("title") or "")[:300],
                        "author": post.get("author", ""),
                        "created_utc": post.get("created_utc", 0) or 0,
                        "url": post.get("url", ""),
                        "subreddit": post.get("subreddit", files.get(pid, "unknown")),
                        "over_18": bool(post.get("over_18")),
                        "spoiler": bool(post.get("spoiler")),
                    }
                done += 1
                if done % SAVE_EVERY == 0:
                    json.dump(meta, open(OUT, "w", encoding="utf-8"))
                    print(f"  [{done}/{len(batches)}] fetched, {len(meta)} total saved", flush=True)

    # final save
    json.dump(meta, open(OUT, "w", encoding="utf-8"))
    print(f"\nDone. {len(meta)} post-meta records saved to {OUT.name} (failed batches: {failed})", flush=True)


if __name__ == "__main__":
    main()
