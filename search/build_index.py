"""Build the search index from the catalog + OCR cache.

For each meme we assemble a text "document" from its title, subreddit,
community category, humor signal, and (if present) OCR'd caption text, then
embed it with bge-large and persist vectors + a memes manifest.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    CATALOG_FILE,
    OCR_CACHE_FILE,
    INDEX_DIR,
    MEMES_JSON,
    VECTORS_NPY,
    meme_key,
)
from search.retrieve import MemeSearcher


def load_catalog():
    with open(CATALOG_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_ocr():
    if os.path.exists(OCR_CACHE_FILE):
        with open(OCR_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def build_doc(m: dict, ocr: dict) -> str:
    parts = [
        m.get("title", ""),
        m.get("source_sub", ""),
        m.get("community_category", ""),
        m.get("humor_signal", ""),
    ]
    ocr_text = ocr.get(meme_key(m))
    if ocr_text:
        parts.append(ocr_text)
    return " ".join(p for p in parts if p).strip()


def main():
    catalog = load_catalog()
    ocr = load_ocr()
    print(f"Catalog: {len(catalog)} memes | OCR cache: {len(ocr)} entries")

    docs, memes = [], []
    for m in catalog:
        doc = build_doc(m, ocr)
        docs.append(doc)
        memes.append(
            {
                "meme_id": meme_key(m),
                "source": m.get("source"),
                "source_sub": m.get("source_sub"),
                "title": m.get("title"),
                "image_path": m.get("image_path"),
                "image_url": m.get("image_url"),
                "community_category": m.get("community_category"),
                "humor_signal": m.get("humor_signal"),
                "search_doc": doc,
            }
        )

    print(f"Embedding {len(docs)} documents...")
    vectors = MemeSearcher.embed_docs(docs)

    os.makedirs(os.path.dirname(VECTORS_NPY), exist_ok=True)
    os.makedirs(os.path.dirname(MEMES_JSON), exist_ok=True)
    import numpy as np
    np.save(VECTORS_NPY, vectors)
    with open(MEMES_JSON, "w", encoding="utf-8") as f:
        json.dump(memes, f, ensure_ascii=False, indent=2)

    print(f"Saved vectors -> {VECTORS_NPY}")
    print(f"Saved manifest -> {MEMES_JSON}")


if __name__ == "__main__":
    main()
