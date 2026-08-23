"""Collect memes until data/curated holds TARGET memes.

Checkpointing guarantees no data loss on stop:
  - every downloaded image is written to disk (atomic .part -> final) immediately
  - curated_metadata.json + dedup/seen state are saved every CHECKPOINT memes
    and at the end of every subreddit, and on Ctrl-C / any error (finally block)
  - the curated images are the source of truth; the metadata index is also
    rebuildable from config/postmeta.json + the files, so it can never be the
    single point of loss.

Run:  python collect_to_target.py            (targets 120000)
      python collect_to_target.py --target 150000
"""
import argparse
import json
import os
import re
import sys
import time
import uuid
import shutil
import threading
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config.settings import (
    BASE_DIR, DATA_DIR, REDDIT_SUBREDDITS, REDDIT_DATE_FLOOR,
    MIN_RESOLUTION as _IGNORED, TEMPLATE_SUBREDDITS,
)
from utils.dedup import Deduplicator

ARCTIC_BASE = "https://arctic-shift.photon-reddit.com/api/posts/search"
FIELDS = "id,title,score,num_comments,url,created_utc,author,over_18,post_hint,link_flair_text,spoiler,selftext,subreddit"
STATIC_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
REQUEST_DELAY = 1.2
DOWNLOAD_WORKERS = 10
MIN_RES = (400, 400)
MIN_KB = 20
UPVOTE_MIN = 5
CHECKPOINT = 250
RESUME_SKIP_THRESHOLD = 2500  # per-sub cap for 50k balanced run (~3000 max)
CURATED_DIR = DATA_DIR / "curated"
FILENAME_RE = re.compile(r"^(?P<sub>.+)_(?P<pid>[A-Za-z0-9]{4,12})\.(jpg|png)$", re.IGNORECASE)
LOCK_FILE = BASE_DIR / "collect_target.lock"
LOG_FILE = BASE_DIR / "collect_target.log"

# Image optimization
MAX_DIM = 1920          # max width/height
JPEG_QUALITY = 85       # JPEG quality for converted images
MAX_FILE_KB = 2048      # 2 MB cap after optimization


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class Lock:
    def __enter__(self):
        if LOCK_FILE.exists():
            try:
                pid = int(LOCK_FILE.read_text().strip())
                import ctypes
                if pid > 0 and ctypes.windll.kernel32.OpenProcess(0x1000, False, pid):
                    log(f"ERROR: another collection (pid {pid}) is running. Delete {LOCK_FILE.name} if wrong.")
                    sys.exit(1)
            except Exception:
                pass
        LOCK_FILE.write_text(str(os.getpid()))
        return self
    def __exit__(self, *a):
        LOCK_FILE.unlink(missing_ok=True)


def is_static(url):
    u = url.lower().split("?")[0]
    return any(u.endswith(e) for e in STATIC_EXTS)


def search_page(session, sub, before, attempt_total=8):
    params = {"subreddit": sub, "fields": FIELDS, "sort": "desc", "limit": "auto"}
    if before:
        params["before"] = int(before)
    for attempt in range(attempt_total):
        try:
            r = session.get(ARCTIC_BASE, params=params, timeout=90)
            if r.status_code == 429:
                wait = int(r.headers.get("X-RateLimit-Reset", 30))
                log(f"  rate limited, wait {wait}s"); time.sleep(wait); continue
            if r.status_code == 422 or "Timeout" in r.text[:200]:
                wait = 15 * (attempt + 1)
                log(f"  query timeout, backoff {wait}s"); time.sleep(wait); continue
            r.raise_for_status()
            j = r.json()
            err = j.get("error") or j.get("detail")
            if err:
                return [], None, str(err)
            posts = j.get("data") or []
            oldest = min((p["created_utc"] for p in posts), default=None)
            return posts, oldest, None
        except Exception as e:
            log(f"  attempt {attempt+1}/{attempt_total} error: {str(e)[:70]}")
            time.sleep(10 * (attempt + 1))
    return [], None, "max_retries"


