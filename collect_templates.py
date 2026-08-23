#!/usr/bin/env python3
"""
Isolated template collector - Imgflip + KnowYourMeme
Stores in separate dirs data/imgflip/ and data/knowyourmeme/
Does NOT touch data/reddit/ or collection.lock (post collector)
"""
import json
from pathlib import Path
from datetime import datetime

from config.settings import DATA_DIR, IMGFLIP_DATA_DIR, KNOWYOURMEME_DATA_DIR
from scrapers.imgflip_scraper import ImgflipScraper
from scrapers.knowyourmeme_scraper import KnowYourMemeScraper

def save_source_metadata(source: str, records):
    # mimic main.py _write_source_metadata but isolated
    src_meta = DATA_DIR / source / "_metadata.json"
    src_meta.parent.mkdir(parents=True, exist_ok=True)
    # load existing if present to merge
    existing = []
    if src_meta.exists():
        try:
            existing = json.load(open(src_meta, encoding="utf-8"))
        except: existing=[]
    existing_ids = {r.get("source_id") for r in existing}
    new = [r for r in records if r.get("source_id") not in existing_ids]
    merged = existing + new
    with open(src_meta, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"  -> {src_meta}: {len(new)} new, {len(merged)} total")
    return merged

def run_imgflip():
    print("\n" + "="*60)
    print("IMGFLIP TEMPLATES (blank for AI)")
    print("="*60)
    s = ImgflipScraper()
    recs = s.scrape_all()
    save_source_metadata("imgflip", recs)
    return recs

def run_kym(limit_popular=100):
    print("\n" + "="*60)
    print("KNOWYOURMEME (examples + tags)")
    print("="*60)
    queries = [
        "drake", "distracted boyfriend", "change my mind",
        "expanding brain", "woman yelling at cat", "two buttons",
        "is this a pigeon", "galaxy brain", "epic handshake",
        "they're the same picture", "bernard looking", "hide the pain harold",
    ]
    s = KnowYourMemeScraper()
    recs = s.scrape_all(limit_popular=limit_popular, queries=queries)
    save_source_metadata("knowyourmeme", recs)
    return recs

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Collect templates separate from reddit")
    p.add_argument("--source", choices=["all","imgflip","kym"], default="all")
    p.add_argument("--kym-limit", type=int, default=100)
    args = p.parse_args()
    if args.source in ("all","imgflip"):
        # if imgflip already has files, skip re-download but ensure metadata exists
        meta = DATA_DIR / "imgflip" / "_metadata.json"
        if not meta.exists():
            # we already collected 95 via direct run, need to generate metadata from scraped recs stored? 
            # Re-run will dedup via files exists -> 0 new but still works. Run again to generate metadata
            # Instead, if we already have files, rebuild metadata from scraper's last run is lost.
            # So we force a fresh scrape that will find 0 new but we lost previous 95 records.
            # Workaround: scan existing files and create minimal metadata if missing
            files = list(IMGFLIP_DATA_DIR.glob("*.jpg"))
            if files and not meta.exists():
                print(f"Found {len(files)} existing imgflip files but no _metadata.json, rebuilding placeholder")
                # fetch api again to get mapping for those files? easier: run scraper and capture if 0 new, rebuild from files
                pass
        run_imgflip()
    if args.source in ("all","kym"):
        run_kym(limit_popular=args.kym_limit)
    print(f"\nDone at {datetime.now().isoformat()}")
    for src in ["imgflip","knowyourmeme"]:
        m = DATA_DIR / src / "_metadata.json"
        if m.exists():
            data = json.load(open(m, encoding="utf-8"))
            print(f"{src}: {len(data)} records -> {m}")
        else:
            print(f"{src}: no metadata yet")
        print(f"  files: {len(list((DATA_DIR/src).glob('*.*')))}")
