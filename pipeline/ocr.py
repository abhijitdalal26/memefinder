"""OCR pipeline (run on Colab with GPU + mounted Drive images).

Reads the catalog, runs PaddleOCR over each local image, and writes
ocr_cache.json keyed by meme id:  { "<id>": "<extracted caption text>", ... }.

Supports paddleocr 3.x (predict() API, device=...) with a legacy 2.x fallback.
Resumable: ids already in ocr_cache.json are skipped.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    CATALOG_FILE,
    OCR_CACHE_FILE,
    IMAGES_DIR,
    resolve_image_path,
    meme_key,
)

BATCH_SIZE = int(os.environ.get("MAKEMEME_OCR_BATCH", "16"))
CONF_THRESH = float(os.environ.get("MAKEMEME_OCR_CONF", "0.5"))

# watermarks / boilerplate to strip from OCR (case-insensitive)
WATERMARKS = ["imgflip.com", "made with mematic", "mematic"]


def clean_text(text: str) -> str:
    """Post-process raw OCR: strip watermarks, collapse whitespace, trim."""
    import re

    if not text:
        return ""
    t = text
    for w in WATERMARKS:
        t = re.sub(re.escape(w), "", t, flags=re.I)
    # remove leading/trailing quote/bracket artefacts like >" 
    t = t.strip()
    t = re.sub(r"\s+", " ", t)
    t = t.strip(" \t\n\r\"'“”‘’`><|")
    t = re.sub(r"\s+", " ", t).strip()
    # drop if too short after cleaning (likely noise like "X Q")
    if len(t) < 3:
        return ""
    return t


def load_catalog():
    with open(CATALOG_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_cache():
    if os.path.exists(OCR_CACHE_FILE):
        with open(OCR_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def paddle_major() -> int:
    import paddleocr
    return int(str(paddleocr.__version__).split(".")[0])


def make_ocr(use_gpu: bool, major: int):
    from paddleocr import PaddleOCR
    if major >= 3:
        kwargs = dict(
            lang="en",
            device="gpu" if use_gpu else "cpu",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
        )
        if not use_gpu:
            kwargs["enable_mkldnn"] = False
        return PaddleOCR(**kwargs)
    return PaddleOCR(use_angle_cls=True, lang="en", use_gpu=use_gpu, show_log=False)


def extract_texts(ocr, paths, major: int, conf_thresh: float = CONF_THRESH):
    """Run OCR on a batch of paths; returns list of cleaned caption strings."""
    if major >= 3:
        if len(paths) > 1:
            # batched (GPU); CPU is forced to batch=1 in main, so this is GPU-only
            results = ocr.predict(paths)
            out = []
            for res in results:
                texts = res.get("rec_texts", []) if isinstance(res, dict) else []
                scores = res.get("rec_scores", []) if isinstance(res, dict) else []
                filtered = []
                for idx, t in enumerate(texts):
                    if not t or not t.strip():
                        continue
                    if len(scores) > idx and float(scores[idx]) < conf_thresh:
                        continue
                    filtered.append(t.strip())
                out.append(clean_text(" ".join(filtered)))
            return out
        # single image (CPU and GPU fallback)
        out = []
        for p in paths:
            res_list = ocr.predict(p)
            res = res_list[0] if res_list else {}
            texts = res.get("rec_texts", []) if isinstance(res, dict) else []
            scores = res.get("rec_scores", []) if isinstance(res, dict) else []
            filtered = []
            for idx, t in enumerate(texts):
                if not t or not t.strip():
                    continue
                if len(scores) > idx and float(scores[idx]) < conf_thresh:
                    continue
                filtered.append(t.strip())
            out.append(clean_text(" ".join(filtered)))
        return out
    out = []
    for p in paths:
        result = ocr.ocr(p, cls=True)
        lines = []
        if result and result[0]:
            for line in result[0]:
                # line = [bbox, (text, conf)]
                text, conf = line[1]
                if float(conf) < conf_thresh:
                    continue
                lines.append(text)
        out.append(clean_text(" ".join(lines)))
    return out


def main():
    use_gpu = os.environ.get("MAKEMEME_OCR_GPU", "1") == "1"
    major = paddle_major()
    eff_batch = BATCH_SIZE if use_gpu else 1
    if not use_gpu and BATCH_SIZE != 1:
        print(f"note: CPU mode forces batch=1 (requested {BATCH_SIZE}) to avoid Paddle hang")
    print(f"PaddleOCR {major}.x use_gpu={use_gpu} batch={eff_batch} conf>={CONF_THRESH}")

    ocr = make_ocr(use_gpu, major)

    catalog = load_catalog()
    cache = load_cache()
    print(f"Catalog: {len(catalog)} | already OCR'd: {len(cache)}")

    jobs = []
    for m in catalog:
        key = meme_key(m)
        if key in cache:
            continue
        path = resolve_image_path(m.get("image_path"))
        if not path or not os.path.exists(path):
            continue
        jobs.append((key, path))
    print(f"To OCR: {len(jobs)}")

    done = 0
    for i in range(0, len(jobs), eff_batch):
        batch = jobs[i : i + eff_batch]
        keys = [k for k, _ in batch]
        paths = [p for _, p in batch]
        try:
            texts = extract_texts(ocr, paths, major)
            if len(texts) != len(batch):
                raise ValueError(f"batch result mismatch {len(texts)} != {len(batch)}")
        except Exception as e:
            print(f"  batch failed ({e}); retrying one-by-one")
            texts = []
            for p in paths:
                try:
                    texts.extend(extract_texts(ocr, [p], major))
                except Exception as e2:
                    print(f"  OCR failed for {p}: {e2}")
                    texts.append("")
        for key, text in zip(keys, texts):
            cache[key] = text
            done += 1
        if done % 200 < len(batch):
            with open(OCR_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
            print(f"  progress: {done}/{len(jobs)} new, {len(cache)} total")

    with open(OCR_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f"Wrote ocr_cache -> {OCR_CACHE_FILE} ({len(cache)} entries)")


if __name__ == "__main__":
    main()
