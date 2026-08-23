"""
Reddit Comment Image Scraper - isolated from main post scraper.

Collects ONLY images posted inside comments (body markdown) for training.
Stored in data/reddit_comments/ with separate seen state and dedup.

Does NOT touch:
- data/reddit/ (post images)
- config/seen_reddit_posts.json / seen_reddit_urls.json
- collection.lock

Uses its own:
- data/reddit_comments/
- config/seen_comment_ids.json / seen_comment_urls.json
- collection_comments.lock
"""

import os
import re
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
    REDDIT_COMMENTS_DATA_DIR,
    MIN_RESOLUTION,
    MAX_FILE_SIZE_MB,
    SUBREDDIT_META,
    DEFAULT_SUB_META,
)
from utils.dedup import Deduplicator
from utils.quality import passes_quality_check_img, compute_quality_score, get_image_info_from_img, classify_image_type_from_info
from utils.enrichment import enrich

from PIL import Image

# Arctic Shift endpoints
ARCTIC_POSTS = "https://arctic-shift.photon-reddit.com/api/posts/search"
ARCTIC_COMMENTS = "https://arctic-shift.photon-reddit.com/api/comments/search"

POST_FIELDS = "id,title,score,num_comments,created_utc,author"
COMMENT_FIELDS = "id,body,score,author,created_utc,link_id,parent_id,subreddit"

# Regex to extract direct image URLs from comment body markdown
# Handles: https://i.redd.it/xxx.jpg , https://preview.redd.it/xxx.jpg?width=1080&auto=webp , https://i.imgur.com/xxx.png
IMAGE_URL_RE = re.compile(
    r"https?://[^\s\)\]\"'<>]+?\.(?:jpg|jpeg|png|webp)(?:\?[^\s\)\]\"'<>]*)?",
    re.IGNORECASE,
)
# Fallback: redd.it short links without extension but with image host
REDDIT_HOST_RE = re.compile(
    r"https?://(?:i\.redd\.it|preview\.redd\.it|i\.imgur\.com|external-preview\.redd\.it)[^\s\)\]\"'<>]+",
    re.IGNORECASE,
)

STATIC_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
REQUEST_DELAY = 1.0
DOWNLOAD_WORKERS = 8
COMMENT_SEARCH_DELAY = 0.8


