# Prerequisites – `isro rag` (building the knowledge base)

Scope of this folder: turn the cleaned Wikipedia documents into a searchable Qdrant collection.

```
wiki documents/*.md  ->  chunking.py  ->  data/chunks.jsonl  ->  indexing (embed + load)  ->  Qdrant
```

The agent (LLM, API, guardrails, UI) lives in a separate folder later and queries Qdrant directly.

Status checked on this machine on 2026-11-05 (Windows 11).

## 1. Software

| Tool | Needed for | Version | Status here |
|---|---|---|---|
| Python + venv | chunking, embedding, indexing | 3.11+ | ✅ 3.13.5 (`.venv` in `New Page Assignment\`) |
| WSL 2 | required by Docker Desktop | – | ❌ not installed: `wsl --install --no-distribution` (admin, then restart) |
| Docker Desktop | Qdrant server + web dashboard (`docker compose up -d`, see `docker-compose.yml`) | 4.x | ❌ not installed: `winget install -e --id Docker.DockerDesktop`. Without it, Qdrant runs in **local mode** (no dashboard) |
| Git | version control | 2.40+ | ❌ not installed: https://git-scm.com/download/win |

## 2. Python packages (`requirements.txt`)

| Package | Used for |
|---|---|
| `qdrant-client` | creating the collections, uploading chunks, test queries (local mode or server) |
| `openai` | Azure OpenAI client for the **dense** embeddings (`text-embedding-3-large`) |
| `fastembed` | **BM25 sparse** vectors (`Qdrant/bm25`), computed locally on CPU, no API |
| `python-dotenv` | loads `.env` |
| `pytest` | unit tests (use a fake dense embedder + in-memory Qdrant, so no Azure keys needed) |

`fastembed` downloads the small BM25 tokenizer files on first use into `isro rag/.cache/`, so the first run needs internet.

## 2b. Azure OpenAI embedding deployment

- An Azure OpenAI / Azure AI Foundry resource with a **`text-embedding-3-large` deployment**.
- Copy `.env.example` to `.env` and fill in `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`
  and `AZURE_OPENAI_EMBED_DEPLOYMENT` (the deployment name, which may differ from the model name).
- Cost: the whole corpus is ~0.7M tokens, i.e. cents. Embeddings are cached in
  `data/embedding_cache.sqlite`, so re-indexing only embeds chunks whose text changed.

## 3. Input data

- `isro agent/wiki documents/` – 468 cleaned Markdown articles + `wiki_metadata.csv`
  (produced by `wiki_clean download/wiki_clean_download.py`).
- Licence: Wikipedia content is **CC BY-SA 4.0** – chunks keep the article URL and revision id for attribution.

## 4. Machine resources

- ~500 MB free disk (Qdrant data + embedding cache).
- RAM: ~3.7k chunks × 3072-dim vectors ≈ 45 MB; an 8 GB machine is plenty.
- No GPU needed.

## 5. Configuration

| Variable | Meaning |
|---|---|
| `QDRANT_URL` | empty = local mode (`./qdrant_data`); e.g. `http://localhost:6333` for Docker |
| `QDRANT_API_KEY` | only for Qdrant Cloud |
