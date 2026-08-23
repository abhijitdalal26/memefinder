"""Network-free smoke test: validates the retrieval wiring using a dummy
embedder (random but stable per text). Proves build -> search -> top-K works
without downloading bge models. Real accuracy is verified on laptop/Colab.
"""
import os
import sys
import json
import hashlib
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config.settings as settings  # noqa: E402
import search.build_index as bi  # noqa: E402
import search.retrieve as rt  # noqa: E402


def dummy_embed(texts):
    dim = 64
    out = []
    for t in texts:
        h = hashlib.md5(t.encode("utf-8")).digest()
        vec = np.array([(b - 128) / 128.0 for b in h], dtype=np.float32)
        if len(vec) < dim:
            vec = np.concatenate([vec, np.zeros(dim - len(vec), dtype=np.float32)])
        else:
            vec = vec[:dim]
        out.append(vec)
    out = np.array(out, dtype=np.float32)
    out = out / np.linalg.norm(out, axis=1, keepdims=True)
    return out


class FakeReranker:
    def predict(self, pairs):
        scores = []
        for q, d in pairs:
            qs = set(q.lower().split())
            ds = set(d.lower().split())
            scores.append(float(len(qs & ds)))
        return np.array(scores, dtype=np.float32)


def main():
    fixture = os.path.join(ROOT, "search", "fixtures", "sample.json")
    catalog = json.load(open(fixture, encoding="utf-8"))
    ocr = {settings.meme_key(m): m.get("ocr_text", "") for m in catalog}

    docs, memes = [], []
    for m in catalog:
        doc = bi.build_doc(m, ocr)
        assert doc, f"empty doc for {settings.meme_key(m)}"
        docs.append(doc)
        memes.append(
            {
                "meme_id": settings.meme_key(m),
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
    vectors = dummy_embed(docs)

    # Build a searcher with the dummy backend (no real models needed).
    searcher = rt.MemeSearcher.__new__(rt.MemeSearcher)
    searcher.vectors = vectors
    searcher.memes = memes
    searcher._embed = None
    searcher._rerank = None
    searcher.embed_query = lambda text: dummy_embed([text])[0]
    searcher._get_rerank = lambda: FakeReranker()

    results = rt.MemeSearcher.search(searcher, "i don't want to work today", k=6)
    assert len(results) == 6, f"expected 6, got {len(results)}"
    print("SMOKE TEST PASSED")
    for r in results:
        print(f"  {r['score']:.2f}  {r['title']}")


if __name__ == "__main__":
    main()
