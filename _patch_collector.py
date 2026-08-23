"""Patch collect_to_target.py to add parallel sub collection."""
from pathlib import Path

f = Path(r"D:\claude_space\MakeMeMeme\collect_to_target.py")
code = f.read_text(encoding="utf-8")

# Add ckpt_state after new_since_ckpt
code = code.replace(
    "new_since_ckpt = 0\n\n    def save_state():",
    "ckpt_state = {'new': 0}\n\n    def save_state():\n        with slock:"
)

# Replace the entire try block with parallel version
old_try = '''    try:
        for i, sub in enumerate(subs, 1):
            if len(records) >= TARGET:
                break
            if sub_counts.get(sub, 0) >= RESUME_SKIP_THRESHOLD:
                log(f"[{i}/{len(subs)}] r/{sub} already has {sub_counts[sub]} -> skip (resume)")
                continue
            log(f"[{i}/{len(subs)}] r/{sub}  (curated={len(records)}/{TARGET})")
            before = None
            pages = 0
            empty_streak = 0
            skip_streak = 0          # pages yielding 0 new downloads (fast-forward)
            SKIP_JUMP_DAYS = 30      # when skip_streak >= 3, jump this many days
            while len(records) < TARGET:
                posts, oldest, err = search_page(session, sub, before)
                pages += 1
                if err:
                    log(f"  page {pages}: stopped ({err})"); break
                if not posts:
                    empty_streak += 1
                    if empty_streak >= 2:
                        break
                    before = (before or int(datetime.now(timezone.utc).timestamp())) - 3600
                    continue
                empty_streak = 0

                # filter cheaply
                _page_start = len(records)
                jobs = []
                for p in posts:
                    pid = p.get("id", "")
                    url = p.get("url", "") or ""
                    if not pid or pid in seen_post_ids:
                        continue
                    seen_post_ids.add(pid)
                    if p.get("over_18") or p.get("spoiler"):
                        continue
                    if not is_static(url) or url.lower().endswith(".gif"):
                        continue
                    if url in seen_urls:
                        continue
                    s = sub or p.get("subreddit", "unknown")
                    ext = Path(url.split("?")[0]).suffix.lower() or ".jpg"
                    save = CURATED_DIR / s / f"{s}_{pid}{ext}"
                    if save.exists():
                        seen_urls.add(url); continue
                    jobs.append({"post": p, "sub": s, "url": url, "save": save})

                # parallel download
                downloaded = []
                if jobs:
                    CURATED_DIR.mkdir(parents=True, exist_ok=True)
                    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
                        futs = {pool.submit(download, session, j["url"], j["save"]): j for j in jobs}
                        for fut in as_completed(futs):
                            if fut.result():
                                downloaded.append(futs[fut])

                # finalize (main thread): quality + upvote + dedup + record
                for job in downloaded:
                    p = job["post"]; s = job["sub"]; url = job["url"]; save = job["save"]
                    template = s.lower() in TEMPLATE_SUBREDDITS
                    try:
                        with Image.open(save) as img:
                            img.load()
                            w, h = img.size; fmt = img.format
                    except Exception:
                        save.unlink(missing_ok=True); continue
                    sz = save.stat().st_size / 1024
                    if w < MIN_RES[0] or h < MIN_RES[1]:
                        save.unlink(missing_ok=True); continue
                    if sz < MIN_KB:
                        save.unlink(missing_ok=True); continue
                    up = p.get("score", 0) or 0
                    if not template and up < UPVOTE_MIN:
                        save.unlink(missing_ok=True); continue
                    hsh = dedup.compute_hash(str(save))
                    if hsh is None or dedup.is_duplicate(hash_hex=hsh):
                        save.unlink(missing_ok=True); continue
                    dedup.register(hash_hex=hsh)
                    rec = {
                        "id": str(uuid.uuid4()), "source": "reddit", "source_sub": f"r/{s}",
                        "source_id": p.get("id", ""), "source_url": f"https://www.reddit.com/r/{s}/comments/{p.get('id','')}/",
                        "image_url": url, "image_path": str(save.relative_to(BASE_DIR)),
                        "title": (p.get("title") or "")[:300], "author": p.get("author", ""),
                        "upvotes": up, "comments": p.get("num_comments", 0) or 0,
                        "quality_score": round(min(up/50000,1.0)*0.5 + min((w*h)/(1920*1080),1.0)*0.5, 3),
                        "image_type": ("square" if 0.9 <= w/h <= 1.1 else ("portrait" if w/h < 0.9 else "landscape")),
                        "nsfw": False, "collected_at": datetime.now(timezone.utc).isoformat(),
                        "posted_at": datetime.fromtimestamp(p.get("created_utc",0), tz=timezone.utc).isoformat() if p.get("created_utc") else "",
                        "resolution": [w, h], "format": fmt or "", "file_size_kb": round(sz, 2),
                        "community_category": "template" if template else "general",
                    }
                    records.append(rec)
                    seen_urls.add(url)
                    new_since_ckpt += 1

                if pages % 3 == 0:
                    dt = datetime.fromtimestamp(oldest, tz=timezone.utc).strftime("%Y-%m-%d") if oldest else "?"
                    log(f"  page {pages}: curated={len(records)} (at {dt})")
                if new_since_ckpt >= CHECKPOINT:
                    save_state(); new_since_ckpt = 0
                    log(f"  [checkpoint] saved {len(records)}")

                # track pages yielding 0 new downloads -> fast-forward
                page_new = len(records) - _page_start
                if page_new == 0 and posts:
                    skip_streak += 1
                    if skip_streak >= 3 and oldest:
                        jump = oldest - (SKIP_JUMP_DAYS * 86400)
                        floor = datetime.fromisoformat(REDDIT_DATE_FLOOR).replace(tzinfo=timezone.utc).timestamp() if REDDIT_DATE_FLOOR else 0
                        if jump > floor:
                            before = jump
                            log(f"  fast-forward {SKIP_JUMP_DAYS}d (skip_streak={skip_streak})")
                            time.sleep(REQUEST_DELAY)
                            continue
                else:
                    skip_streak = 0

                if REDDIT_DATE_FLOOR:
                    floor = datetime.fromisoformat(REDDIT_DATE_FLOOR).replace(tzinfo=timezone.utc).timestamp()
                    if oldest and oldest < floor:
                        break
                before = oldest
                if not before:
                    break
                time.sleep(REQUEST_DELAY)
            save_state()
        log(f"TARGET REACHED: {len(records)} curated memes")
    except KeyboardInterrupt:
        log("Interrupted by user - saving state before exit.")
    except Exception as e:
        log(f"ERROR: {e} - saving state before exit.")
    finally:
        save_state()
        log(f"Final curated count: {len(records)} (files on disk: {curated_count()})")'''

