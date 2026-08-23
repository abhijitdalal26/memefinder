import requests
import uuid
import time
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import (
    IMGFLIP_DATA_DIR,
    MIN_RESOLUTION,
    MAX_FILE_SIZE_MB,
)
from utils.dedup import Deduplicator
from utils.quality import passes_quality_check_img, compute_quality_score, classify_image_type_from_info, get_image_info_from_img
from utils.enrichment import enrich

from PIL import Image

DOWNLOAD_WORKERS = 8


class ImgflipScraper:
    API_URL = "https://api.imgflip.com/get_memes"

    def __init__(self):
        self.dedup = Deduplicator()
        self.collected: List[Dict] = []
        self.data_dir = IMGFLIP_DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })

    def _fetch_templates(self) -> List[Dict]:
        try:
            resp = self.session.get(self.API_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if data.get("success"):
                return data.get("data", {}).get("memes", [])
        except Exception as e:
            print(f"  Imgflip API error: {e}")
        return []

    def _download_image(self, url: str, save_path: Path) -> bool:
        try:
            resp = self.session.get(url, timeout=30, stream=True)
            resp.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            file_size = save_path.stat().st_size
            if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
                save_path.unlink(missing_ok=True)
                return False
            if file_size < 1024:
                save_path.unlink(missing_ok=True)
                return False
            return True
        except Exception:
            save_path.unlink(missing_ok=True)
            return False

    def _finalize_template(self, template: dict, save_path: Path) -> Optional[Dict]:
        """Main thread: single decode for quality + dedup + enrichment."""
        template_id = template.get("id", "")
        name = template.get("name", "untitled")
        width = template.get("width", 0)
        height = template.get("height", 0)
        box_count = template.get("box_count", 0)

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
            passes, reason = passes_quality_check_img(img, str(save_path), MIN_RESOLUTION, MAX_FILE_SIZE_MB)
            if not passes:
                save_path.unlink(missing_ok=True)
                return None

            img_hash = self.dedup.compute_hash_from_img(img)
            if img_hash is None or self.dedup.is_duplicate(hash_hex=img_hash):
                save_path.unlink(missing_ok=True)
                return None
            self.dedup.register(hash_hex=img_hash)

            info = get_image_info_from_img(img, str(save_path))

        meme_record = {
            "id": str(uuid.uuid4()),
            "source": "imgflip",
            "source_id": template_id,
            "source_url": f"https://imgflip.com/memegenerator/{template_id}",
            "image_path": str(save_path.relative_to(Path(__file__).resolve().parent.parent)),
            "title": name,
            "upvotes": 0,
            "comments": 0,
            "quality_score": compute_quality_score(
                resolution=(width, height) if width and height else (0, 0),
            ),
            "image_type": classify_image_type_from_info(info),
            "tags": ["template", "blank"],
            "created_at": "",
            "collected_at": datetime.now().isoformat(),
            "resolution": [width, height],
            "format": "jpg",
            "file_size_kb": info["file_size_kb"] if info else 0,
            "box_count": box_count,
        }
        enrich(meme_record, img=img)
        return meme_record

    def scrape_all(self) -> List[Dict]:
        print("\n--- Imgflip Templates ---")
        templates = self._fetch_templates()
        print(f"  Fetched {len(templates)} templates from API")

        jobs = []
        for template in templates:
            name = template.get("name", "untitled")
            safe_name = name.replace(" ", "_")[:50]
            filename = f"imgflip_{template.get('id', '')}_{safe_name}.jpg"
            save_path = self.data_dir / filename
            if not template.get("url") or save_path.exists():
                continue
            jobs.append((template, save_path))

        results = []
        if jobs:
            with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
                futures = {pool.submit(self._download_image, t["url"], p): (t, p) for t, p in jobs}
                downloaded = []
                for fut in as_completed(futures):
                    if fut.result():
                        downloaded.append(futures[fut])
            for template, save_path in downloaded:
                record = self._finalize_template(template, save_path)
                if record:
                    results.append(record)
                    self.collected.append(record)

        self.dedup.save()
        print(f"  Collected {len(results)} new templates ({len(templates) - len(jobs)} already present)")
        return results

    def get_collected(self) -> List[Dict]:
        return self.collected


if __name__ == "__main__":
    scraper = ImgflipScraper()
    memes = scraper.scrape_all()
    print(f"\nTotal collected: {len(memes)} templates")
