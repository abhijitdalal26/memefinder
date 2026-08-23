"""CLI: python -m search.cli "lazy monday" """
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import TOP_K
from search.retrieve import MemeSearcher


def main():
    p = argparse.ArgumentParser(description="MakeMeMeme text -> relevant memes")
    p.add_argument("query", nargs="+", help="natural-language description of the meme")
    p.add_argument("--k", type=int, default=TOP_K, help="number of results")
    args = p.parse_args()

    query = " ".join(args.query)
    searcher = MemeSearcher()
    results = searcher.search(query, k=args.k)

    import sys
    out = sys.stdout
    if hasattr(out, "reconfigure"):
        out.reconfigure(encoding="utf-8", errors="replace")
    print(f"\nTop {len(results)} memes for: {query!r}\n" + "-" * 60)
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r['score']:.3f}] {r.get('title')}")
        print(f"   sub: {r.get('source_sub')} | cat: {r.get('community_category')}")
        if r.get("image_url"):
            print(f"   url: {r['image_url']}")
        print()


if __name__ == "__main__":
    main()
