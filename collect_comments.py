#!/usr/bin/env python3
"""
Standalone runner for reddit comment image collection.
Isolated from main.py - uses separate lock/data dir/seen files.

Usage:
  py collect_comments.py --subs memes --limit 50 --score-floor 50
  py collect_comments.py --subs memes,dankmemes --limit 500 --score-floor 50 --date-floor 2024-01-01
  py collect_comments.py --all --limit 300 --score-floor 50
"""
import os
import sys
import argparse
import json
from pathlib import Path
from datetime import datetime

LOCK_FILE = Path(__file__).resolve().parent / "collection_comments.lock"
DATA_DIR = Path(__file__).resolve().parent / "data" / "reddit_comments"
METADATA_FILE = DATA_DIR / "_metadata.json"

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
                    print(f"ERROR: another comment collection is active (pid {pid}). Delete {LOCK_FILE} if wrong.")
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

def load_existing_metadata():
    if METADATA_FILE.exists():
        try:
            return json.load(open(METADATA_FILE, encoding="utf-8"))
        except Exception:
            return []
    return []

def save_metadata(records):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

def main():
    parser = argparse.ArgumentParser(description="MakeMeMeme - Reddit Comment Image Collector (isolated)")
    parser.add_argument("--subs", type=str, default="", help="Comma-separated subreddit list (default: memes)")
    parser.add_argument("--all", action="store_true", help="Use all subreddits from settings.REDDIT_SUBREDDITS")
    parser.add_argument("--limit", type=int, default=100, help="Max posts to scan per subreddit (default 100)")
    parser.add_argument("--score-floor", type=int, default=50, help="Min comment score to keep (default 50)")
    parser.add_argument("--max-per-post", type=int, default=5, help="Max images per post (default 5)")
    parser.add_argument("--date-floor", type=str, default="2024-01-01", help="Don't go older than this (ISO date)")
    args = parser.parse_args()

    from config.settings import REDDIT_SUBREDDITS
    from scrapers.reddit_comment_scraper import RedditCommentScraper

    if args.all:
        subs = REDDIT_SUBREDDITS
    elif args.subs:
        subs = [s.strip() for s in args.subs.split(",") if s.strip()]
    else:
        subs = ["memes"]

    print(f"\nMakeMeMeme Comment Collector Started at {datetime.now().isoformat()}")
    print(f"Subs: {subs[:5]}{'...' if len(subs)>5 else ''} ({len(subs)} total)")
    print(f"Limit: {args.limit}/sub | score floor: {args.score_floor} | max/post: {args.max_per_post} | floor: {args.date_floor}")
    print(f"Output: {DATA_DIR} | Lock: {LOCK_FILE}")
    print("="*60)

    with SingleRunLock():
        scraper = RedditCommentScraper(score_floor=args.score_floor, max_comments_per_post=args.max_per_post)
        # preload existing metadata to avoid duplicate source_id
        existing = load_existing_metadata()
        existing_ids = {m.get("source_id") for m in existing}
        print(f"Existing comment images: {len(existing)} (will dedup against)")

        # Inject existing ids into scraper's dedup via seen sets? Dedup handles via hash, but we also skip source_id
        # We'll filter after scrape_all by checking existing_ids
        scraped = scraper.scrape_all(subs, max_posts_per_sub=args.limit, date_floor=args.date_floor)
        # Dedup against existing metadata by source_id
        new_records = [r for r in scraped if r.get("source_id") not in existing_ids]
        all_records = existing + new_records
        # Also dedup within new_records by source_id (scraper already handles comment id)
        save_metadata(all_records)
        # Also save per-sub files like main.py
        for sub in subs:
            sub_records = [r for r in all_records if r.get("source_sub")==f"r/{sub}"]
            if sub_records:
                out = DATA_DIR / f"_metadata_{sub}.json"
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(sub_records, f, indent=2, ensure_ascii=False)
        print(f"\nDone: {len(new_records)} new comment images (total {len(all_records)})")
        print(f"Stats: {scraper.stats}")
        print(f"Metadata: {METADATA_FILE}")
        print(f"Finished at {datetime.now().isoformat()}")

if __name__ == "__main__":
    main()
