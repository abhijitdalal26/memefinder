import requests
import uuid
import time
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import (
    REDDIT_SUBREDDITS,
    REDDIT_DATA_DIR,
    MIN_RESOLUTION,
    MAX_FILE_SIZE_MB,
)
from utils.dedup import Deduplicator
from utils.quality import passes_quality_check, compute_quality_score, classify_image_type, get_image_info


class RedditScraper:
    API_BASE = "https://meme-api.com/gimme"
    MAX_BATCH = 50

    def __init__(self):
        self.dedup = Deduplicator()
        self.collected: List[Dict] = []
        self.data_dir = REDDIT_DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })

    def _get_extension(self, url: str) -> str:
        url_lower = url.lower().split("?")[0]
        if url_lower.endswith(".gif"):
            return ".gif"
        if url_lower.endswith(".png"):
            return ".png"
        if url_lower.endswith(".webp"):
            return ".webp"
        return ".jpg"

    def _download_image(self, url: str, save_path: Path) -> bool:
        try:
            resp = self.session.get(url, timeout=30, stream=True)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "video" in content_type:
                return False
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            file_size = save_path.stat().st_size
            if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
                save_path.unlink()
                return False
            if file_size < 1024:
                save_path.unlink()
                return False
            return True
        except Exception:
            if save_path.exists():
                save_path.unlink()
            return False

    def _fetch_batch(self, subreddit: str, count: int) -> List[Dict]:
        count = min(count, self.MAX_BATCH)
        url = f"{self.API_BASE}/{subreddit}/{count}"
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return data.get("memes", [])
        except Exception as e:
            print(f"  API error for r/{subreddit}: {e}")
            return []

    def _process_meme(self, meme_data: dict, subreddit: str) -> Optional[Dict]:
        if meme_data.get("nsfw"):
            return None
        if meme_data.get("spoiler"):
            return None

        img_url = meme_data.get("url", "")
        if not img_url:
            return None

        post_id = meme_data.get("id", str(uuid.uuid4())[:8])
        title = meme_data.get("title", "untitled")
        source_url = meme_data.get("postLink", img_url)
        upvotes = meme_data.get("ups", 0)

        ext = self._get_extension(img_url)
        filename = f"{subreddit}_{post_id}{ext}"
        save_path = self.data_dir / filename

        if save_path.exists():
            return None

        if not self._download_image(img_url, save_path):
            return None

        passes, reason = passes_quality_check(str(save_path), MIN_RESOLUTION, MAX_FILE_SIZE_MB)
        if not passes:
            save_path.unlink()
            return None

        if self.dedup.is_duplicate(str(save_path)):
            save_path.unlink()
            return None

        self.dedup.register(str(save_path))

        info = get_image_info(str(save_path))
        quality_score = compute_quality_score(
            upvotes=upvotes,
            resolution=info["resolution"] if info else (0, 0),
        )

        meme_record = {
            "id": str(uuid.uuid4()),
            "source": "reddit",
            "source_id": post_id,
            "source_url": source_url,
            "image_path": str(save_path.relative_to(Path(__file__).resolve().parent.parent)),
            "title": title,
            "subreddit": subreddit,
            "upvotes": upvotes,
            "comments": 0,
            "quality_score": quality_score,
            "image_type": classify_image_type(str(save_path)),
            "tags": [],
            "created_at": "",
            "collected_at": datetime.now().isoformat(),
            "resolution": list(info["resolution"]) if info else [0, 0],
            "format": info["format"] if info else ext.replace(".", ""),
            "file_size_kb": info["file_size_kb"] if info else 0,
        }
        return meme_record

    def scrape_subreddit(self, subreddit_name: str, limit: int = 30) -> List[Dict]:
        print(f"\n--- r/{subreddit_name} (limit={limit}) ---")
        memes = self._fetch_batch(subreddit_name, limit)
        print(f"  Fetched {len(memes)} from API")

        results = []
        for meme_data in memes:
            record = self._process_meme(meme_data, subreddit_name)
            if record:
                results.append(record)
                self.collected.append(record)

        print(f"  Collected {len(results)} memes from r/{subreddit_name}")
        return results

    def scrape_all(self, subreddits=None, limit_per_sub=30) -> List[Dict]:
        if subreddits is None:
            subreddits = REDDIT_SUBREDDITS

        all_memes = []
        for sub_name in subreddits:
            try:
                memes = self.scrape_subreddit(sub_name, limit_per_sub)
                all_memes.extend(memes)
                time.sleep(1)
            except Exception as e:
                print(f"  Error scraping r/{sub_name}: {e}")
                continue

        self.dedup.save()
        return all_memes

    def get_collected(self) -> List[Dict]:
        return self.collected


if __name__ == "__main__":
    scraper = RedditScraper()
    memes = scraper.scrape_all(limit_per_sub=10)
    print(f"\nTotal collected: {len(memes)} memes")
