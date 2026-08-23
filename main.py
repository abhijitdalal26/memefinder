import json
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict

from config.settings import (
    METADATA_FILE,
    DATA_DIR,
    REDDIT_SUBREDDITS,
    REDDIT_MAX_PER_SUB,
    REDDIT_DATE_FLOOR,
)
from scrapers.reddit_arctic_scraper import RedditArcticScraper
from scrapers.imgflip_scraper import ImgflipScraper
from scrapers.knowyourmeme_scraper import KnowYourMemeScraper

LOCK_FILE = Path(__file__).resolve().parent / "collection.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class SingleRunLock:
    def __enter__(self):
        if LOCK_FILE.exists():
            try:
                pid = int(LOCK_FILE.read_text().strip())
                if _pid_alive(pid):
                    print(f"ERROR: another collection run is already active (pid {pid}).")
                    print("Delete collection.lock if that is wrong.")
                    sys.exit(1)
            except (ValueError, OSError):
                pass
        LOCK_FILE.write_text(str(os.getpid()))
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass
        return False


class MemeOrchestrator:
    def __init__(self):
        self.all_memes: List[Dict] = []
        self.metadata_file = METADATA_FILE
        self._load_metadata()

    def _load_metadata(self):
        if self.metadata_file.exists():
            with open(self.metadata_file, "r", encoding="utf-8") as f:
                self.all_memes = json.load(f)
        else:
            self.all_memes = []

    def _save_metadata(self):
        with open(self.metadata_file, "w", encoding="utf-8") as f:
            json.dump(self.all_memes, f, indent=2, ensure_ascii=False)

    def _get_existing_ids(self) -> set:
        return {m["source_id"] for m in self.all_memes if "source_id" in m}

    def _merge_results(self, new_memes: List[Dict]) -> int:
        existing_ids = self._get_existing_ids()
        added = 0
        for meme in new_memes:
            if meme.get("source_id") not in existing_ids:
                self.all_memes.append(meme)
                existing_ids.add(meme.get("source_id"))
                added += 1
        return added

    def _write_source_metadata(self, source: str):
        """Per-source metadata file so each source's data is independently browsable."""
        src_meta = DATA_DIR / source / "_metadata.json"
        src_meta.parent.mkdir(parents=True, exist_ok=True)
        records = [m for m in self.all_memes if m.get("source") == source]
        with open(src_meta, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)

    def run_reddit(self, subreddits=None, max_per_sub=None, date_floor=None):
        subs = subreddits or REDDIT_SUBREDDITS
        max_per_sub = max_per_sub if max_per_sub is not None else REDDIT_MAX_PER_SUB
        date_floor = date_floor or REDDIT_DATE_FLOOR

        print("\n" + "=" * 60)
        print(f"REDDIT SCRAPER (Arctic Shift archive) - {len(subs)} subreddits")
        print(f"cap: {max_per_sub}/sub | floor: {date_floor}")
        print("=" * 60)
        scraper = RedditArcticScraper()
        memes = scraper.scrape_all(subs, max_per_sub=max_per_sub, date_floor=date_floor)
        added = self._merge_results(memes)
        self._save_metadata()
        self._write_source_metadata("reddit")
        print(f"\nReddit: {added} new images (total in catalog: {len(self.all_memes)})")
        return added

    def run_imgflip(self):
        print("\n" + "=" * 60)
        print("IMGFLIP SCRAPER (blank templates - separate category)")
        print("=" * 60)
        scraper = ImgflipScraper()
        memes = scraper.scrape_all()
        added = self._merge_results(memes)
        self._save_metadata()
        self._write_source_metadata("imgflip")
        print(f"\nImgflip: {added} new templates (total in catalog: {len(self.all_memes)})")
        return added

    def run_knowyourmeme(self, limit_popular=100, queries=None):
        print("\n" + "=" * 60)
        print("KNOW YOUR MEME SCRAPER")
        print("=" * 60)
        scraper = KnowYourMemeScraper()
        memes = scraper.scrape_all(limit_popular, queries)
        added = self._merge_results(memes)
        self._save_metadata()
        self._write_source_metadata("knowyourmeme")
        print(f"\nKnowYourMeme: {added} new memes (total in catalog: {len(self.all_memes)})")
        return added

    def run_all(self, reddit_limit=None, kym_limit=100):
        total_added = 0
        total_added += self.run_reddit(max_per_sub=reddit_limit)
        total_added += self.run_imgflip()
        kym_queries = [
            "drake", "distracted boyfriend", "change my mind",
            "expanding brain", "woman yelling at cat", "two buttons",
            "is this a pigeon", "galaxy brain", "epic handshake",
            "they're the same picture", "bernard looking", "hide the pain harold",
        ]
        total_added += self.run_knowyourmeme(limit_popular=kym_limit, queries=kym_queries)
        return total_added

    def get_stats(self) -> Dict:
        stats = {
            "total_memes": len(self.all_memes),
            "by_source": {},
            "by_subreddit": {},
            "by_community_category": {},
            "by_humor_signal": {},
            "by_platform_fit": {},
            "avg_quality_score": 0,
            "total_size_mb": 0,
        }
        for meme in self.all_memes:
            source = meme.get("source", "unknown")
            stats["by_source"][source] = stats["by_source"].get(source, 0) + 1
            if source == "reddit":
                sub = meme.get("source_sub", "unknown")
                stats["by_subreddit"][sub] = stats["by_subreddit"].get(sub, 0) + 1
                cat = meme.get("community_category", "unknown")
                stats["by_community_category"][cat] = stats["by_community_category"].get(cat, 0) + 1
            humor = meme.get("humor_signal", "none")
            stats["by_humor_signal"][humor] = stats["by_humor_signal"].get(humor, 0) + 1
            fit = meme.get("platform_fit") or []
            for platform in fit[:2]:
                stats["by_platform_fit"][platform] = stats["by_platform_fit"].get(platform, 0) + 1

        existing = [m for m in self.all_memes if Path(m.get("image_path", "")).exists()]
        if existing:
            scores = [m.get("quality_score", 0) for m in existing]
            stats["avg_quality_score"] = round(sum(scores) / len(scores), 3)
            for meme in existing:
                img_path = Path(meme.get("image_path", ""))
                stats["total_size_mb"] += img_path.stat().st_size / (1024 * 1024)
            stats["total_size_mb"] = round(stats["total_size_mb"], 2)
        stats["missing_files"] = len(self.all_memes) - len(existing)

        return stats

    def print_stats(self):
        stats = self.get_stats()
        print("\n" + "=" * 60)
        print("COLLECTION STATISTICS")
        print("=" * 60)
        print(f"Total memes: {stats['total_memes']} ({stats['missing_files']} files missing)")
        print(f"Average quality score: {stats['avg_quality_score']}")
        print(f"Total size: {stats['total_size_mb']} MB")
        print("\nBy source:")
        for source, count in sorted(stats["by_source"].items(), key=lambda x: -x[1]):
            print(f"  {source}: {count}")
        if stats["by_subreddit"]:
            print("\nReddit by subreddit (top 20):")
            items = sorted(stats["by_subreddit"].items(), key=lambda x: -x[1])[:20]
            for sub, count in items:
                print(f"  {sub}: {count}")
        if stats["by_community_category"]:
            print("\nBy community category:")
            for cat, count in sorted(stats["by_community_category"].items(), key=lambda x: -x[1]):
                print(f"  {cat}: {count}")
        if stats["by_humor_signal"]:
            print("\nBy humor signal (top 10):")
            items = sorted(stats["by_humor_signal"].items(), key=lambda x: -x[1])[:10]
            for sig, count in items:
                print(f"  {sig}: {count}")
        if stats["by_platform_fit"]:
            print("\nBy platform fit (top 10):")
            items = sorted(stats["by_platform_fit"].items(), key=lambda x: -x[1])[:10]
            for plat, count in items:
                print(f"  {plat}: {count}")
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="MakeMeMeme - Meme Collection Orchestrator")
    parser.add_argument(
        "--source",
        choices=["all", "reddit", "imgflip", "knowyourmeme"],
        default="all",
        help="Which source to scrape (default: all)",
    )
    parser.add_argument("--reddit-limit", type=int, default=None, help="Max images per subreddit (default from settings)")
    parser.add_argument("--kym-limit", type=int, default=100, help="KYM popular memes limit")
    parser.add_argument("--subs", type=str, default="", help="Comma-separated subreddit list override")
    parser.add_argument("--stats", action="store_true", help="Show collection stats only")

    args = parser.parse_args()
    orchestrator = MemeOrchestrator()

    if args.stats:
        orchestrator.print_stats()
        return

    with SingleRunLock():
        print(f"\nMakeMeMeme Collection Started at {datetime.now().isoformat()}")
        print(f"Source: {args.source}")

        if args.source == "all":
            orchestrator.run_all(reddit_limit=args.reddit_limit, kym_limit=args.kym_limit)
        elif args.source == "reddit":
            subs = args.subs.split(",") if args.subs else None
            orchestrator.run_reddit(subreddits=subs, max_per_sub=args.reddit_limit)
        elif args.source == "imgflip":
            orchestrator.run_imgflip()
        elif args.source == "knowyourmeme":
            orchestrator.run_knowyourmeme(limit_popular=args.kym_limit)

        print(f"\nCollection finished at {datetime.now().isoformat()}")
        orchestrator.print_stats()


if __name__ == "__main__":
    main()
