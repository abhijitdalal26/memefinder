# MemeFinder — Full Pipeline Report (2026-08-23 verified)

## 1. Overview
Text-to-meme **retrieval** (not generation yet). You type “i don’t want to work today”, you get the 6 most relevant memes from a curated Reddit corpus. All steps run in Colab T4 GPU, images+metadata live on Drive, code is `pipeline/` + `search/` + `config/`. Verified end-to-end on 12 images with real models on 2026-08-23.

## 2. Data We Collect / Train On

### 2.1 Source
58 Reddit subs defined in `config/settings.py:12` (`REDDIT_SUBREDDITS`) — core (`memes`, `dankmemes`, `me_irl`, `AdviceAnimals`), gen-z/shitpost (`shitposting`, `okbuddyretard`, `surrealmemes`), niche (`ProgrammerHumor`, `HistoryMemes`, `Animemes`, 196, etc.), templates (`MemeTemplatesOfficial`, `BlankTemplatesForMemes`), reaction/wholesome/animal subs. Crawler is `scrapers/reddit_arctic_scraper.py` via Arctic Shift API with `search_page()` + `ThreadPoolExecutor` per `collect_to_target.py`.

### 2.2 Current snapshot (live DB, 2026-08-23)
- **24475 memes** in `curated_metadata.json` (21 MB), **24563 files** on disk (`data/curated/<sub>/*.jpg`, 9.7 GB). 88 orphans from a killed run.
- **Top subs:** `r/memes` 13960 (57.0%), `r/ComedyNecrophilia` 2318 (9.5%), `r/shitposting` 1686 (6.9%), `r/surrealmemes` 1483 (6.1%), `r/AdviceAnimals` 1084, `r/dankmemes` 1070, `r/me_irl` 856 — heavily imbalanced (first high-yield sub floods before per-sub cap — known).
- **Fields per record** (`curated_metadata.json:94`): `id` (uuid), `source`, `source_sub` (`r/memes`), `source_id`, `source_url`, `image_url`, `image_path` (`data\curated\...`), `title` (≤300 chars), `author`, `upvotes`, `comments`, `quality_score` (`min(up/50000,1)*0.5 + min(pixels/1080p,1)*0.5`), `image_type` (square/portrait/landscape), `resolution` [w,h], `format`, `file_size_kb`, `community_category` (`general`/`template`), `posted_at`/`collected_at`.
- **Quality gates at ingest** (`collect_to_target.py:42`): `MIN_RES (400,400)`, `MIN_KB 20`, `UPVOTE_MIN 5` (templates exempt), `is_static` (jpg/jpeg/png/webp only, no gif/video), dedup via `utils/dedup.py` (pHash). Legacy 452 small-res + 84 small-file + 10908 low-score (<0.12) records pre-date current gates.
- **Target:** 50k balanced (~860/sub). Other agent owns collection to 50k; do not touch `collect_target.log/.lock`.

### 2.3 Text side
- **Title** (post title) + **OCR caption** extracted from the image itself (`pipeline/ocr.py` → `ocr_cache.json` `{id: "STOP MAKING FUN..."}`) — this is what makes “rust API safety” match via image text, not just title.
- **Search document** built in `search/build_index.py:36` as `build_doc() = title + source_sub + community_category + humor_signal + OCR_text`.

### 2.4 Training data view (if you fine-tune/generate)
You have **image ↔ text pairs**: image file + `title` + OCR text + sub/category + upvotes. For retrieval fine-tuning, the pair is `(query text, search_doc)`; for generation (e.g., SD/MemeGen), the pair is `(prompt = title/OCR, image)`. Sub/category can be used as conditioning. Templates (`r/MemeTemplatesOfficial` etc.) are blank — useful for generation, not retrieval ranking.

## 3. Pipeline — How It Works

### Step 0 — Drive layout (Colab prereq)
Upload once to `/MyDrive/MakeMeMeme/`: `curated_metadata.json` and `data/curated/**`. `config/settings.py:187` `resolve_image_path()` strips leading `data/` and joins with `MAKEMEME_IMAGES`.

### Step 1 — `pipeline/download_images.py`
Input: `MAKEMEME_CATALOG` (catalog json) + `MAKEMEME_IMAGES` (dest). Concurrent `ThreadPoolExecutor(8)`, skips `os.path.exists(out)`. Verified: `exists:12` → delete 2 → `ok:2` re-download from `i.redd.it`. Env: `MAKEMEME_CATALOG`, `MAKEMEME_IMAGES`.

### Step 2 — `pipeline/ocr.py` (PaddleOCR 3.x)
Input: catalog + `IMAGES_DIR`. Output: `ocr_cache.json`.
- Init: `PaddleOCR(lang="en", device="gpu"/"cpu", use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=True, enable_mkldnn=False on CPU)` — 3.x API (`pipeline/ocr.py:29`). Fixed from 2.x (`use_gpu`, `use_angle_cls`, `cls=True` crash).
- Inference: `ocr.predict(path)` → `res["rec_texts"]` joined. Batched `MAKEMEME_OCR_BATCH=16`, resumable (skips keys in cache). First run downloads `PP-OCRv6_medium_det/rec` + `PP-LCNet_x1_0_textline_ori` to `.paddlex/`.
- Verified 12/12 captions (e.g., “made with mematic”, “imgflip.com”).

### Step 3 — `search/build_index.py`
Input: catalog + OCR cache. Output: `search/index/memes.json` + `vectors.npy` (normalized).
- `build_doc()` per meme → `MemeSearcher.embed_docs()` via `BAAI/bge-large-en-v1.5` (`SentenceTransformer`, `normalize_embeddings=True`, `BGE_QUERY_PREFIX` for queries only). Verified with cached 1.3 GB weights.

### Step 4 — `search/retrieve.py` + `search/cli.py` / `search/app.py`
- `MemeSearcher` loads `vectors.npy` + `memes.json`.
- Query: `embed_query(BGE_QUERY_PREFIX+text)` → cosine `vectors @ qv` → top 30 → `CrossEncoder(BAAI/bge-reranker-v2-m3).predict(pairs)` → top K (6). Verified: “where I spawn in minecraft” → MinecraftMemes 0.853, “rust API safety meme” → ProgrammerHumor 0.847 (matched via OCR text).
- CLI: `python -m search.cli "query" --k 6`; UI: `python -m search.app` (Gradio Gallery, `MAKEMEME_SHARE=1` → public link, verified HTTP 200 on :7860).

All env-overridable via `config/settings.py:160` `_env()` (see `COLAB_COMMANDS.md`).

## 4. Models — Why

| Model | Role | Why |
|-------|------|-----|
| `BAAI/bge-large-en-v1.5` | Embedding (1024-d) | Best open-source retrieval, Colab-friendly, HF cached |
| `BAAI/bge-reranker-v2-m3` | Rerank | Cross-encoder gives large score gaps (0.85 vs 0.00 verified) |
| PaddleOCR `PP-OCRv6` | Caption extraction | Handles meme fonts/rotations, GPU-fast on Colab |

## 5. How to Run

See `README.md` / `COLAB_COMMANDS.md` / `colab/makememe.ipynb` (9 cells, copy-paste). Local smoke: `python search/smoke_test.py` (no models).

## 6. What’s Next (if training a generator)
- Balance to 50k, add per-sub cap mid-run (r/memes 57% now).
- Fold 88 orphans, purge legacy small/low-score if strict quality needed.
- For fine-tuning: use `(search_doc, image)` pairs; templates as blank conditioning; upvotes/quality_score as sampling weight.