def download(session, url, save_path):
    part = Path(str(save_path) + ".part")
    try:
        resp = session.get(url, timeout=30, stream=True, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "")
        if "gif" in ct or "video" in ct or "html" in ct:
            return False
        with open(part, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
        sz = part.stat().st_size
        if sz < 5000 or sz > 10 * 1024 * 1024:
            part.unlink(missing_ok=True); return False
        # Optimize image: resize + convert to JPEG (except templates)
        if not optimize_image(part, save_path):
            part.unlink(missing_ok=True); return False
        part.unlink(missing_ok=True)
        return True
    except Exception:
        part.unlink(missing_ok=True); return False


def optimize_image(src_path, dst_path):
    """Resize to MAX_DIM, convert to JPEG (quality 85), enforce MAX_FILE_KB.
    Keeps PNG only for template subreddits."""
    try:
        with Image.open(src_path) as img:
            img.load()
            w, h = img.size
            fmt = img.format
            if max(w, h) > MAX_DIM:
                scale = MAX_DIM / max(w, h)
                img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            is_template = dst_path.parent.name.lower() in TEMPLATE_SUBREDDITS
            if is_template and fmt == "PNG":
                img.save(dst_path, "PNG", optimize=True)
            else:
                if img.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                    img = bg
                elif img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(dst_path, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        if dst_path.stat().st_size > MAX_FILE_KB * 1024:
            dst_path.unlink(missing_ok=True)
            return False
        return True
    except Exception:
        return False


def curated_count():
    return sum(1 for _ in CURATED_DIR.rglob("*") if _.is_file())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=50000)
    ap.add_argument("--subs", type=str, default="")
    ap.add_argument("--parallel", type=int, default=2, help="number of subreddits to collect in parallel")
    args = ap.parse_args()
    TARGET = args.target
    subs = args.subs.split(",") if args.subs else REDDIT_SUBREDDITS
    PARALLEL = args.parallel
    # Diversity: prioritize least-collected subs first (templates, underrepresented)
    # sub_counts available after loading records, so we sort there; initial sort by name for deterministic
    # Actual sorting done after sub_counts computed below

    dedup = Deduplicator()
    slock = threading.Lock()   # protects records, seen_post_ids, seen_urls, dedup
    ckpt_state = {"new": 0}

    # ---- load existing curated as the starting point ----
    records = []
    seen_post_ids = set()
    seen_urls = set()
    if (BASE_DIR / "curated_metadata.json").exists():
        records = json.load(open(BASE_DIR / "curated_metadata.json", encoding="utf-8"))
        for r in records:
            if r.get("source_id"):
                seen_post_ids.add(r["source_id"])
            if r.get("image_url"):
                seen_urls.add(r["image_url"])
    # Also load seen files (contain filtered pids/urls not in curated, e.g. low_upvotes, duplicates)
    # This prevents re-downloading same filtered posts after a run that overwrote seen files
    for seen_file, target_set in [
        (BASE_DIR / "config" / "seen_reddit_posts.json", seen_post_ids),
        (BASE_DIR / "config" / "seen_reddit_urls.json", seen_urls),
    ]:
        if seen_file.exists():
            try:
                extra = json.load(open(seen_file, encoding="utf-8"))
                if isinstance(extra, list):
                    target_set.update(extra)
                elif isinstance(extra, dict) and "seen" in extra:
                    target_set.update(extra["seen"])
            except Exception as e:
                log(f"warn: could not load {seen_file.name}: {e}")
    log(f"starting with {len(records)} already-curated memes; target {TARGET} (seen_posts={len(seen_post_ids)} seen_urls={len(seen_urls)})")

    # resume optimization: skip subreddits already near their cap
    sub_counts = {}
    for r in records:
        s = (r.get("source_sub") or "").replace("r/", "")
        sub_counts[s] = sub_counts.get(s, 0) + 1
    # Keep original REDDIT_SUBREDDITS order (high-yield first) but skip saturated subs via RESUME_SKIP_THRESHOLD
    # Previous ascending sort caused thrash on low-yield subs like BoneHurtingJuice (0) before high-yield like dankmemes
    if not args.subs:
        log(f"sub order: original REDDIT_SUBREDDITS, skipping >= {RESUME_SKIP_THRESHOLD}")
        # Optional: log underrepresented subs (<500) that will be filled first due to early position
        under = [s for s in subs if sub_counts.get(s,0) < 500]
        log(f"underrepresented (<500): {under[:10]}...")

    def save_state():
        with slock:
            # atomic writes to avoid corruption on kill
            tmp = BASE_DIR / "curated_metadata.json.tmp"
            json.dump(records, open(tmp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
            tmp.replace(BASE_DIR / "curated_metadata.json")
            # also mirror to data/
            tmp2 = DATA_DIR / "curated_metadata.json.tmp"
            json.dump(records, open(tmp2, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
            tmp2.replace(DATA_DIR / "curated_metadata.json")
            dedup.save()
            tmp = BASE_DIR / "config" / "seen_reddit_posts.json.tmp"
            json.dump(sorted(seen_post_ids), open(tmp, "w", encoding="utf-8"), indent=0)
            tmp.replace(BASE_DIR / "config" / "seen_reddit_posts.json")
            tmp = BASE_DIR / "config" / "seen_reddit_urls.json.tmp"
            json.dump(sorted(seen_urls), open(tmp, "w", encoding="utf-8"), indent=0)
            tmp.replace(BASE_DIR / "config" / "seen_reddit_urls.json")

    def collect_sub(sub, idx):
        nonlocal TARGET
        if sub_counts.get(sub, 0) >= RESUME_SKIP_THRESHOLD:
            log(f"[{idx+1}/{len(subs)}] r/{sub} already has {sub_counts[sub]} -> skip (resume)")
            return
        log(f"[{idx+1}/{len(subs)}] r/{sub}  (curated={len(records)}/{TARGET})")
        sess = requests.Session()
        sess.headers.update({"User-Agent": "MakeMeMemeDatasetCollector/1.0"})
        before = None
        pages = 0
        empty_streak = 0
        skip_streak = 0          # pages yielding 0 new downloads (fast-forward)
        SKIP_JUMP_DAYS = 7       # when skip_streak >= 3, jump this many days (7 for 50k balanced, was 30)
        while True:
            with slock:
                if len(records) >= TARGET:
                    return
            posts, oldest, err = search_page(sess, sub, before)
            pages += 1
            if err:
                log(f"  page {pages}: stopped ({err})"); break
            if not posts:
                empty_streak += 1
                if empty_streak >= 2:
                    break
                before = (before or int(datetime.now(timezone.utc).timestamp())) - 3600
                continue
            empty_streak = 0

            # filter cheaply under lock
            with slock:
                _page_start = len(records)
                jobs = []
                for p in posts:
                    pid = p.get("id", "")
                    url = p.get("url", "") or ""
                    if not pid or pid in seen_post_ids:
                        continue
                    seen_post_ids.add(pid)
                    if p.get("over_18") or p.get("spoiler"):
                        continue
                    if not is_static(url) or url.lower().endswith(".gif"):
                        continue
                    if url in seen_urls:
                        continue
                    s = sub or p.get("subreddit", "unknown")
                    is_template = s.lower() in TEMPLATE_SUBREDDITS
                    ext = ".png" if is_template else ".jpg"
                    save = CURATED_DIR / s / f"{s}_{pid}{ext}"
                    if save.exists():
                        seen_urls.add(url); continue
                    jobs.append({"post": p, "sub": s, "url": url, "save": save})

            # parallel download (no lock needed — each job is independent)
            downloaded = []
            if jobs:
                CURATED_DIR.mkdir(parents=True, exist_ok=True)
                with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
                    futs = {pool.submit(download, sess, j["url"], j["save"]): j for j in jobs}
                    for fut in as_completed(futs):
                        if fut.result():
                            downloaded.append(futs[fut])

            # finalize under lock: quality + upvote + dedup + record
            with slock:
                for job in downloaded:
                    p = job["post"]; s = job["sub"]; url = job["url"]; save = job["save"]
                    template = s.lower() in TEMPLATE_SUBREDDITS
                    try:
                        with Image.open(save) as img:
                            img.load()
                            w, h = img.size; fmt = img.format
                    except Exception:
                        save.unlink(missing_ok=True); continue
                    sz = save.stat().st_size / 1024
                    if w < MIN_RES[0] or h < MIN_RES[1]:
                        save.unlink(missing_ok=True); continue
                    if sz < MIN_KB:
                        save.unlink(missing_ok=True); continue
                    up = p.get("score", 0) or 0
                    if not template and up < UPVOTE_MIN:
                        save.unlink(missing_ok=True); continue
                    hsh = dedup.compute_hash(str(save))
                    if hsh is None or dedup.is_duplicate(hash_hex=hsh):
                        save.unlink(missing_ok=True); continue
                    dedup.register(hash_hex=hsh)
                    rec = {
                        "id": str(uuid.uuid4()), "source": "reddit", "source_sub": f"r/{s}",
                        "source_id": p.get("id", ""), "source_url": f"https://www.reddit.com/r/{s}/comments/{p.get('id','')}/",
                        "image_url": url, "image_path": str(save.relative_to(BASE_DIR)),
                        "title": (p.get("title") or "")[:300], "author": p.get("author", ""),
                        "upvotes": up, "comments": p.get("num_comments", 0) or 0,
                        "quality_score": round(min(up/50000,1.0)*0.5 + min((w*h)/(1920*1080),1.0)*0.5, 3),
                        "image_type": ("square" if 0.9 <= w/h <= 1.1 else ("portrait" if w/h < 0.9 else "landscape")),
                        "nsfw": False, "collected_at": datetime.now(timezone.utc).isoformat(),
                        "posted_at": datetime.fromtimestamp(p.get("created_utc",0), tz=timezone.utc).isoformat() if p.get("created_utc") else "",
                        "resolution": [w, h], "format": fmt or "", "file_size_kb": round(sz, 2),
                        "community_category": "template" if template else "general",
                    }
                    records.append(rec)
                    seen_urls.add(url)
                    ckpt_state["new"] += 1

            if pages % 3 == 0:
                dt = datetime.fromtimestamp(oldest, tz=timezone.utc).strftime("%Y-%m-%d") if oldest else "?"
                log(f"  page {pages}: curated={len(records)} (at {dt})")
            with slock:
                if ckpt_state["new"] >= CHECKPOINT:
                    save_state(); ckpt_state["new"] = 0
                    log(f"  [checkpoint] saved {len(records)}")

            # track pages yielding 0 new downloads -> fast-forward (capped to avoid thrash on low-yield subs)
            page_new = len(records) - _page_start
            if page_new == 0 and posts:
                skip_streak += 1
                if skip_streak >= 3 and skip_streak <= 6 and oldest:
                    jump = oldest - (SKIP_JUMP_DAYS * 86400)
                    floor = datetime.fromisoformat(REDDIT_DATE_FLOOR).replace(tzinfo=timezone.utc).timestamp() if REDDIT_DATE_FLOOR else 0
                    if jump > floor:
                        before = jump
                        log(f"  fast-forward {SKIP_JUMP_DAYS}d (skip_streak={skip_streak}) for r/{sub}")
                        time.sleep(REQUEST_DELAY)
                        continue
                elif skip_streak > 6:
                    log(f"  r/{sub} stuck {skip_streak} pages with 0 new -> skip sub (yield too low)")
                    break
            else:
                skip_streak = 0

            if REDDIT_DATE_FLOOR:
                floor = datetime.fromisoformat(REDDIT_DATE_FLOOR).replace(tzinfo=timezone.utc).timestamp()
                if oldest and oldest < floor:
                    break
            before = oldest
            if not before:
                break
            time.sleep(REQUEST_DELAY)
        save_state()

    try:
        log(f"launching {PARALLEL} parallel collectors across {len(subs)} subs")
        with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
            futures = {pool.submit(collect_sub, sub, i): sub for i, sub in enumerate(subs)}
            for fut in as_completed(futures):
                sub = futures[fut]
                try:
                    fut.result()
                except Exception as e:
                    log(f"  r/{sub} crashed: {e}")
                with slock:
                    if len(records) >= TARGET:
                        break
        log(f"TARGET REACHED: {len(records)} curated memes")
    except KeyboardInterrupt:
        log("Interrupted by user - saving state before exit.")
    except Exception as e:
        log(f"ERROR: {e} - saving state before exit.")
    finally:
        save_state()
        log(f"Final curated count: {len(records)} (files on disk: {curated_count()})")


if __name__ == "__main__":
    with Lock():
        main()
