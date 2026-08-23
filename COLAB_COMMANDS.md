# MakeMeMeme — Colab Commands (one block = one cell)

> **Before running:** Runtime → Change runtime type → **T4 GPU**. The notebook and these commands assume GPU.

---

### Cell 1 — Mount Drive

```python
from google.colab import drive
drive.mount('/content/drive')
```

---

### Cell 2 — Clone repo + install deps

> Set `REPO_URL` to your fork. Install order matters: `paddleocr` first (pulls CPU paddle), then the GPU build overwrites it.

```python
%cd /content
REPO_URL = "https://github.com/YOUR_USERNAME/MakeMeMeme.git"  # <-- edit this
import os
if not os.path.exists("/content/MakeMeMeme"):
    !git clone {REPO_URL}
%cd /content/MakeMeMeme
!pip install -q sentence-transformers gradio
!pip install -q paddleocr
!pip install -q paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

---

### Cell 3 — Verify paddle GPU build

```python
import paddle
print("paddle", paddle.__version__, "| GPU compiled:", paddle.device.is_compiled_with_cuda())
```

Expected: `paddle 3.3.0 | GPU compiled: True`

---

### Cell 4 — Configure paths

> Edit the Drive path if yours differs. `MAKEMEME_IMAGES` must point to the folder that contains `curated/` on Drive.

```python
%env MAKEMEME_ROOT=/content/MakeMeMeme
%env MAKEMEME_IMAGES=/content/drive/MyDrive/MakeMeMeme/data
%env MAKEMEME_CATALOG=/content/drive/MyDrive/MakeMeMeme/curated_metadata.json
%env MAKEMEME_OCR=/content/drive/MyDrive/MakeMeMeme/ocr_cache.json
%env MAKEMEME_INDEX=/content/MakeMeMeme/search/index
%env MAKEMEME_SHARE=1
```

Prereq on Drive — upload once before Cell 5:
```
/MyDrive/MakeMeMeme/curated_metadata.json
/MyDrive/MakeMeMeme/data/curated/<sub>/<image>.jpg
```

---

### Cell 5 — Download images (resumable, skips existing)

```python
!python pipeline/download_images.py
```

---

### Cell 6 — OCR with PaddleOCR 3.x → ocr_cache.json (resumable, GPU)

Batched (`MAKEMEME_OCR_BATCH` default `16`), skips ids already in `ocr_cache.json`. First run auto-downloads PP-OCRv6 det/rec + textline-orientation models.

```python
!python pipeline/ocr.py
```

Optional large-run tuning:
```python
%env MAKEMEME_OCR_BATCH=32
!python pipeline/ocr.py
```

---

### Cell 7 — Build embedding index

```python
!python search/build_index.py
```

Outputs:
```
/content/MakeMeMeme/search/index/memes.json
/content/MakeMeMeme/search/index/vectors.npy
```

---

### Cell 8 — CLI smoke test

```python
!python -m search.cli "i don't want to work today"
```

---

### Cell 9 — Launch Gradio UI (public share link)

`MAKEMEME_SHARE=1` from Cell 4 creates a `gradio.live` link in the output.

```python
!python -m search.app
```

Stop with Runtime → Interrupt execution when done.
