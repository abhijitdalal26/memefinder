# MemeFinder — Text-to-Meme Retrieval

Describe a meme in words, get the best matches. Built on 24k+ curated Reddit memes with OCR + `bge-large` embeddings + `bge-reranker` + Gradio.

## Pipeline (verified end-to-end on 12 images, 2026-08-23)

```
Reddit crawl → curate (quality/dedup) → pipeline/download_images.py → pipeline/ocr.py → search/build_index.py → search (retrieve + rerank) → Gradio UI
```

All colab steps are GPU-ready and resumable.

## Quick Start — Colab (T4 GPU)

> Full copy-paste cells: [`COLAB_COMMANDS.md`](COLAB_COMMANDS.md) and [`colab/makememe.ipynb`](colab/makememe.ipynb)

1. **Mount Drive**
```python
from google.colab import drive
drive.mount('/content/drive')
```

2. **Clone + install** (order matters — `paddlepaddle-gpu` after `paddleocr`)
```python
%cd /content
REPO_URL = "https://github.com/abhijitdalal26/memefinder.git"
import os
if not os.path.exists("/content/MakeMeMeme"):
    !git clone {REPO_URL}
%cd /content/MakeMeMeme  # or /content/memefinder depending on repo name
!pip install -q sentence-transformers gradio
!pip install -q paddleocr
!pip install -q paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

3. **Configure paths** (edit Drive path if yours differs)
```python
%env MAKEMEME_ROOT=/content/MakeMeMeme
%env MAKEMEME_IMAGES=/content/drive/MyDrive/MakeMeMeme/data
%env MAKEMEME_CATALOG=/content/drive/MyDrive/MakeMeMeme/curated_metadata.json
%env MAKEMEME_OCR=/content/drive/MyDrive/MakeMeMeme/ocr_cache.json
%env MAKEMEME_INDEX=/content/MakeMeMeme/search/index
%env MAKEMEME_SHARE=1
```

4. **Run**
```python
!python pipeline/download_images.py   # resumable, skips existing
!python pipeline/ocr.py               # PaddleOCR 3.x, batched, resumable
!python search/build_index.py         # bge-large embeddings
!python -m search.cli "i don't want to work today"
!python -m search.app                 # Gradio share link
```

**Drive prereq** (upload once):
```
/MyDrive/MakeMeMeme/curated_metadata.json
/MyDrive/MakeMeMeme/data/curated/<sub>/<image>.jpg
```

## Local Run

```bash
pip install -r requirements.txt
# CPU paddle: pip install paddlepaddle  (GPU on Colab as above)
python pipeline/download_images.py
python pipeline/ocr.py          # set MAKEMEME_OCR_GPU=0 for CPU
python search/build_index.py
python -m search.cli "when you pretend to work but do nothing"
python -m search.app            # http://127.0.0.1:7860
```

Env vars: `MAKEMEME_ROOT`, `MAKEMEME_IMAGES`, `MAKEMEME_CATALOG`, `MAKEMEME_OCR`, `MAKEMEME_INDEX`, `MAKEMEME_SHARE`, `MAKEMEME_OCR_GPU`, `MAKEMEME_OCR_BATCH` (see `config/settings.py`).

`python search/smoke_test.py` — network-free wiring check (no models needed).

## Models

| Model | Use | Size |
|-------|-----|------|
| `BAAI/bge-large-en-v1.5` | Text embeddings (1024-d, `BGE_QUERY_PREFIX` for queries) | ~1.3 GB |
| `BAAI/bge-reranker-v2-m3` | Cross-encoder reranking of top 30 → top 6 | ~2.2 GB |
| `PaddleOCR 3.x` (`PP-OCRv6` det + rec + `PP-LCNet` orientation) + `paddlepaddle 3.3` | OCR meme captions | auto-downloaded on first run |

All models cached in HF Hub / `.paddlex` — no manual download needed.

## Files

| File | What it does |
|------|--------------|
| `config/settings.py` | All env-overridable paths (`MAKEMEME_*`) + `EMBED_MODEL`/`RERANK_MODEL` |
| `pipeline/download_images.py` | Downloads `image_url` → `IMAGES_DIR/curated/<sub>/` (threaded, skips existing) |
| `pipeline/ocr.py` | Runs PaddleOCR on each image → `ocr_cache.json` (batched, resumable, strips `imgflip.com`/`mematic` watermarks, `conf>=0.5` filter, whitespace cleaning) |
| `search/build_index.py` | Builds `search_doc = title + sub + category + OCR` → `vectors.npy` + `memes.json` |
| `search/retrieve.py` | `MemeSearcher` — embeds query, cosine recall, reranks |
| `search/app.py` | Gradio UI — textbox → gallery of 6 memes |
| `search/cli.py` | CLI — `python -m search.cli "your query"` |
| `search/smoke_test.py` | Offline wiring test with dummy embeddings |
| `colab/makememe.ipynb` | Colab notebook (9 runnable cells) |
| `COLAB_COMMANDS.md` | Same commands as flat markdown (1 block = 1 cell) |
| `requirements.txt` | `requests`, `Pillow`, `sentence-transformers`, `gradio`, `paddleocr` |

## What’s on GitHub

Only the 25 pipeline files above are tracked. Large/debug files stay local (`.gitignore`): `data/`, `curated_metadata.json`, `collect_*.py`, `debug_*`, `_patch_*`, `AGENT.md`, logs, `.venv`, `.paddlex`, `search/index/`.

## Notes

- OCR uses `PaddleOCR 3.x` (`device=`, `predict()`, `rec_texts`). The 2.x API (`use_gpu`, `use_angle_cls`, `cls=True`) is removed.
- Colab CUDA 12.x requires `paddlepaddle-gpu==3.3.0` from `.../stable/cu126/` — not the old `2.6.1.post112`.
- `paddle` and `torch` cannot be imported in the same process on Windows (DLL clash) — keep OCR and embedding in separate processes (as Colab does).
