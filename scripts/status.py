"""Quick collection status. Run anytime: python scripts/status.py"""
import json
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent.parent
META = BASE / "curated_metadata.json"

TARGET = 50000

def main():
    try:
        records = json.load(open(META, encoding="utf-8"))
    except Exception:
        records = []

    n = len(records)
    subs = {}
    for r in records:
        s = (r.get("source_sub") or "?").replace("r/", "")
        subs[s] = subs.get(s, 0) + 1

    files = sum(1 for p in (BASE / "data" / "curated").rglob("*") if p.is_file() and p.suffix.lower() != ".part")
    parts = sum(1 for p in (BASE / "data" / "curated").rglob("*.part"))
    size_gb = sum(p.stat().st_size for p in (BASE / "data" / "curated").rglob("*") if p.is_file()) / 1e9

    print(f"=== MakeMeMeme Status @ {datetime.now().strftime('%H:%M:%S')} ===")
    print(f"Curated: {n:,} / {TARGET:,}  ({n/TARGET*100:.1f}%)   remaining {TARGET-n:,}")
    print(f"Files on disk: {files:,} (+{parts} .part in-flight)")
    print(f"Disk: {size_gb:.2f} GB")
    print("Top subs:")
    for s, c in sorted(subs.items(), key=lambda x: -x[1])[:12]:
        print(f"  r/{s:<28} {c:>6}")
    zero_subs = [s for s in [
        "wholesomememes","PrequelMemes","Animemes","MinecraftMemes","okbuddyretard",
        "BoneHurtingJuice","comedyheaven","terriblefacebookmemes","starterpacks","196",
        "gamingmemes","animememes","dankchristianmemes","physicsmemes","mathmemes",
        "chemistrymemes","lotrmemes","MemeTemplatesOfficial","BlankTemplatesForMemes",
        "memesoundless","reactionpictures"] if s not in subs]
    print(f"Still zero: {len(zero_subs)} e.g. {zero_subs[:8]}")

if __name__ == "__main__":
    main()
