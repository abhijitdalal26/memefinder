"""Core retrieval: embed query, cosine recall, cross-encoder rerank -> top-K.

Models (best open-source, run on GPU):
  - embeddings: BAAI/bge-large-en-v1.5
  - reranker:   BAAI/bge-reranker-v2-m3
"""
import os
import sys
import json
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import (
    EMBED_MODEL,
    RERANK_MODEL,
    BGE_QUERY_PREFIX,
    VECTORS_NPY,
    MEMES_JSON,
    INDEX_DIR,
    TOP_K,
    RERANK_CANDIDATES,
)


class MemeSearcher:
    def __init__(self):
        self._embed = None
        self._rerank = None
        self.vectors = np.load(VECTORS_NPY)
        with open(MEMES_JSON, encoding="utf-8") as f:
            self.memes = json.load(f)

    # --- model loading (lazy, so import is cheap) -------------------------
    def _get_embed(self):
        if self._embed is None:
            from sentence_transformers import SentenceTransformer
            self._embed = SentenceTransformer(EMBED_MODEL)
        return self._embed

    def _get_rerank(self):
        if self._rerank is None:
            from sentence_transformers import CrossEncoder
            self._rerank = CrossEncoder(RERANK_MODEL)
        return self._rerank

    # --- encoding ---------------------------------------------------------
    def embed_query(self, text: str) -> np.ndarray:
        vec = self._get_embed().encode(
            BGE_QUERY_PREFIX + text, normalize_embeddings=True
        )
        return np.asarray(vec, dtype=np.float32)

    @staticmethod
    def embed_docs(texts) -> np.ndarray:
        from sentence_transformers import SentenceTransformer
        vecs = SentenceTransformer(EMBED_MODEL).encode(
            list(texts), normalize_embeddings=True
        )
        return np.asarray(vecs, dtype=np.float32)

    # --- search -----------------------------------------------------------
    def search(self, query: str, k: int = TOP_K):
        qv = self.embed_query(query)
        sims = self.vectors @ qv  # cosine (vectors are normalized)
        cand_idx = np.argsort(-sims)[:RERANK_CANDIDATES]

        reranker = self._get_rerank()
        pairs = [
            (query, self.memes[int(i)].get("search_doc", "")) for i in cand_idx
        ]
        scores = np.asarray(reranker.predict(pairs), dtype=np.float32)

        order = np.argsort(-scores)
        results = []
        for rank, o in enumerate(order[:k]):
            i = int(cand_idx[int(o)])
            meme = dict(self.memes[i])
            meme["score"] = float(scores[int(o)])
            results.append(meme)
        return results


def main():
    import sys
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "lazy monday"
    searcher = MemeSearcher()
    for r in searcher.search(q):
        print(f"{r['score']:.3f}  {r.get('title')}  ({r.get('source_sub')})")


if __name__ == "__main__":
    main()
