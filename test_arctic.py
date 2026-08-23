import requests, time
s=requests.Session()
s.headers.update({"User-Agent":"MakeMeMemeDatasetCollector/1.0"})
url='https://arctic-shift.photon-reddit.com/api/posts/search'
for limit in ['5','auto']:
    params={'subreddit':'BoneHurtingJuice','fields':'id,title,score,num_comments,url,created_utc,author,over_18,post_hint,link_flair_text,spoiler,selftext,subreddit','sort':'desc','limit':limit}
    print(f'testing limit={limit}')
    t0=time.time()
    try:
        r=s.get(url, params=params, timeout=30)
        print(f'  status {r.status_code} time {time.time()-t0:.1f} len {len(r.text)}')
        print(r.text[:300])
    except Exception as e:
        print(f'  err {e} time {time.time()-t0:.1f}')
    time.sleep(1)

for sub in ['wholesomememes','BoneHurtingJuice']:
    params={'subreddit':sub,'fields':'id,title,score','sort':'desc','limit':'5'}
    print(f'sub {sub} limit 5')
    t0=time.time()
    try:
        r=s.get(url, params=params, timeout=15)
        print(f'  ok {r.status_code} {time.time()-t0:.1f}')
    except Exception as e:
        print(f'  err {e}')
