import json
from pathlib import Path
M = Path(r"D:\claude_space\MakeMeMeme\data\curated_metadata.json")
recs = json.loads(M.read_text())
ids = [r.get("source_id") for r in recs]
print("records:", len(recs))
print("non-null source_id:", sum(1 for i in ids if i))
print("unique source_id:", len(set(i for i in ids if i)))
print("with upvotes:", sum(1 for r in recs if r.get("upvotes") is not None))
print("with image_path:", sum(1 for r in recs if r.get("image_path")))
import collections
subs = collections.Counter((r.get("source_sub") or "?") for r in recs)
print("top subs:", subs.most_common(8))
