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


def extract_texts(ocr, paths, major: int):
    """Run OCR on a batch of paths; returns list of caption strings."""
    if major >= 3:
        results = ocr.predict(paths if len(paths) > 1 else paths[0])
        out = []
        for res in results:
            texts = res["rec_texts"] if "rec_texts" in res else []
            out.append(" ".join(t.strip() for t in texts if t and t.strip()))
        return out
    out = []
    for p in paths:
        result = ocr.ocr(p, cls=True)
        lines = []
        if result and result[0]:
            for line in result[0]:
                lines.append(line[1][0])
        out.append(" ".join(lines).strip())
    return out


def main():
    use_gpu = os.environ.get("MAKEMEME_OCR_GPU", "1") == "1"
    major = paddle_major()
    print(f"PaddleOCR {major}.x use_gpu={use_gpu} batch={BATCH_SIZE}")

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
    for i in range(0, len(jobs), BATCH_SIZE):
        batch = jobs[i : i + BATCH_SIZE]
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