class RedditCommentScraper:
    def __init__(self, score_floor: int = 50, max_comments_per_post: int = 20):
        self.score_floor = score_floor
        self.max_comments_per_post = max_comments_per_post
        self.dedup = Deduplicator()
        self.collected: List[Dict] = []
        self.data_dir = REDDIT_COMMENTS_DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MakeMeMemeDatasetCollector-Comments/1.0"})
        self.seen_comment_ids: Set[str] = self._load_json_set("seen_comment_ids.json")
        self.seen_urls: Set[str] = self._load_json_set("seen_comment_urls.json")
        # stats
        self.stats = {"posts_scanned": 0, "comments_scanned": 0, "image_urls_found": 0, "downloaded": 0, "kept": 0}

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
        json.dump(sorted(self.seen_comment_ids), open(cfg / "seen_comment_ids.json", "w"), indent=0)
        json.dump(sorted(self.seen_urls), open(cfg / "seen_comment_urls.json", "w"), indent=0)

    # ---------- Arctic API helpers ----------

    def _search_posts(self, subreddit: str, before: Optional[int] = None) -> tuple:
        params = {
            "subreddit": subreddit,
            "fields": POST_FIELDS,
            "sort": "desc",
            "limit": 100,
        }
        if before:
            params["before"] = int(before)
        for attempt in range(5):
            try:
                r = self.session.get(ARCTIC_POSTS, params=params, timeout=60)
                if r.status_code == 429:
                    wait = int(r.headers.get("X-RateLimit-Reset", 20))
                    print(f"      posts rate limited, wait {wait}s", flush=True)
                    time.sleep(wait)
                    continue
                if r.status_code == 422 or "Timeout" in r.text[:200]:
                    wait = 10 * (attempt + 1)
                    print(f"      posts query timeout, backoff {wait}s", flush=True)
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
                print(f"      posts attempt {attempt+1}/5 error: {str(e)[:80]}", flush=True)
                time.sleep(8 * (attempt + 1))
        return [], None, "max_retries"

    def _search_comments(self, link_id: str) -> tuple:
        """
        Fetch comments for a single post link_id.
        link_id is expected as 't3_xxxx' or 'xxxx' - Arctic wants without prefix? test both.
        We'll try with raw id first.
        """
        # Arctic expects link_id like "t3_1abc" or just id? Use as stored.
        # Try with t3_ prefix if not present
        if not link_id.startswith("t3_"):
            link_id_q = f"t3_{link_id}"
        else:
            link_id_q = link_id
        params = {
            "link_id": link_id_q,
            "fields": COMMENT_FIELDS,
            "sort": "desc",
            "limit": 100,
        }
        for attempt in range(5):
            try:
                r = self.session.get(ARCTIC_COMMENTS, params=params, timeout=60)
                if r.status_code == 429:
                    wait = int(r.headers.get("X-RateLimit-Reset", 15))
                    time.sleep(wait)
                    continue
                if r.status_code == 422 or "Timeout" in r.text[:200]:
                    wait = 8 * (attempt + 1)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                j = r.json()
                err = j.get("error") or j.get("detail")
                if err:
                    return [], str(err)
                comments = j.get("data") or []
                return comments, None
            except Exception as e:
                time.sleep(5 * (attempt + 1))
                if attempt == 4:
                    return [], str(e)[:80]
        return [], "max_retries"

    # ---------- Image URL extraction ----------

    @staticmethod
    def _extract_image_urls(body: str) -> List[str]:
        if not body:
            return []
        urls = []
        # primary: extension-based
        for m in IMAGE_URL_RE.finditer(body):
            url = m.group(0).rstrip(".,!;")
            # clean preview redd.it width params but keep url
            # filter out non-static hosts if needed, but keep all
            # need to strip trailing ) that regex may include
            url = url.rstrip(")")
            urls.append(url)
        # fallback: redd.it hosts without extension (tmp keep if not already found)
        # Only add if not already captured and looks like image
        if not urls:
            for m in REDDIT_HOST_RE.finditer(body):
                url = m.group(0).rstrip(".,!;)")
                # only keep if likely image (has preview or i.redd.it)
                if "i.redd.it" in url or "preview.redd.it" in url:
                    # add .jpg assumption? but better skip without ext - will be filtered later
                    # try to keep only if url contains image-like token
                    if url not in urls:
                        urls.append(url)
        # dedup preserve order
        seen = set()
        out = []
        for u in urls:
            # Normalize: strip query for ext check but keep full for download
            # we keep full url for download
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    @staticmethod
    def _is_static_image(url: str) -> bool:
        u = url.lower().split("?")[0]
        return any(u.endswith(ext) for ext in STATIC_EXTS)

    # ---------- Download + finalize (same pattern as arctic scraper) ----------

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

    def _finalize_image(self, job: Dict) -> Optional[Dict]:
        save_path = job["save_path"]
        comment = job["comment"]
        post = job["post"]
        url = job["url"]
        subreddit = job["subreddit"]

        try:
            img = Image.open(save_path)
            img.load()
        except Exception:
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

        # Build training-helpful record
        sub_meta = SUBREDDIT_META.get(subreddit.lower(), DEFAULT_SUB_META)
        created = comment.get("created_utc", 0)
        # parent post fields
        post_created = post.get("created_utc", 0)
        # clean comment body (strip image markdown)
        raw_body = comment.get("body", "") or ""
        # truncate and strip url from body for text feature
        clean_body = IMAGE_URL_RE.sub("", raw_body).strip()
        clean_body = re.sub(r"\s+", " ", clean_body)[:500]

        # Relative path for portability
        try:
            rel_path = str(save_path.relative_to(Path(__file__).resolve().parent.parent))
        except ValueError:
            rel_path = str(save_path)

        record = {
            "id": str(uuid.uuid4()),
            "source": "reddit_comment",
            "source_sub": f"r/{subreddit}",
            "source_id": comment.get("id", ""),
            "parent_post_id": post.get("id", ""),
            "source_url": f"https://www.reddit.com/r/{subreddit}/comments/{post.get('id','')}/_/{comment.get('id','')}/",
            "parent_post_url": f"https://www.reddit.com/r/{subreddit}/comments/{post.get('id','')}/",
            "image_url": url,
            "image_path": rel_path,
            # post context
            "post_title": (post.get("title") or "")[:300],
            "post_author": post.get("author", ""),
            "post_upvotes": post.get("score", 0),
            "post_comments": post.get("num_comments", 0),
            "post_created_utc": post_created,
            # comment context
            "comment_body": clean_body,
            "comment_body_raw": (raw_body or "")[:500],
            "comment_author": comment.get("author", ""),
            "comment_score": comment.get("score", 0),
            "comment_subreddit": comment.get("subreddit", subreddit),
            "posted_at": datetime.fromtimestamp(created, tz=timezone.utc).isoformat() if created else "",
            "post_posted_at": datetime.fromtimestamp(post_created, tz=timezone.utc).isoformat() if post_created else "",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            # image technical
            "title": (post.get("title") or "")[:300],  # for enrich compatibility
            "author": comment.get("author", ""),
            "upvotes": comment.get("score", 0),
            "comments": 0,
            "quality_score": compute_quality_score(
                upvotes=comment.get("score", 0),
                comments=0,
                resolution=info["resolution"] if info else (0, 0),
            ),
            "image_type": classify_image_type_from_info(info),
            "resolution": [info["width"], info["height"]] if info else [0, 0],
            "format": info["format"] if info else "",
            "file_size_kb": info["file_size_kb"] if info else 0,
            "community_category": sub_meta["category"],
            "community_audience": sub_meta["audience"],
        }
        # Enrich adds: humor_signal, title_style, virality, platform_fit, etc.
        # enrich expects title, posted_at, upvotes, image_path
        enrich(record, img=img)
        self.seen_urls.add(url)
        self.collected.append(record)
        self.stats["kept"] += 1
        return record

    # ---------- Public API ----------

    def scrape_comments_for_post(self, post: Dict, subreddit: str) -> int:
        """Fetch comments for one post, download+finalize images. Returns count kept."""
        link_id = post.get("id", "")
        if not link_id:
            return 0
        comments, err = self._search_comments(link_id)
        if err:
            # print once per failure
            # print(f"      comments error for {link_id}: {err}", flush=True)
            return 0
        if not comments:
            return 0
        self.stats["comments_scanned"] += len(comments)
        # filter good comments first (cheap)
        candidates = []
        for c in comments:
            cid = c.get("id", "")
            if not cid or cid in self.seen_comment_ids:
                continue
            if c.get("score", 0) < self.score_floor:
                continue
            body = c.get("body", "") or ""
            if not body or body in ("[removed]", "[deleted]"):
                continue
            urls = self._extract_image_urls(body)
            if not urls:
                continue
            # need to mark seen even if we skip download due to url dup?
            # we will mark per-url after finalization, but mark comment id now to avoid re-scanning
            self.seen_comment_ids.add(cid)
            # take up to 2 image urls per comment (usually 1)
            for url in urls[:2]:
                if not self._is_static_image(url):
                    continue
                if url in self.seen_urls:
                    continue
                ext = Path(url.split("?")[0]).suffix.lower() or ".jpg"
                # avoid .gif
                if ext == ".gif":
                    continue
                filename = f"{subreddit}_{post.get('id','')}_{cid}_{len(candidates)}{ext}"
                save_path = self.data_dir / filename
                if save_path.exists():
                    self.seen_urls.add(url)
                    continue
                candidates.append({"comment": c, "post": post, "subreddit": subreddit, "url": url, "save_path": save_path})
                self.stats["image_urls_found"] += 1
                # limit per post
                if len(candidates) >= self.max_comments_per_post:
                    break
            if len(candidates) >= self.max_comments_per_post:
                break

        if not candidates:
            return 0

        # Parallel download
        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
            futures = {pool.submit(self._download_image, job["url"], job["save_path"]): job for job in candidates}
            downloaded = []
            for fut in as_completed(futures):
                if fut.result():
                    downloaded.append(futures[fut])
                    self.stats["downloaded"] += 1
        kept = 0
        for job in downloaded:
            if self._finalize_image(job):
                kept += 1
        return kept

    def scrape_subreddit(self, subreddit: str, max_posts: int = 500, date_floor: str = "2024-01-01", min_post_comments: int = 2) -> int:
        count_before = len(self.collected)
        before: Optional[int] = None
        pages = 0
        posts_evaluated = 0  # all posts seen from API
        posts_with_comments = 0  # posts that passed min_post_comments and were scanned for comment images

        while posts_with_comments < max_posts and posts_evaluated < max_posts * 20:
            posts, oldest, err = self._search_posts(subreddit, before)
            pages += 1
            if err:
                print(f"      page {pages}: stopped ({err})", flush=True)
                break
            if not posts:
                break
            # debug
            if pages <= 5 or pages % 5 == 0:
                dt = datetime.fromtimestamp(oldest, tz=timezone.utc).strftime("%Y-%m-%d") if oldest else "?"
                avg_c = sum(p.get("num_comments",0) for p in posts)/len(posts) if posts else 0
                print(f"      page {pages}: {len(posts)} posts avg_comments {avg_c:.1f} oldest {dt}", flush=True)
            for post in posts:
                if posts_with_comments >= max_posts or posts_evaluated >= max_posts * 20:
                    break
                posts_evaluated += 1
                # date floor check
                if date_floor:
                    try:
                        floor_ts = datetime.fromisoformat(date_floor).replace(tzinfo=timezone.utc).timestamp()
                        if post.get("created_utc", 0) < floor_ts:
                            print(f"      floor reached at page {pages}", flush=True)
                            return len(self.collected) - count_before
                    except Exception:
                        pass
                if post.get("num_comments", 0) < min_post_comments:
                    continue
                kept = self.scrape_comments_for_post(post, subreddit)
                posts_with_comments += 1
                self.stats["posts_scanned"] += 1
                # small delay between posts to avoid hammering
                time.sleep(COMMENT_SEARCH_DELAY)
                # periodic checkpoint
                if posts_with_comments % 20 == 0 and posts_with_comments>0:
                    print(f"      posts {posts_with_comments}/{max_posts} (evaluated {posts_evaluated}) pages {pages} kept {len(self.collected)-count_before} (at {datetime.fromtimestamp(oldest, tz=timezone.utc).strftime('%Y-%m-%d') if oldest else '?'})", flush=True)
                    self._save_state()

            # pagination
            if oldest and oldest < (before or float('inf')):
                before = oldest
            else:
                # fallback: decrement
                before = (before or int(datetime.now(timezone.utc).timestamp())) - 3600
            time.sleep(REQUEST_DELAY)
            if pages % 3 == 0:
                self._save_state()
                self.dedup.save()
            # date floor outer
            if date_floor and oldest:
                try:
                    floor_ts = datetime.fromisoformat(date_floor).replace(tzinfo=timezone.utc).timestamp()
                    if oldest < floor_ts:
                        break
                except Exception:
                    pass
            if not before:
                break

        self._save_state()
        self.dedup.save()
        added = len(self.collected) - count_before
        print(f"    r/{subreddit}: +{added} comment images ({posts_with_comments} posts with comments, {posts_evaluated} evaluated, {pages} post pages) stats {self.stats}", flush=True)
        return added

    def scrape_all(self, subreddits: List[str], max_posts_per_sub: int = 500, date_floor: str = "2024-01-01") -> List[Dict]:
        total_before = len(self.collected)
        for i, sub in enumerate(subreddits, 1):
            print(f"  [{i}/{len(subreddits)}] r/{sub} (comments)", flush=True)
            try:
                self.scrape_subreddit(sub, max_posts_per_sub, date_floor)
            except Exception as e:
                print(f"    FAILED r/{sub}: {e}", flush=True)
                import traceback; traceback.print_exc()
            if i % 3 == 0:
                self.dedup.save()
                self._save_state()
                print(f"    [checkpoint] total collected: {len(self.collected)}", flush=True)
        self.dedup.save()
        self._save_state()
        print(f"\nComment images new this run: {len(self.collected) - total_before} total {len(self.collected)}", flush=True)
        return self.collected

    def get_collected(self) -> List[Dict]:
        return self.collected


if __name__ == "__main__":
    # quick manual test
    s = RedditCommentScraper(score_floor=20, max_comments_per_post=5)
    s.scrape_all(["memes"], max_posts_per_sub=5)
    print(f"Total: {len(s.get_collected())}")
