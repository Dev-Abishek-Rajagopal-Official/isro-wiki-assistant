"""
Chunk the corpus with every variant and index each into its own Qdrant collection pair
(eval_<variant>_chunks / eval_<variant>_parents). Production collections are not touched.
Embeddings come from the shared cache, so identical chunk texts are never embedded twice.

Usage:
    uv run python rag_evals/build_variants.py                 # all variants
    uv run python rag_evals/build_variants.py struct_200      # selected ones
"""

from __future__ import annotations

import argparse
import json
import statistics
import time

from common import DATA_DIR, RAG_DIR, log, record
from variants import VARIANTS, chunk_for_variant

from config import get_settings  # noqa: E402
from embeddings import BM25Embedder, build_dense_embedder  # noqa: E402
from index import build_index, get_client  # noqa: E402

DOCS = RAG_DIR.parent / "wiki documents"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("variants", nargs="*", default=list(VARIANTS))
    args = ap.parse_args()

    s = get_settings()
    dense = build_dense_embedder(s)
    sparse = BM25Embedder(s.sparse_model, s.model_cache)
    client = get_client(s)

    for name in args.variants:
        v = VARIANTS[name]
        out = DATA_DIR / "variants" / name
        out.mkdir(parents=True, exist_ok=True)
        sizes, n_parents = [], 0
        with open(out / "chunks.jsonl", "w", encoding="utf-8") as cf, \
                open(out / "parents.jsonl", "w", encoding="utf-8") as pf:
            for path in sorted(DOCS.glob("*.md")):
                chunks, parents = chunk_for_variant(v, path.read_text(encoding="utf-8"))
                cf.writelines(json.dumps(c, ensure_ascii=False) + "\n" for c in chunks)
                pf.writelines(json.dumps(p, ensure_ascii=False) + "\n" for p in parents)
                sizes += [c["token_count"] for c in chunks]
                n_parents += len(parents)

        log(f"[index] {name}: {len(sizes)} chunks, {n_parents} parents -> embedding + upload")
        hits0, miss0, t0 = dense.hits, dense.misses, time.time()
        counts = build_index(client, dense, sparse, out / "chunks.jsonl", out / "parents.jsonl",
                             v.chunks_collection, v.parents_collection, with_breadcrumb=v.with_breadcrumb)
        sizes.sort()
        record("index", name, {"chunk_config": name, "n_chunks": counts["chunks"]},
               notes=(f"{v.description}; median_tokens={int(statistics.median(sizes))}, "
                      f"p90={sizes[int(.9 * (len(sizes) - 1))]}, max={sizes[-1]}, parents={counts['parents']}, "
                      f"new_embeddings={dense.misses - miss0}, cached={dense.hits - hits0}, "
                      f"seconds={time.time() - t0:.0f}"))
    client.close()


if __name__ == "__main__":
    main()
