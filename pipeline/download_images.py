"""Download meme images from image_url -> local files (resumable, concurrent).

Run locally (or on Colab) to populate IMAGES_DIR with the actual image bytes
referenced by the catalog's image_path. Skips files that already exist.

Env overrides: MAKEMEME_IMAGES (where to save), MAKEMEME_CATALOG.
"""
import os
import sys
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    CATALOG_FILE,
    IMAGES_DIR,
    resolve_image_path,
    meme_key,
)

HEADERS = {"User-Agent": "Mozilla/5.0 (MakeMeMeme image fetcher)"}
MAX_WORKERS = int(os.environ.get("MAKEMEME_WORKERS", "8"))


def target_path(image_path):
    rel = image_path.replace("\\", "/")
    if rel.startswith("data/"):
        rel = rel[len("data/"):]
    return os.path.join(IMAGES_DIR, rel)


def fetch(m):
    key = meme_key(m)
    url = m.get("image_url")
    ip = m.get("image_path")
    if not url or not ip:
        return key, "skip"
    out = target_path(ip)
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return key, "exists"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        if not data:
            return key, "empty"
        with open(out, "wb") as f:
            f.write(data)
        return key, "ok"
    except Exception as e:
        return key, f"err:{e}"


def main():
    with open(CATALOG_FILE, encoding="utf-8") as f:
        catalog = json.load(f)
    print(f"Catalog: {len(catalog)} memes | saving to {IMAGES_DIR}")

    stats = {"ok": 0, "exists": 0, "skip": 0, "empty": 0, "err": 0}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(fetch, m) for m in catalog]
        for fut in as_completed(futs):
            _, status = fut.result()
            if status.startswith("err"):
                stats["err"] += 1
            else:
                stats[status] = stats.get(status, 0) + 1
    print("Done:", stats)


if __name__ == "__main__":
    main()
