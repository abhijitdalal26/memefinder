import json, pathlib, re, collections
base=pathlib.Path(r"D:\claude_space\MakeMeMeme")
cm=json.load(open(base / 'curated_metadata.json', encoding='utf-8'))
print('meta',len(cm))
meta_ids={r.get('source_id') for r in cm if r.get('source_id')}
print('unique',len(meta_ids))
files=[p for p in (base/'data'/'curated').rglob('*') if p.is_file() and p.suffix.lower()!='.part']
print('files',len(files))
pat=re.compile(r'^(?P<sub>.+)_(?P<postid>[A-Za-z0-9]{4,12})\.(?:jpg|png|jpeg|webp)$', re.I)
orphan=[]
bysub=collections.Counter()
miss=0
for f in files:
    m=pat.match(f.name)
    if not m:
        miss+=1
        continue
    postid=m.group('postid')
    sub=m.group('sub')
    if postid not in meta_ids:
        orphan.append(f)
        bysub[sub]+=1
print(f'orphan={len(orphan)} miss_pat={miss}')
print(bysub.most_common(20))
print([str(x.name) for x in orphan[:10]])
# also check reverse: metadata without file
missing_files=[]
for r in cm:
    p=base / r.get('image_path','')
    if not p.exists():
        missing_files.append(r)
print(f'metadata without file={len(missing_files)}')
if missing_files:
    print(missing_files[:3])
