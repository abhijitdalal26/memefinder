import json, pathlib, collections
base=pathlib.Path(r"D:\claude_space\MakeMeMeme")
cm=json.load(open(base/'curated_metadata.json', encoding='utf-8'))
c=collections.Counter(r.get('source_sub') or '?' for r in cm)
print('total',len(cm))
for k,v in c.most_common(20):
    print(f'{k}: {v} ({v/len(cm)*100:.1f}%)')
cat=collections.Counter(r.get('community_category') or '?' for r in cm)
print('--- category ---')
for k,v in cat.most_common():
    print(f'{k}: {v}')
qc=collections.Counter()
for r in cm:
    w,h=r.get('resolution',[0,0])
    if w<400 or h<400: qc['small_res']+=1
    if r.get('file_size_kb',0)<20: qc['small_file']+=1
    if r.get('quality_score',0)<0.12 and r.get('community_category')!='template': qc['low_score']+=1
print('--- quality failures if re-filtered ---', dict(qc))
files=list((base/'data'/'curated').rglob('*'))
files=[p for p in files if p.is_file() and p.suffix.lower()!='.part']
print('files vs meta', len(files), len(cm))
s=sum(p.stat().st_size for p in files)
print(f'size GB {s/1e9:.2f} size MB {s/1024/1024:.1f}')
# hash
import json as js
seen=json.load(open(base/'config'/'seen_hashes.json'))
print('hashes', len(seen.get('hashes',[])))
seen_posts=json.load(open(base/'config'/'seen_reddit_posts.json'))
print('seen_posts', len(seen_posts))
