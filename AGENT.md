# AGENT.md — MakeMeMeme

> Read this before touching code. Keep changes minimal and verified.

## What this repo is
Image-meme retrieval: **Reddit scrape → curate (quality/dedup) → download → OCR → embed + rerank → Gradio search**. Deployed on Colab (T4 GPU), images+catalog live on Drive.

## Stack (pinned)
- Python 3.13 (local), 3.12 (Colab). `torch 2.13 CPU` / `sentence-transformers 6.0` / `gradio 6.25` / `numpy 2.5`
- **OCR:** `paddleocr>=3.0` + `paddlepaddle 3.3.x` (CPU locally, `paddlepaddle-gpu==3.3.0 cu126` on Colab). API is 3.x (`device=`, `predict()`, `res["rec_texts"]`) — see `pipeline/ocr.py:29`.
- Embeddings: `BAAI/bge-large-en-v1.5` (1024-d), reranker: `BAAI/bge-reranker-v2-m3` — both cached in HF hub, no download needed on this machine.

## Layout
```
config/settings.py        # env-overridable paths (ROOT, IMAGES_DIR, CATALOG_FILE, OCR_CACHE_FILE, INDEX_DIR)
pipeline/download_images.py  # resumable fetch image_url -> IMAGES_DIR
pipeline/ocr.py           # batched PaddleOCR, resumable via ocr_cache.json (fixed for 3.x + enable_mkldnn=False on CPU)
search/build_index.py     # embed search_doc (title+sub+cat+OCR) -> vectors.npy + memes.json
search/retrieve.py        # MemeSearcher (embed query + cosine + cross-encoder rerank)
search/app.py             # Gradio Gallery UI
search/cli.py             # CLI search
colab/makememe.ipynb      # Colab notebook (source of truth for remote run)
COLAB_COMMANDS.md         # same commands as flat markdown, 1 block = 1 cell
data/curated/<sub>/*.jpg  # 24k+ images (~9.7 GB) — NOT committed, uploaded to Drive
curated_metadata.json     # catalog — uploaded to Drive
```

## Env vars (all optional, via `config/settings.py:_env`)
```
MAKEMEME_ROOT    = repo root (/content/MakeMeMeme on Colab)
MAKEMEME_IMAGES  = where images live (/content/drive/MyDrive/MakeMeMeme/data on Colab)
MAKEMEME_CATALOG = catalog json (/content/drive/MyDrive/MakeMeMeme/curated_metadata.json on Colab)
MAKEMEME_OCR     = ocr cache json
MAKEMEME_INDEX   = index dir (search/index)
MAKEMEME_SHARE   = 1 -> Gradio public link
MAKEMEME_OCR_GPU = 1/0 (default 1 on Colab)
MAKEMEME_OCR_BATCH = 16 (batch size for ocr.py)
```

`resolve_image_path()` strips leading `data/` from catalog `image_path` and joins with `IMAGES_DIR` — Drive layout must be `data/curated/...` under `MAKEMEME_IMAGES`.

## Verified end-to-end (2026-08-23, 12-image subset in temp Drive-layout dir)
```
set MAKEMEME_CATALOG=.../catalog12.json && set MAKEMEME_IMAGES=.../data && python pipeline/download_images.py  # exists:12, re-download:2 OK
set MAKEMEME_CATALOG=... && set MAKEMEME_IMAGES=... && set MAKEMEME_OCR=.../ocr_cache.json && set MAKEMEME_OCR_GPU=0 && python pipeline/ocr.py  # 12/12 captions, batch 16
set MAKEMEME_CATALOG=... && set MAKEMEME_IMAGES=... && set MAKEMEME_OCR=... && set MAKEMEME_INDEX=.../index && python search/build_index.py
set MAKEMEME_INDEX=... && python -m search.cli "where I spawn in minecraft" --k 3  # MinecraftMemes 0.853 top hit
set MAKEMEME_INDEX=... && python -m search.cli "rust API safety meme" --k 3        # ProgrammerHumor 0.847 top hit (via OCR text)
python -m search.app  # with MAKEMEME_INDEX/IMAGES/SHARE=0 -> HTTP 200 on :7860
search/smoke_test.py  # PASSED (dummy embedder, no models)
```
If you change OCR/build/retrieve/app, re-run the subset flow above before claiming "works on Colab".

## Colab run
See `COLAB_COMMANDS.md` and `colab/makememe.ipynb` (17 cells). Order: mount Drive → clone (`REPO_URL`) → install `sentence-transformers gradio`, then `paddleocr`, then `paddlepaddle-gpu==3.3.0 -i .../cu126/` (GPU overwrites CPU) → set `%env` → `download_images.py` → `ocr.py` → `build_index.py` → `search.cli` test → `search.app`. First OCR run downloads PP-OCRv6 models.

## Collection (DO NOT TOUCH — other agent owns it)
- `collect_to_target.py` is the parallel collector (TARGET 50k, `PARALLEL`, `slock`, checkpointing). Currently at 24,475/50k.
- `collect_target.log` + `collect_target.lock` (pid 4984, stale) belong to the collector agent. Do not delete the lock, do not run collection, do not edit `curated_metadata.json`/`data/curated/` unless asked.
- Your job is pipeline verification only (the 12-image flow above).

## Gotchas fixed — do not regress
1. `pipeline/ocr.py` must stay on paddleocr 3.x API (`device=`, `predict()`, `rec_texts`) with `enable_mkldnn=False` on CPU; `use_gpu`/`use_angle_cls`/`show_log`/`cls=True` are dead.
2. Colab paddle GPU wheel is `cu126` (CUDA 12.x), not `2.6.1.post112 cu112`.
3. `paddle` and `torch` cannot be imported in the same process on this Windows venv (DLL clash) — keep OCR and embedding in separate processes (as Colab does).
4. `requirements.txt` pins `paddleocr>=3.0`; Colab installs GPU paddle *after* paddleocr.

## What to do before pushing
- `python search/smoke_test.py` must pass.
- If you touched `colab/makememe.ipynb`, validate: `python -c "import json; json.load(open('colab/makememe.ipynb'))"`.
- Do not commit `.venv/`, `data/`, `__pycache__/`, `*.part`, `collect_target.log`, `.paddlex/` caches.

## Your checklist before hand-off
- [ ] Upload to Drive: `curated_metadata.json` → `/MyDrive/MakeMeMeme/curated_metadata.json`, `data/curated/**` → `/MyDrive/MakeMeMeme/data/curated/**`
- [ ] Set `REPO_URL` in notebook to your GitHub fork, commit + push, verify notebook runs top-to-bottom on a fresh Colab T4 runtime
