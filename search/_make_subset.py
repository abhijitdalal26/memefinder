import json
import collections
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = os.path.join(ROOT, "curated_metadata.json")
d = json.load(open(src, encoding="utf-8"))
by = collections.defaultdict(list)
for m in d:
    by[m.get("source_sub")].append(m)
out = []
for sub, ms in by.items():
    out.extend(ms[:6])
out = out[:120]
dst = os.path.join(ROOT, "search", "test_catalog.json")
json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("wrote", len(out), "memes to", dst)
