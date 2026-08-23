import requests, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config.settings import REDDIT_SUBREDDITS

ARCTIC_BASE = "https://arctic-shift.photon-reddit.com/api/posts/search"
FIELDS = "id,title,score,num_comments,url,created_utc,author,over_18,post_hint,link_flair_text,spoiler,selftext,subreddit"

def search_page(session, sub, before):
    params = {"subreddit": sub, "fields": FIELDS, "sort": "desc", "limit": "auto"}
    if before:
        params["before"] = int(before)
    print(f"search_page sub={sub} before={before} params={params}")
    for attempt in range(3):
        try:
            print(f"  attempt {attempt+1} get...")
            r = session.get(ARCTIC_BASE, params=params, timeout=30)
            print(f"  status {r.status_code} len {len(r.text[:200])}")
            if r.status_code == 429:
                wait = int(r.headers.get("X-RateLimit-Reset", 30))
                print(f"  rate limited wait {wait}")
                time.sleep(wait)
                continue
            if r.status_code == 422 or "Timeout" in r.text[:200]:
                wait = 15 * (attempt + 1)
                print(f"  timeout backoff {wait}")
                time.sleep(wait)
                continue
            r.raise_for_status()
            j = r.json()
            err = j.get("error") or j.get("detail")
            if err:
                print(f"  err field {err}")
                return [], None, str(err)
            posts = j.get("data") or []
            oldest = min((p["created_utc"] for p in posts), default=None)
            print(f"  got {len(posts)} posts oldest {oldest}")
            return posts, oldest, None
        except Exception as e:
            print(f"  exception {e}")
            import traceback; traceback.print_exc()
            time.sleep(2)
    return [], None, "max_retries"

sess = requests.Session()
sess.headers.update({"User-Agent": "MakeMeMemeDatasetCollector/1.0"})
for sub in ["wholesomememes","BoneHurtingJuice"]:
    print(f"\n=== {sub} ===")
    t0=time.time()
    posts, oldest, err = search_page(sess, sub, None)
    print(f"done {time.time()-t0:.1f}s err={err} posts={len(posts) if posts else 0}")
