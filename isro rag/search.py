"""
Hybrid search over the knowledge base - used to check that the index works.

dense (Azure OpenAI) top-k  ┐
                            ├─> Reciprocal Rank Fusion ─> top results
bm25 (sparse) top-k        ┘

Usage:
    python search.py "What was the launch mass of GSAT-7?"
    python search.py "Chandrayaan-3 landing site" --mode bm25 -k 5
"""

from __future__ import annotations

import argparse

from qdrant_client import QdrantClient, models

from index import DENSE, SPARSE


def hybrid_search(client: QdrantClient, collection: str, dense, sparse, query: str,
                  k: int = 8, prefetch_k: int = 30, mode: str = "hybrid",
                  chunk_type: str | None = None) -> list[models.ScoredPoint]:
    flt = None
    if chunk_type:
        flt = models.Filter(must=[models.FieldCondition(key="chunk_type", match=models.MatchValue(value=chunk_type))])
    if mode == "dense":
        return client.query_points(collection, query=dense.embed_query(query), using=DENSE,
                                   query_filter=flt, limit=k, with_payload=True).points
    if mode == "bm25":
        return client.query_points(collection, query=sparse.embed_query(query), using=SPARSE,
                                   query_filter=flt, limit=k, with_payload=True).points
    return client.query_points(
        collection,
        prefetch=[
            models.Prefetch(query=dense.embed_query(query), using=DENSE, limit=prefetch_k, filter=flt),
            models.Prefetch(query=sparse.embed_query(query), using=SPARSE, limit=prefetch_k, filter=flt),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=k,
        with_payload=True,
    ).points


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--mode", choices=["hybrid", "dense", "bm25"], default="hybrid")
    ap.add_argument("--type", choices=["text", "facts", "table"], help="filter by chunk type")
    args = ap.parse_args()

    from config import get_settings
    from embeddings import AzureOpenAIEmbedder, BM25Embedder
    from index import get_client

    s = get_settings()
    client = get_client(s)
    dense = AzureOpenAIEmbedder(s) if args.mode != "bm25" else None
    sparse = BM25Embedder(s.sparse_model, s.model_cache)
    hits = hybrid_search(client, s.chunks_collection, dense, sparse, args.query, k=args.k,
                         mode=args.mode, chunk_type=args.type)
    for i, h in enumerate(hits, 1):
        p = h.payload
        print(f"\n[{i}] score={h.score:.4f}  {p['chunk_type']:<5}  {p['breadcrumb']}")
        print(f"    {p['url']}")
        print("    " + p["content"][:300].replace("\n", "\n    "))
    client.close()


if __name__ == "__main__":
    main()
