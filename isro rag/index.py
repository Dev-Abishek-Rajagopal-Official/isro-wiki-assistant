"""
Load chunks and parents into Qdrant.

Collections
  isro_chunks   one point per chunk
                  vectors: "dense" (Azure OpenAI, cosine) + "bm25" (sparse, IDF applied by Qdrant)
                  payload: content, breadcrumb, title, section_path, chunk_type, url, revid,
                           parent_id, prev_id, next_id, keywords, categories, ...
  isro_parents  one point per parent section, no vectors - fetched by id for context expansion

Point ids are UUIDv5 of the chunk/parent id, so re-indexing overwrites instead of duplicating.
Chunks are streamed from chunks.jsonl in batches; embeddings are cached (see embeddings.py).

Usage:
    python chunking.py      # first, produces data/chunks.jsonl + data/parents.jsonl
    python index.py         # embeds + uploads (rebuilds the collections)
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Iterator

from qdrant_client import QdrantClient, models

from config import Settings, get_settings

DENSE, SPARSE = "dense", "bm25"
KEYWORD_INDEXES = ["chunk_type", "title", "parent_id", "categories", "keywords"]


def point_id(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"isro-rag/{key}"))


def get_client(s: Settings) -> QdrantClient:
    if s.qdrant_url:
        return QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None, timeout=60)
    return QdrantClient(path=str(s.qdrant_path))  # local mode, no server needed


def is_local(client: QdrantClient) -> bool:
    from qdrant_client.local.qdrant_local import QdrantLocal

    return isinstance(getattr(client, "_client", None), QdrantLocal)


def embedding_text(chunk: dict, with_breadcrumb: bool = True) -> str:
    """What gets embedded: breadcrumb gives the chunk its context (article > section)."""
    return f"{chunk['breadcrumb']}\n\n{chunk['content']}" if with_breadcrumb else chunk["content"]


def read_jsonl(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def batched(it, n: int):
    it = iter(it)
    while batch := list(islice(it, n)):
        yield batch


def create_collections(client: QdrantClient, chunks: str, parents: str, dim: int) -> None:
    for name in (chunks, parents):
        if client.collection_exists(name):
            client.delete_collection(name)
    client.create_collection(
        chunks,
        vectors_config={DENSE: models.VectorParams(size=dim, distance=models.Distance.COSINE)},
        sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    client.create_collection(parents, vectors_config={})
    # Payload indexes make filtering fast on a server; local mode does not support them.
    if is_local(client):
        return
    for field in KEYWORD_INDEXES:
        client.create_payload_index(chunks, field, models.PayloadSchemaType.KEYWORD)
    client.create_payload_index(chunks, "doc_id", models.PayloadSchemaType.INTEGER)


def build_index(client: QdrantClient, dense, sparse, chunks_path: Path, parents_path: Path,
                chunks_collection: str, parents_collection: str, batch_size: int = 128,
                with_breadcrumb: bool = True) -> dict:
    """Rebuild both collections. Returns counts."""
    n_chunks = n_parents = 0
    created = False
    for batch in batched(read_jsonl(chunks_path), batch_size):
        texts = [embedding_text(c, with_breadcrumb) for c in batch]
        dense_vecs = dense.embed_documents(texts)
        sparse_vecs = sparse.embed_documents(texts)
        if not created:
            create_collections(client, chunks_collection, parents_collection, len(dense_vecs[0]))
            created = True
        client.upsert(chunks_collection, points=[
            models.PointStruct(id=point_id(c["chunk_id"]), vector={DENSE: d, SPARSE: sp}, payload=c)
            for c, d, sp in zip(batch, dense_vecs, sparse_vecs)
        ])
        n_chunks += len(batch)
        print(f"  chunks indexed: {n_chunks}", flush=True)
    if not created:
        raise RuntimeError(f"No chunks found in {chunks_path}")

    for batch in batched(read_jsonl(parents_path), 256):
        client.upsert(parents_collection, points=[
            models.PointStruct(id=point_id(p["parent_id"]), vector={}, payload=p) for p in batch
        ])
        n_parents += len(batch)

    stored = client.count(chunks_collection, exact=True).count
    if stored != n_chunks:
        raise RuntimeError(f"Expected {n_chunks} points in {chunks_collection}, found {stored}")
    return {"chunks": n_chunks, "parents": n_parents}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chunks", type=Path, help="default: data/chunks.jsonl")
    ap.add_argument("--parents", type=Path, help="default: data/parents.jsonl")
    args = ap.parse_args()
    s = get_settings()
    chunks_path = args.chunks or s.data_dir / "chunks.jsonl"
    parents_path = args.parents or s.data_dir / "parents.jsonl"

    from embeddings import BM25Embedder, build_dense_embedder

    dense = build_dense_embedder(s)
    sparse = BM25Embedder(s.sparse_model, s.model_cache)
    client = get_client(s)
    where = s.qdrant_url or f"local mode ({s.qdrant_path})"
    print(f"Indexing into {where} with {dense.model_id} + {s.sparse_model}", flush=True)

    t0 = time.time()
    counts = build_index(client, dense, sparse, chunks_path, parents_path,
                         s.chunks_collection, s.parents_collection)
    manifest = {
        **counts,
        "dense_model": dense.model_id,
        "sparse_model": s.sparse_model,
        "chunks_collection": s.chunks_collection,
        "parents_collection": s.parents_collection,
        "qdrant": where,
        "embedding_cache_hits": dense.hits,
        "embedding_cache_misses": dense.misses,
        "seconds": round(time.time() - t0, 1),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (s.data_dir / "index_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    client.close()


if __name__ == "__main__":
    main()
