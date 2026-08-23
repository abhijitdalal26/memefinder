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

## Project Layout

```
config/settings.py              # env-overridable paths + model names
pipeline/download_images.py     # fetch image_url -> IMAGES_DIR (concurrent, resumable)
pipeline/ocr.py                 # PaddleOCR 3.x (predict API, enable_mkldnn=False on CPU)
search/build_index.py           # embed title+sub+category+OCR -> vectors.npy + memes.json
search/retrieve.py              # MemeSearcher: cosine recall + cross-encoder rerank
search/app.py                   # Gradio Gallery UI
search/cli.py                   # CLI search
colab/makememe.ipynb            # Colab notebook
```

## Notes

- OCR uses `PaddleOCR 3.x` (`device=`, `predict()`, `rec_texts`). The 2.x API (`use_gpu`, `use_angle_cls`, `cls=True`) is removed.
- Colab CUDA 12.x requires `paddlepaddle-gpu==3.3.0` from `.../stable/cu126/` — not the old `2.6.1.post112`.
- `paddle` and `torch` cannot be imported in the same process on Windows (DLL clash) — keep OCR and embedding in separate processes (as Colab does).
