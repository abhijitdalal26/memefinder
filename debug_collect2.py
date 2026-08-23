import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_to_target import search_page
import requests, time

sess = requests.Session()
sess.headers.update({"User-Agent": "MakeMeMemeDatasetCollector/1.0"})
for sub in ["wholesomememes"]:
    print(f"testing {sub}")
    t0=time.time()
    posts, oldest, err = search_page(sess, sub, None)
    print(f"done {time.time()-t0:.1f} posts {len(posts) if posts else 0} err {err} oldest {oldest}")

# Now test with full collect_sub logic including dedup and lock
from utils.dedup import Deduplicator
from threading import Lock
import json, uuid
from config.settings import BASE_DIR, DATA_DIR
from datetime import datetime, timezone

dedup = Deduplicator()
print(f"dedup loaded {dedup.get_stats()}")
slock=Lock()
records=[]
seen_post_ids=set()
seen_urls=set()
# load existing
import json as js
recs=js.load(open(BASE_DIR/"curated_metadata.json", encoding="utf-8"))
for r in recs:
    seen_post_ids.add(r["source_id"])
    seen_urls.add(r["image_url"])
print(f"seen {len(seen_post_ids)} posts")
# try one collect_sub iteration manually
sub="wholesomememes"
before=None
sess2=requests.Session()
sess2.headers.update({"User-Agent": "MakeMeMemeDatasetCollector/1.0"})
print("calling search_page again with sess2")
posts, oldest, err = search_page(sess2, sub, before)
print(f"posts {len(posts)} err {err}")
# filter
from collect_to_target import is_static, CURATED_DIR, TEMPLATE_SUBREDDITS, MIN_RES, MIN_KB, UPVOTE_MIN, STATIC_EXTS
jobs=[]
for p in posts[:10]:
    pid=p.get("id","")
    url=p.get("url","") or ""
    print(f"  pid {pid} url {url[:60]} score {p.get('score')} is_static {is_static(url)} over18 {p.get('over_18')}")
    if not pid or pid in seen_post_ids:
        print("    skip seen")
        continue
    if p.get("over_18") or p.get("spoiler"):
        print("    skip nsfw")
        continue
    if not is_static(url):
        print("    skip not static")
        continue
    if url in seen_urls:
        print("    skip seen url")
        continue
    print("    would be job")