new_try = r'''    def collect_sub(sub, idx):
        """Worker: collect one subreddit until exhausted or TARGET reached."""
        sess = requests.Session()
        sess.headers.update({"User-Agent": "MakeMeMemeDatasetCollector/1.0"})
        before = None
        pages = 0
        empty_streak = 0
        skip_streak = 0
        sub_added = 0
        while True:
            with slock:
                if len(records) >= TARGET:
                    break
            posts, oldest, err = search_page(sess, sub, before)
            pages += 1
            if err:
                log(f"  r/{sub} page {pages}: stopped ({err})"); break
            if not posts:
                empty_streak += 1
                if empty_streak >= 2:
                    break
                before = (before or int(datetime.now(timezone.utc).timestamp())) - 3600
                continue
            empty_streak = 0
            _page_start = sub_added
            jobs = []
            for p in posts:
                pid = p.get("id", "")
                url = p.get("url", "") or ""
                if not pid:
                    continue
                with slock:
                    if pid in seen_post_ids:
                        continue
                    seen_post_ids.add(pid)
                if p.get("over_18") or p.get("spoiler"):
                    continue
                if not is_static(url) or url.lower().endswith(".gif"):
                    continue
                with slock:
                    if url in seen_urls:
                        continue
                ext = Path(url.split("?")[0]).suffix.lower() or ".jpg"
                save = CURATED_DIR / sub / f"{sub}_{pid}{ext}"
                if save.exists():
                    with slock:
                        seen_urls.add(url)
                    continue
                jobs.append({"post": p, "sub": sub, "url": url, "save": save})
            downloaded = []
            if jobs:
                CURATED_DIR.mkdir(parents=True, exist_ok=True)
                with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
                    futs = {pool.submit(download, sess, j["url"], j["save"]): j for j in jobs}
                    for fut in as_completed(futs):
                        if fut.result():
                            downloaded.append(futs[fut])
            for job in downloaded:
                p = job["post"]; s = job["sub"]; url = job["url"]; save = job["save"]
                template = s.lower() in TEMPLATE_SUBREDDITS
                try:
                    with Image.open(save) as img:
                        img.load()
                        w, h = img.size; fmt = img.format
                except Exception:
                    save.unlink(missing_ok=True); continue
                sz = save.stat().st_size / 1024
                if w < MIN_RES[0] or h < MIN_RES[1]:
                    save.unlink(missing_ok=True); continue
                if sz < MIN_KB:
                    save.unlink(missing_ok=True); continue
                up = p.get("score", 0) or 0
                if not template and up < UPVOTE_MIN:
                    save.unlink(missing_ok=True); continue
                with slock:
                    hsh = dedup.compute_hash(str(save))
                    if hsh is None or dedup.is_duplicate(hash_hex=hsh):
                        save.unlink(missing_ok=True); continue
                    dedup.register(hash_hex=hsh)
                    rec = {
                        "id": str(uuid.uuid4()), "source": "reddit", "source_sub": f"r/{s}",
                        "source_id": p.get("id", ""), "source_url": f"https://www.reddit.com/r/{s}/comments/{p.get('id','')}/",
                        "image_url": url, "image_path": str(save.relative_to(BASE_DIR)),
                        "title": (p.get("title") or "")[:300], "author": p.get("author", ""),
                        "upvotes": up, "comments": p.get("num_comments", 0) or 0,
                        "quality_score": round(min(up/50000,1.0)*0.5 + min((w*h)/(1920*1080),1.0)*0.5, 3),
                        "image_type": ("square" if 0.9 <= w/h <= 1.1 else ("portrait" if w/h < 0.9 else "landscape")),
                        "nsfw": False, "collected_at": datetime.now(timezone.utc).isoformat(),
                        "posted_at": datetime.fromtimestamp(p.get("created_utc",0), tz=timezone.utc).isoformat() if p.get("created_utc") else "",
                        "resolution": [w, h], "format": fmt or "", "file_size_kb": round(sz, 2),
                        "community_category": "template" if template else "general",
                    }
                    records.append(rec)
                    seen_urls.add(url)
                    sub_added += 1
                    ckpt_state["new"] += 1
            if pages % 5 == 0:
                dt = datetime.fromtimestamp(oldest, tz=timezone.utc).strftime("%Y-%m-%d") if oldest else "?"
                with slock:
                    tc = len(records)
                log(f"  r/{sub} p{pages}: +{sub_added} (total={tc}, at {dt})")
            with slock:
                if ckpt_state["new"] >= CHECKPOINT:
                    ckpt_state["new"] = 0
                    save_state()
                    log(f"  [checkpoint] total={len(records)}")
            page_new = sub_added - _page_start
            if page_new == 0 and posts:
                skip_streak += 1
                if skip_streak >= 3 and oldest:
                    jump = oldest - (SKIP_JUMP_DAYS * 86400)
                    floor = datetime.fromisoformat(REDDIT_DATE_FLOOR).replace(tzinfo=timezone.utc).timestamp() if REDDIT_DATE_FLOOR else 0
                    if jump > floor:
                        before = jump
                        log(f"  r/{sub} fast-forward {SKIP_JUMP_DAYS}d")
                        time.sleep(REQUEST_DELAY)
                        continue
            else:
                skip_streak = 0
            if REDDIT_DATE_FLOOR:
                floor = datetime.fromisoformat(REDDIT_DATE_FLOOR).replace(tzinfo=timezone.utc).timestamp()
                if oldest and oldest < floor:
                    break
            before = oldest
            if not before:
                break
            time.sleep(REQUEST_DELAY)
        with slock:
            save_state()
        log(f"  r/{sub} done: +{sub_added}")

    try:
        log(f"launching {PARALLEL} parallel collectors across {len(subs)} subs")
        with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
            futures = {pool.submit(collect_sub, sub, i): sub for i, sub in enumerate(subs)}
            for fut in as_completed(futures):
                sub = futures[fut]
                try:
                    fut.result()
                except Exception as e:
                    log(f"  r/{sub} crashed: {e}")
                with slock:
                    if len(records) >= TARGET:
                        break
        log(f"TARGET REACHED: {len(records)} curated memes")
    except KeyboardInterrupt:
        log("Interrupted by user - saving state before exit.")
    except Exception as e:
        log(f"ERROR: {e} - saving state before exit.")
    finally:
        save_state()
        log(f"Final curated count: {len(records)} (files on disk: {curated_count()})")'''

if old_try in code:
    code = code.replace(old_try, new_try)
    f.write_text(code, encoding="utf-8")
    print("OK: patched collect_to_target.py")
else:
    print("ERROR: old_try block not found; need manual patch")
    # write just the collect_sub function and parallel dispatch as a separate file
    Path(r"D:\claude_space\MakeMeMeme\_patch_note.txt").write_text("patch not applied")
