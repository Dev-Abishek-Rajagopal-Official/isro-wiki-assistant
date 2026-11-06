"""Settings for building the knowledge base. Values come from environment variables / a .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")


def _int_or_none(value: str | None) -> int | None:
    return int(value) if value else None


@dataclass(frozen=True)
class Settings:
    # Azure OpenAI (dense embeddings)
    azure_endpoint: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    azure_api_key: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    azure_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    embed_deployment: str = os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT", "text-embedding-3-large")
    # Optional: shorten text-embedding-3 vectors (e.g. 1024). Empty = model default (3072 for -large).
    embed_dimensions: int | None = _int_or_none(os.getenv("EMBED_DIMENSIONS"))
    embed_batch_size: int = int(os.getenv("EMBED_BATCH_SIZE", "64"))

    # Sparse (BM25) vectors, computed locally
    sparse_model: str = os.getenv("SPARSE_MODEL", "Qdrant/bm25")
    model_cache: Path = HERE / ".cache" / "fastembed"   # not Windows Temp, which gets cleaned

    # Qdrant
    qdrant_url: str = os.getenv("QDRANT_URL", "")            # empty = local mode
    qdrant_api_key: str = os.getenv("QDRANT_API_KEY", "")
    qdrant_path: Path = HERE / os.getenv("QDRANT_PATH", "qdrant_data")
    chunks_collection: str = os.getenv("CHUNKS_COLLECTION", "isro_chunks")
    parents_collection: str = os.getenv("PARENTS_COLLECTION", "isro_parents")

    # Files
    data_dir: Path = HERE / "data"
    embedding_cache: Path = HERE / "data" / "embedding_cache.sqlite"


def get_settings() -> Settings:
    return Settings()
