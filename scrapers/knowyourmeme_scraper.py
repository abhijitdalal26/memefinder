import requests
import uuid
import json
import time
import re
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from bs4 import BeautifulSoup
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import (
    KNOWYOURMEME_DATA_DIR,
    MIN_RESOLUTION,
    MAX_FILE_SIZE_MB,
)
from utils.dedup import Deduplicator
from utils.quality import passes_quality_check_img, compute_quality_score, classify_image_type_from_info, get_image_info_from_img
from utils.enrichment import enrich

from PIL import Image


class KnowYourMemeScraper:
    BASE_URL = "https://knowyourmeme.com"

    def __init__(self):
        self.dedup = Deduplicator()
        self.collected: List[Dict] = []
        self.data_dir = KNOWYOURMEME_DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

    def _download_image(self, url: str, save_path: Path) -> bool:
        try:
            if url.startswith("//"):
                url = "https:" + url
            resp = self.session.get(url, timeout=30, stream=True)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "video" in content_type or "text/html" in content_type or "gif" in content_type:
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

    def _get_extension(self, url: str) -> str:
        url_lower = url.lower().split("?")[0]
        if url_lower.endswith(".gif"):
            return ".gif"
        if url_lower.endswith(".png"):
            return ".png"
        if url_lower.endswith(".webp"):
            return ".webp"
        return ".jpg"

    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"  Fetch error: {e}")
            return None

    def _get_meme_links(self, page_url: str) -> List[Dict]:
        soup = self._fetch_page(page_url)
        if not soup:
            return []

        links = []
        for a_tag in soup.select("a[href]"):
            href = a_tag.get("href", "")
            if href.startswith("/memes/") and href.count("/") >= 2:
                slug = href.strip("/")
                if slug not in [l["slug"] for l in links]:
                    title = a_tag.get_text(strip=True)
                    if title and len(title) > 2:
                        links.append({"slug": slug, "title": title})
        return links

    def _get_meme_images(self, slug: str) -> Optional[Dict]:
        url = f"{self.BASE_URL}/{slug}"
        soup = self._fetch_page(url)
        if not soup:
            return None

        title_tag = soup.select_one("h1")
        title = title_tag.get_text(strip=True) if title_tag else slug.split("/")[-1]

        images = []
        for img in soup.select("section#photos img"):
            src = img.get("data-src", "")
            if not src:
                src = img.get("src", "")
            if not src or src.startswith("data:") or "blank" in src:
                continue
            if "kym-cdn.com/photos" in src:
                src = src.replace("/list/", "/original/")
                images.append(src)
            elif "kym-cdn.com/entries" in src:
                images.append(src)

        tags = []
        for tag_link in soup.select("a.tag, a[href*='/tags/']"):
            tag_text = tag_link.get_text(strip=True).lower()
            if tag_text and tag_text not in tags:
                tags.append(tag_text)

        created = ""
        time_tag = soup.select_one("time")
        if time_tag:
            created = time_tag.get("datetime", "")

        return {
            "title": title,
            "images": images[:5],
            "tags": tags[:10],
            "created_at": created,
            "url": url,
        }

    def _process_meme(self, slug: str, meme_info: dict) -> List[Dict]:
        processed = []
        title = meme_info.get("title", slug.split("/")[-1])
        tags = meme_info.get("tags", [])
        created = meme_info.get("created_at", "")
        source_url = meme_info.get("url", f"{self.BASE_URL}/{slug}")

        for idx, img_url in enumerate(meme_info.get("images", [])):
            ext = self._get_extension(img_url)
            if ext == ".gif":
                continue
            safe_title = re.sub(r'[^\w\s-]', '', title)[:50].strip().replace(' ', '_')
            meme_id = slug.split("/")[-1]
            filename = f"kym_{meme_id}_{idx}{ext}"
            save_path = self.data_dir / filename

            if save_path.exists():
                continue

            if not self._download_image(img_url, save_path):
                continue

            img = None
            try:
                img = Image.open(save_path)
                img.load()
            except Exception:
                if img is not None:
                    img.close()
                save_path.unlink(missing_ok=True)
                continue

            with img:
                passes, reason = passes_quality_check_img(img, str(save_path), MIN_RESOLUTION, MAX_FILE_SIZE_MB)
                if not passes:
                    save_path.unlink(missing_ok=True)
                    continue

                img_hash = self.dedup.compute_hash_from_img(img)
                if img_hash is None or self.dedup.is_duplicate(hash_hex=img_hash):
                    save_path.unlink(missing_ok=True)
                    continue
                self.dedup.register(hash_hex=img_hash)

                info = get_image_info_from_img(img, str(save_path))

            meme_record = {
                "id": str(uuid.uuid4()),
                "source": "knowyourmeme",
                "source_id": meme_id,
                "source_url": source_url,
                "image_path": str(save_path.relative_to(Path(__file__).resolve().parent.parent)),
                "title": title,
                "upvotes": 0,
                "comments": 0,
                "quality_score": compute_quality_score(
                    resolution=info["resolution"] if info else (0, 0),
                ),
                "image_type": classify_image_type_from_info(info),
                "tags": tags,
                "created_at": created,
                "collected_at": datetime.now().isoformat(),
                "resolution": list(info["resolution"]) if info else [0, 0],
                "format": info["format"] if info else ext.replace(".", ""),
                "file_size_kb": info["file_size_kb"] if info else 0,
            }
            enrich(meme_record, img=img)
            processed.append(meme_record)
            self.collected.append(meme_record)

        return processed

    def scrape_popular(self, limit: int = 30) -> List[Dict]:
        print(f"\n--- KYM Popular (limit={limit}) ---")
        all_memes = []

        page = 1
        while len(all_memes) < limit and page <= 10:
            url = f"{self.BASE_URL}/memes/popular?page={page}"
            links = self._get_meme_links(url)
            if not links:
                break

            for link in links:
                if len(all_memes) >= limit:
                    break

                meme_info = self._get_meme_images(link["slug"])
                if meme_info and meme_info["images"]:
                    memes = self._process_meme(link["slug"], meme_info)
                    all_memes.extend(memes)
                    print(f"  [{len(all_memes)}/{limit}] {meme_info['title'][:40]}")

                time.sleep(0.5)

            page += 1

        print(f"  Collected {len(all_memes)} memes from KYM")
        return all_memes

    def scrape_search(self, query: str, limit: int = 10) -> List[Dict]:
        print(f"\n--- KYM search: '{query}' (limit={limit}) ---")
        url = f"{self.BASE_URL}/search?q={query.replace(' ', '+')}"
        links = self._get_meme_links(url)[:limit]

        all_memes = []
        for link in links:
            meme_info = self._get_meme_images(link["slug"])
            if meme_info and meme_info["images"]:
                memes = self._process_meme(link["slug"], meme_info)
                all_memes.extend(memes)
            time.sleep(0.5)

        print(f"  Collected {len(all_memes)} memes for '{query}'")
        return all_memes

    def scrape_all(self, limit_popular=30, queries=None) -> List[Dict]:
        all_memes = []

        popular = self.scrape_popular(limit_popular)
        all_memes.extend(popular)

        if queries:
            for query in queries:
                try:
                    memes = self.scrape_search(query, limit=5)
                    all_memes.extend(memes)
                    time.sleep(1)
                except Exception as e:
                    print(f"  Error searching '{query}': {e}")

        self.dedup.save()
        return all_memes

    def get_collected(self) -> List[Dict]:
        return self.collected


if __name__ == "__main__":
    scraper = KnowYourMemeScraper()
    memes = scraper.scrape_all(
        limit_popular=10,
        queries=["drake", "distracted boyfriend"],
    )
    print(f"\nTotal collected: {len(memes)} memes")
