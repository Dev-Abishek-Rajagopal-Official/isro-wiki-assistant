"""
Embedders used to build (and query) the Qdrant collection.

* Dense  : Azure OpenAI (text-embedding-3-large by default), wrapped in a local SQLite cache so
           re-indexing only pays for chunks whose text changed.
* Sparse : BM25 term weights from fastembed (`Qdrant/bm25`), computed locally. Qdrant applies the
           IDF part itself (collection uses Modifier.IDF).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from array import array
from pathlib import Path
from typing import Iterable, Protocol

# Must be set before huggingface_hub is imported (Windows without developer mode has no symlinks).
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from qdrant_client import models  # noqa: E402

from config import Settings  # noqa: E402


class DenseEmbedder(Protocol):
    model_id: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


# --------------------------------------------------------------------------- Azure OpenAI
class AzureOpenAIEmbedder:
    def __init__(self, s: Settings) -> None:
        if not (s.azure_endpoint and s.azure_api_key):
            raise RuntimeError("Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY in isro rag/.env")
        from openai import AzureOpenAI

        # The SDK retries 429/5xx with exponential backoff.
        self.client = AzureOpenAI(azure_endpoint=s.azure_endpoint, api_key=s.azure_api_key,
                                  api_version=s.azure_api_version, max_retries=6, timeout=60)
        self.deployment = s.embed_deployment
        self.dimensions = s.embed_dimensions
        self.batch_size = s.embed_batch_size
        self.model_id = f"azure:{s.embed_deployment}:{s.embed_dimensions or 'default'}"

    def _embed(self, texts: list[str]) -> list[list[float]]:
        kwargs = {"dimensions": self.dimensions} if self.dimensions else {}
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            resp = self.client.embeddings.create(model=self.deployment, input=texts[i:i + self.batch_size], **kwargs)
            out.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


# --------------------------------------------------------------------------- cache
class CachedEmbedder:
    """Wraps a dense embedder with a SQLite cache keyed by (model id, text hash)."""

    def __init__(self, inner: DenseEmbedder, path: Path) -> None:
        self.inner = inner
        self.model_id = inner.model_id
        path.parent.mkdir(parents=True, exist_ok=True)
        # Shared across threads (e.g. parallel answer generation in evals), guarded by a lock.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS emb (key TEXT PRIMARY KEY, vec BLOB)")
        self.lock = threading.Lock()
        self.hits = self.misses = 0

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model_id}\n{text}".encode()).hexdigest()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        keys = [self._key(t) for t in texts]
        found: dict[str, list[float]] = {}
        with self.lock:
            for k in keys:
                row = self.db.execute("SELECT vec FROM emb WHERE key = ?", (k,)).fetchone()
                if row:
                    found[k] = array("f", row[0]).tolist()
            missing = [(k, t) for k, t in zip(keys, texts) if k not in found]
            self.hits += len(texts) - len(missing)
            self.misses += len(missing)
        if missing:
            vecs = self.inner.embed_documents([t for _, t in missing])  # network call outside the lock
            with self.lock:
                self.db.executemany("INSERT OR REPLACE INTO emb VALUES (?, ?)",
                                    [(k, array("f", v).tobytes()) for (k, _), v in zip(missing, vecs)])
                self.db.commit()
            found.update({k: v for (k, _), v in zip(missing, vecs)})
        return [found[k] for k in keys]

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed_query(text)


# --------------------------------------------------------------------------- sparse (BM25)
class BM25Embedder:
    def __init__(self, model_name: str = "Qdrant/bm25", cache_dir: Path | None = None) -> None:
        from fastembed import SparseTextEmbedding

        cache_dir = cache_dir or Path(__file__).resolve().parent / ".cache" / "fastembed"
        self.model = SparseTextEmbedding(model_name=model_name, cache_dir=str(cache_dir))

    @staticmethod
    def _to_qdrant(e) -> models.SparseVector:
        return models.SparseVector(indices=e.indices.tolist(), values=e.values.tolist())

    def embed_documents(self, texts: Iterable[str]) -> list[models.SparseVector]:
        return [self._to_qdrant(e) for e in self.model.embed(list(texts))]

    def embed_query(self, text: str) -> models.SparseVector:
        # query_embed gives each term weight 1; Qdrant's IDF modifier does the weighting.
        return self._to_qdrant(next(iter(self.model.query_embed(text))))


def build_dense_embedder(s: Settings) -> CachedEmbedder:
    return CachedEmbedder(AzureOpenAIEmbedder(s), s.embedding_cache)
