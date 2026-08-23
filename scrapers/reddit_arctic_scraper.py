import os
import time
import uuid
import json
import requests
from pathlib import Path
from typing import List, Dict, Optional, Set
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import (
    REDDIT_DATA_DIR,
    MIN_RESOLUTION,
    MAX_FILE_SIZE_MB,
    SUBREDDIT_META,
    DEFAULT_SUB_META,
)
from utils.dedup import Deduplicator
from utils.quality import passes_quality_check_img, compute_quality_score, get_image_info_from_img, classify_image_type_from_info
from utils.enrichment import enrich

from PIL import Image

ARCTIC_BASE = "https://arctic-shift.photon-reddit.com/api/posts/search"
FIELDS = (
    "id,title,score,num_comments,url,created_utc,author,over_18,"
    "post_hint,link_flair_text,spoiler,selftext"
)
STATIC_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
REQUEST_DELAY = 1.2
DOWNLOAD_WORKERS = 10


class RedditArcticScraper:
    def __init__(self):
        self.dedup = Deduplicator()
        self.collected: List[Dict] = []
        self.data_dir = REDDIT_DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MakeMeMemeDatasetCollector/1.0"})
        self.seen_post_ids: Set[str] = self._load_json_set("seen_reddit_posts.json")
        self.seen_urls: Set[str] = self._load_json_set("seen_reddit_urls.json")

    @staticmethod
    def _load_json_set(name: str) -> Set[str]:
        p = Path(__file__).resolve().parent.parent / "config" / name
        if p.exists():
            try:
                return set(json.load(open(p, encoding="utf-8")))
            except Exception:
                pass
        return set()

    def _save_state(self):
        cfg = Path(__file__).resolve().parent.parent / "config"
        json.dump(sorted(self.seen_post_ids), open(cfg / "seen_reddit_posts.json", "w"), indent=0)
        json.dump(sorted(self.seen_urls), open(cfg / "seen_reddit_urls.json", "w"), indent=0)

    def _search_page(self, subreddit: str, before: Optional[int] = None, limit: str = "auto") -> tuple:
        params = {
            "subreddit": subreddit,
            "fields": FIELDS,
            "sort": "desc",
            "limit": limit,
        }
        if before:
            params["before"] = int(before)

        for attempt in range(8):
            try:
                r = self.session.get(ARCTIC_BASE, params=params, timeout=90)
                if r.status_code == 429:
                    wait = int(r.headers.get("X-RateLimit-Reset", 30))
                    print(f"      rate limited, wait {wait}s", flush=True)
                    time.sleep(wait)
                    continue
                # 422 from arctic = "Timeout. Maybe slow down a bit" (transient)
                if r.status_code == 422 or "Timeout" in r.text[:200]:
                    wait = 15 * (attempt + 1)
                    print(f"      query timeout, backing off {wait}s", flush=True)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                j = r.json()
                err = j.get("error") or j.get("detail")
                if err:
                    return [], None, str(err)
                posts = j.get("data") or []
                oldest = min((p["created_utc"] for p in posts), default=None)
                return posts, oldest, None
            except Exception as e:
                print(f"      attempt {attempt+1}/8 error: {str(e)[:70]}", flush=True)
                time.sleep(10 * (attempt + 1))
        return [], None, "max_retries"

    @staticmethod
    def _is_static_image(url: str) -> bool:
        u = url.lower().split("?")[0]
        return any(u.endswith(ext) for ext in STATIC_EXTS)

    def _download_image(self, url: str, save_path: Path) -> bool:
        part_path = Path(str(save_path) + ".part")
        try:
            resp = self.session.get(url, timeout=30, stream=True,
                                    headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "gif" in ct or "video" in ct or "html" in ct:
                return False
            with open(part_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            size = part_path.stat().st_size
            if size < 5000 or size > MAX_FILE_SIZE_MB * 1024 * 1024:
                part_path.unlink(missing_ok=True)
                return False
            os.replace(part_path, save_path)
            return True
        except Exception:
            part_path.unlink(missing_ok=True)
            return False

    def _filter_candidate(self, post: Dict, subreddit: str) -> Optional[Dict]:
        """Cheap checks only (no network). Returns a download job or None."""
        pid = post.get("id", "")
        url = post.get("url", "") or ""

        if not pid or pid in self.seen_post_ids:
            return None
        self.seen_post_ids.add(pid)

        if post.get("over_18") or post.get("spoiler"):
            return None
        if not self._is_static_image(url):
            return None
        if url.lower().endswith(".gif"):
            return None
        if url in self.seen_urls:
            return None

        subreddit = subreddit or post.get("subreddit", "unknown")
        ext = Path(url.split("?")[0]).suffix.lower() or ".jpg"
        filename = f"{subreddit}_{pid}{ext}"
        save_path = self.data_dir / filename

        if save_path.exists():
            self.seen_urls.add(url)
            return None

        return {"post": post, "subreddit": subreddit, "url": url, "save_path": save_path}

    def _finalize_image(self, job: Dict, listing_tag: str) -> Optional[Dict]:
        """Runs on main thread after parallel download: single decode for all checks."""
        save_path = job["save_path"]
        post = job["post"]
        subreddit = job["subreddit"]
        url = job["url"]

        img = None
        try:
            img = Image.open(save_path)
            img.load()
        except Exception:
            if img is not None:
                img.close()
            save_path.unlink(missing_ok=True)
            return None

        with img:
            passes, _ = passes_quality_check_img(img, str(save_path), MIN_RESOLUTION, MAX_FILE_SIZE_MB)
            if not passes:
                save_path.unlink(missing_ok=True)
                return None

            img_hash = self.dedup.compute_hash_from_img(img)
            if img_hash is None or self.dedup.is_duplicate(hash_hex=img_hash):
                save_path.unlink(missing_ok=True)
                return None
            self.dedup.register(hash_hex=img_hash)

            info = get_image_info_from_img(img, str(save_path))

        created = post.get("created_utc", 0)
        sub_meta = SUBREDDIT_META.get(subreddit.lower(), DEFAULT_SUB_META)
        record = {
            "id": str(uuid.uuid4()),
            "source": "reddit",
            "source_sub": f"r/{subreddit}",
            "source_listing": listing_tag,
            "source_id": post.get("id", ""),
            "source_url": f"https://www.reddit.com/r/{subreddit}/comments/{post.get('id', '')}/",
            "image_url": url,
            "image_path": str(save_path.relative_to(Path(__file__).resolve().parent.parent)),
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
        }
        enrich(record, img=img)
        self.seen_urls.add(url)
        self.collected.append(record)
        return record

    def scrape_subreddit(self, subreddit: str, max_images: int = 5000, date_floor: str = "") -> int:
        count_before = len(self.collected)
        before: Optional[int] = None
        pages = 0
        empty_streak = 0

        while len(self.collected) - count_before < max_images:
            posts, oldest, err = self._search_page(subreddit, before)
            pages += 1

            if err:
                print(f"      page {pages}: stopped ({err})", flush=True)
                break
            if not posts:
                empty_streak += 1
                if empty_streak >= 2:
                    break
                before = (before or int(datetime.now(timezone.utc).timestamp())) - 3600
                continue
            empty_streak = 0

            jobs = [j for j in (self._filter_candidate(p, subreddit) for p in posts) if j]
            if jobs:
                with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
                    futures = {pool.submit(self._download_image, j["url"], j["save_path"]): j for j in jobs}
                    downloaded = []
                    for fut in as_completed(futures):
                        if fut.result():
                            downloaded.append(futures[fut])
                for job in downloaded:
                    self._finalize_image(job, "arctic_history")

            if pages % 3 == 0:
                got = len(self.collected) - count_before
                dt = datetime.fromtimestamp(oldest, tz=timezone.utc).strftime("%Y-%m-%d")
                print(f"      page {pages}: {got} imgs (at {dt})", flush=True)
                self._save_state()

            if date_floor:
                floor_ts = datetime.fromisoformat(date_floor).replace(tzinfo=timezone.utc).timestamp()
                if oldest and oldest < floor_ts:
                    break

            before = oldest
            if not before:
                break
            time.sleep(REQUEST_DELAY)

        self._save_state()
        added = len(self.collected) - count_before
        print(f"    r/{subreddit}: +{added} images ({pages} pages)", flush=True)
        return added

    def scrape_all(self, subreddits: List[str], max_per_sub: int = 5000, date_floor: str = "") -> List[Dict]:
        total_before = len(self.collected)
        for i, sub in enumerate(subreddits, 1):
            print(f"  [{i}/{len(subreddits)}] r/{sub}", flush=True)
            try:
                self.scrape_subreddit(sub, max_per_sub, date_floor)
            except Exception as e:
                print(f"    FAILED: {e}", flush=True)
            if i % 3 == 0:
                self.dedup.save()
                print(f"    [checkpoint] total collected: {len(self.collected)}", flush=True)

        self.dedup.save()
        self._save_state()
        print(f"\nReddit new this run: {len(self.collected) - total_before}", flush=True)
        return self.collected

    def get_collected(self) -> List[Dict]:
        return self.collected


if __name__ == "__main__":
    s = RedditArcticScraper()
    s.scrape_all(["memes"], max_per_sub=50)
    print(f"Total: {len(s.get_collected())}")
