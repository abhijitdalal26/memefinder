import json
from collections import Counter
from pathlib import Path

BASE = Path(r"D:\claude_space\MakeMeMeme")
m = json.load(open(BASE / "config" / "postmeta.json", encoding="utf-8"))
print("records:", len(m))

buckets = Counter()
for v in m.values():
    u = v.get("upvotes", 0) or 0
    if u < 100:
        buckets["<100"] += 1
    elif u < 250:
        buckets["100-249"] += 1
    elif u < 500:
        buckets["250-499"] += 1
    elif u < 1000:
        buckets["500-999"] += 1
    elif u < 2000:
        buckets["1000-1999"] += 1
    elif u < 5000:
        buckets["2000-4999"] += 1
    else:
        buckets["5000+"] += 1

for k in ["<100", "100-249", "250-499", "500-999", "1000-1999", "2000-4999", "5000+"]:
    print(f"  upvotes {k}: {buckets[k]} ({100*buckets[k]/len(m):.0f}%)")

ups = sorted(v.get("upvotes", 0) or 0 for v in m.values())
n = len(ups)
print("median upvotes:", ups[n // 2])
median = ups[n // 2]
print("p90 upvotes:", ups[int(n * 0.9)])
print("DONE")
