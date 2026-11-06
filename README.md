# ISRO Assistant – chat with the Indian space programme

A full-stack, multi-agent RAG assistant over **468 English Wikipedia articles about ISRO** plus three live
space-data sources. Ask by text or voice; watch every agent step live; open any step to see exactly what each
LLM, tool, API and retrieved passage returned; every answer cites its sources.

![Answer with live steps and citations](docs/screenshots/04-answer-citations.jpg)

**Contents** – [Tech stack](#tech-stack) · [Prerequisites](#prerequisites) · [Quick start](#quick-start) ·
[Using the app](#using-the-app-step-by-step) · [Admin consoles](#admin-consoles-qdrant-pgadmin-api-docs) ·
[Architecture](#architecture) · [Agent workflow](#agent-workflow) · [Knowledge base & RAG](#knowledge-base--rag) ·
[MCP & transport](#mcp-servers-and-transport) · [AI Foundry & guardrails](#microsoft-azure-ai-foundry-and-guardrails) ·
[RAG / LLM decisions](#rag--llm-decisions) · [Backend](#backend-api) · [Frontend](#frontend) ·
[Path to production](#path-to-production-azure) · [Engineering standards](#engineering-standards) ·
[Testing](#testing) · [AI tools](#how-ai-tools-were-used) · [More time](#what-i-would-do-with-more-time) ·
[Repository layout](#repository-layout) · [Credits](#credits-and-licence)

---

## What it does

| | |
|---|---|
| **Grounded answers** | Wikipedia knowledge base in Qdrant (hybrid dense + BM25), answers cite `[1] [2]` with links to the article section |
| **Live data** | upcoming / past launches (Launch Library 2), structured facts (Wikidata), "is it still in orbit?" (CelesTrak) |
| **Multi-agent** | a LangGraph router picks one or more specialist agents per question, then a final agent writes one answer |
| **Transparent** | every step streams to the UI; a drawer shows tool arguments, raw results, retrieved chunks with scores, every LLM call with tokens and latency, and the AgentState changes |
| **Voice** | record a question in the browser; Azure Speech transcribes it with a phrase list of ISRO names |
| **Conversations** | many conversations, each with several threads (separate agent memory), LLM-generated titles, full history with an AgentState timeline |
| **Accounts & usage** | JWT login, per-user usage (questions, latency, tokens by day / model / role / agent), admin analytics for the admin account |
| **Guardrails** | answers only from sources; out-of-scope questions get "not in my sources" (e.g. NASA's Apollo is deliberately not in the corpus) |

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript (strict), Vite 7, Tailwind CSS v4, Redux Toolkit + RTK Query, React Router 7, react-markdown, Recharts, lucide-react; served by nginx 1.27 |
| API | Python 3.13, FastAPI, Uvicorn, WebSockets, SQLAlchemy 2 (async, psycopg 3), Alembic, Pydantic v2 / pydantic-settings, PyJWT, argon2-cffi, redis-py |
| Agent | LangGraph (StateGraph + `AsyncPostgresSaver` checkpointer), LangChain OpenAI client, langchain-mcp-adapters |
| Tools | MCP servers built with FastMCP 3 (MCP SDK 1.x), streamable HTTP transport, httpx with an SQLite response cache |
| Knowledge base | Qdrant 1.20 (named dense + sparse vectors, RRF fusion), fastembed BM25, Azure OpenAI `text-embedding-3-large` |
| AI platform | **Microsoft Azure AI Foundry**: chat model `gpt-6-luna` (every agent role), embeddings, Azure AI Speech (Fast Transcription) |
| Evaluation | RAGAS 0.4, own retrieval A/B harness |
| Data | PostgreSQL 17 (users, conversations, runs, LLM calls, LangGraph checkpoints, agent event log), Redis 7 (tokens, caches, locks, pub/sub) |
| Ops | Docker + Docker Compose, uv (Python lock files), npm, pgAdmin 4 |

## Prerequisites

| Need | For | Notes |
|---|---|---|
| **Docker Desktop** (Windows / macOS) or Docker Engine + Compose v2 (Linux) | running everything | Windows needs WSL 2 (Docker Desktop installs it). ~6 GB disk for images, 4 GB+ RAM for Docker |
| **Azure AI Foundry resource** | LLM + embeddings | a chat model deployment (OpenAI v1-compatible endpoint, e.g. `gpt-6-luna`) and a `text-embedding-3-large` deployment |
| Azure AI Speech key (same Foundry / AI Services resource) | voice questions only | optional – text chat works without it |
| Internet access | Wikipedia (only with `WIKI_DOWNLOAD=true`), Launch Library 2, Wikidata, CelesTrak, model downloads | |
| Free ports | 3000, 8000, 5432, 6379, 6333, 5050 | change them in `.env` (`FRONTEND_PORT`, …) if taken |
| Git | cloning | |

Nothing else is needed on the host – Python, Node and every dependency run inside the containers. (For working
on one component outside Docker: Python 3.11+ with [uv](https://docs.astral.sh/uv/) and Node 22 – see each
folder's README.)

---

## Quick start

**You need:** Docker Desktop (or Docker Engine + Compose v2) and an Azure AI Foundry resource with a chat
model deployment and a `text-embedding-3-large` deployment (Azure Speech is optional – only for voice).

```bash
git clone https://github.com/Dev-Abishek-Rajagopal-Official/isro-wiki-assistant.git
cd isro-wiki-assistant
cp .env.example .env          # Windows: copy .env.example .env
# edit .env: LLM_BASE_URL, LLM_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY (+ SPEECH_* for voice)
```

Then run **one** script – it prepares everything and only returns when the whole system is healthy:

```powershell
.\setup.ps1                   # Windows (PowerShell)
```
```bash
./setup.sh                    # macOS / Linux / WSL
```

Open **http://localhost:3000**, create an account and ask a question.

![What the setup script does](docs/images/setup-flow.svg)

| Step | What happens |
|---|---|
| 1 | checks Docker is installed and running |
| 2 | creates `.env` if missing, **generates** the Postgres / Redis passwords and the JWT secret, stops early if the Azure settings are missing |
| 3 | builds the images: `rag`, `mcp`, `api` (Python + uv) and `frontend` (Node build → nginx) |
| 4 | starts Postgres, Redis and Qdrant and waits for their health checks |
| 5 | **Wikipedia articles** – only if `WIKI_DOWNLOAD=true` in `.env` (default **false**) or `-DownloadWiki` / `--download-wiki`: downloads articles not downloaded yet. Either way it then **verifies every article listed in `wiki_metadata.csv` is present** before going on. With `false` it uses the 468 articles committed in `wiki documents/` |
| 6 | builds the knowledge base: chunk → embed → index into Qdrant → verify the point counts and run a test query. Skipped when Qdrant already holds exactly these chunks (`-Reindex` / `--reindex` forces it) |
| 7 | starts the MCP servers, the API (runs the database migrations), the frontend and pgAdmin, waiting for each health check |
| 8 | polls `/api/health` until database, Redis, agent, MCP servers, Qdrant, LLM and Speech all report OK, then prints the URLs |

Re-running is safe and fast: nothing finished is redone (embeddings are cached, the index is fingerprinted).

| URL | What |
|---|---|
| http://localhost:3000 | the app |
| http://localhost:8000/docs | API (OpenAPI / Swagger) |
| http://localhost:6333/dashboard | Qdrant dashboard |
| http://localhost:5050 | pgAdmin (server "isro-postgres" pre-registered, no password prompt) |
| http://localhost:8101/mcp … 8104/mcp | the MCP servers (localhost only) – usable from any MCP client, e.g. Claude Desktop or an IDE |

**Admin account.** Emails listed in `ADMIN_EMAILS` are reserved – they cannot sign up through the app (there is
no email verification, so anyone could otherwise claim the admin address). Create it from the command line and
choose its password at the prompt (at least 8 characters, letters and digits):

```bash
docker compose exec api .venv/bin/python scripts/create_admin.py
```

**Stop / reset:** `docker compose stop` (data kept) · `docker compose down -v` (removes containers and data).

---

## Using the app, step by step

All screenshots below come from the running stack with real answers; they are produced by
[`docs/capture_screenshots.py`](docs/capture_screenshots.py), a Playwright walkthrough that also works as an
end-to-end smoke test (`pip install playwright`, then run it with the demo and admin credentials in env vars).

### 1. Create an account and sign in
![Sign up](docs/screenshots/01-sign-up.jpg)

Sign up with a name, email and password (≥ 8 characters with letters and digits). Sessions last 8 hours and
renew silently for 7 days.

### 2. Ask a question – or pick a suggestion
![Welcome screen](docs/screenshots/02-welcome.jpg)

Type a question, press the microphone to ask by voice, or click a suggestion. A new conversation is created
and named automatically by an LLM from your first question.

### 3. Watch the agents work
![Live steps](docs/screenshots/03-live-steps.jpg)

Each step appears as it happens: the router's decision, the agent that is running, the tool it called and a
one-line summary of the result ("5 passages found · 1.9 s"). The answer then streams in token by token.

### 4. Read the answer and its sources
![Answer with citations](docs/screenshots/04-answer-citations.jpg)

Citations `[1]` link to the source list; the chips under the answer open the exact Wikipedia section or data
source. The footer shows the time, tokens and agents used.

### 5. Open any step to see everything it did
![Step drawer – tool calls](docs/screenshots/05-step-tool-calls.jpg)

Clicking a step opens a side panel. **Tool calls** shows the arguments the agent sent and what came back – for
the knowledge base the retrieved chunks with their breadcrumb and score; for live sources the API data as a
table.

![Step drawer – LLM calls](docs/screenshots/06-step-llm-calls.jpg)

**LLM calls** lists every model call of that step (rewriter, generator …) with model, input / output /
reasoning tokens and latency. **Findings** shows what the agent reported to the router, **State changes** the
exact AgentState update.

### 6. Run details
![Run details](docs/screenshots/07-run-details.jpg)

"Run details" summarises one question: total time, LLM calls, tokens per LLM role and the thread's running total.

### 7. Multi-agent questions and follow-ups
![Multi-agent follow-up](docs/screenshots/08-multi-agent.jpg)

Follow-ups keep the thread's memory ("it", "that satellite"). Questions that need several sources go through
several agents – here the knowledge base for the launch and CelesTrak for the current orbit.

### 8. Ask by voice
![Voice question](docs/screenshots/08a-voice-question.jpg)

Press the microphone, speak, press it again. The browser records 16 kHz WAV; Azure AI Speech (Fast
Transcription, with a phrase list of ISRO names so "Cartosat-3" is not heard as "Cardasat") turns it into text –
shown as the first step, "Speech to text" – and the question runs like a typed one. Silent or very short
recordings are caught in the browser with a hint to check the microphone.

### 9. Bigger questions: several agents, tables, run details
![Three agents](docs/screenshots/08b-three-agents.jpg)

"List all ISRO launches from 2021 till today" needs the knowledge base, Launch Library 2 and Wikidata – the
router calls them one after another, each agent's tool calls (green = data, amber = empty / retried) are visible.

![Launch table](docs/screenshots/08c-launch-table.jpg)

The final answer merges them into a table with a citation on every row.

![Run details – summary](docs/screenshots/08d-run-details-summary.jpg)

Run details: time, LLM calls and tokens per role (router, each rewriter and generator, final), plus the thread total.

![Run details – AgentState](docs/screenshots/08e-run-details-agentstate.jpg)

The AgentState after the run – the router's last decision, every agent's findings, sources, hop count –
with the keys changed by the latest update highlighted.

### 10. Out-of-scope questions are refused
![Out of scope](docs/screenshots/09-out-of-scope.jpg)

The corpus is only about the Indian space programme. Questions it cannot support get a clear "not in my
sources" instead of an answer from the model's own memory.

### 11. Conversations and threads
![Sidebar](docs/screenshots/10-sidebar.jpg)

The sidebar lists the 10 most recent conversations ("Load more" pages further). Each conversation can hold
several threads – independent agent memories – and can be renamed or archived.

### 12. History and the AgentState timeline
![History – steps](docs/screenshots/11-history-steps.jpg)

History replays any past question with the same steps and drawer as when it ran live.

![History – AgentState timeline](docs/screenshots/12-history-agentstate.jpg)

The AgentState timeline steps through the LangGraph checkpoints of the thread; keys changed since the previous
snapshot are highlighted.

### 13. Your usage
![Usage](docs/screenshots/13-usage.jpg)

Questions (and how many by voice), success rate, typical answer time and tokens.

![Usage by LLM role](docs/screenshots/13b-usage-by-role.jpg)

Tokens can be grouped by day, LLM role, agent, model or conversation – here by role, which shows where the
tokens go (generators and the router read the most context).

### 14. Admin analytics (admin account only)
![Admin overview](docs/screenshots/14-admin-overview.jpg)

Only accounts in `ADMIN_EMAILS` see the Admin tab (everyone else gets 404 from the admin API). Overview:
users, questions, error rate, answer time p50 / p95, tokens, and the Azure rate-limit headroom.

![Admin – agents and routes](docs/screenshots/15-admin-agents.jpg)

Which agents are used, the most common routes through the graph and their latency.

![Admin – tools](docs/screenshots/16-admin-tools.jpg)

Every MCP tool: calls, failures, empty results, average duration.

![Admin – users](docs/screenshots/17-admin-users.jpg)

Per-user activity with a drawer of each user's usage.

![Admin – system](docs/screenshots/18-admin-system.jpg)

Live health of every dependency.

### 15. On a phone
![Mobile](docs/screenshots/19-mobile.jpg)

The layout works down to phone width; the sidebar becomes a slide-over.

---

## Admin consoles (Qdrant, pgAdmin, API docs)

The stack also exposes the tools used to inspect and debug it.

**Qdrant dashboard** – http://localhost:6333/dashboard: the `isro_chunks` collection (dense + BM25 vectors per
chunk, payload with breadcrumb, URL, revision id) and `isro_parents`.

![Qdrant collections](docs/screenshots/20-qdrant-collections.jpg)

![Qdrant point](docs/screenshots/21-qdrant-point.jpg)

**pgAdmin** – http://localhost:5050: the server "isro-postgres" is pre-registered and connects without a
password prompt (the stack mounts a generated pgpass file built from `POSTGRES_PASSWORD`). Tables: `users`, `conversations`, `threads`, `runs`, `llm_calls`, `agent_events` and the LangGraph
`checkpoints*` tables.

![pgAdmin tables](docs/screenshots/22-pgadmin.jpg)

**API docs** – http://localhost:8000/docs: every REST endpoint with schemas (OpenAPI / Swagger UI).

![API docs](docs/screenshots/23-api-docs.jpg)

**Containers** – `docker compose ps` shows every service and its health (output after `setup.ps1`):

```
SERVICE    IMAGE                  STATUS                  PORTS
api        isro-assistant/api     Up (healthy)            0.0.0.0:8000->8000/tcp
frontend   isro-assistant/frontend Up (healthy)           0.0.0.0:3000->80/tcp
mcp        isro-assistant/mcp     Up (healthy)            (internal 8101-8104)
pgadmin    dpage/pgadmin4:9.8     Up                      0.0.0.0:5050->80/tcp
postgres   postgres:17.6          Up (healthy)            0.0.0.0:5432->5432/tcp
qdrant     qdrant/qdrant:v1.20.0  Up (healthy)            0.0.0.0:6333->6333/tcp
redis      redis:7.4-alpine       Up (healthy)            0.0.0.0:6379->6379/tcp
```

And the end of the setup script's output:

```
[6/8] Building the knowledge base in Qdrant
OK: 468 documents, all present
468 documents -> 3703 chunks, 621 parents
OK: 3703 chunks + 621 parents indexed; test query top hit: Chandrayaan-3 > Mission profile > Launch
[8/8] Waiting until every dependency reports OK
  OK  database   OK  redis   OK  agent   OK  mcp_servers   OK  qdrant   OK  llm   OK  speech
ISRO assistant is ready.
```

---

## Architecture

![Architecture](docs/images/architecture.svg)

| Component | Folder | Role |
|---|---|---|
| Frontend | [`isro assistant frontend/`](isro%20assistant%20frontend/) | React 19 + TypeScript + Tailwind v4, Redux Toolkit + RTK Query; nginx in the container |
| API | [`isro api/`](isro%20api/) | FastAPI: auth, conversations / threads / runs, WebSocket streaming, usage, admin, health |
| Agent | [`isro agentic orchestration/`](isro%20agentic%20orchestration/) | LangGraph graph (router, 4 sub-agents, final), Postgres checkpointer + event log, Azure Speech |
| MCP servers | [`isromcp/`](isromcp/) | one FastMCP server per data source (knowledge base, Launch Library 2, Wikidata, CelesTrak) |
| Knowledge base | [`isro rag/`](isro%20rag/) | chunking, embeddings, Qdrant indexing, hybrid search, and the evaluation (`rag_evals/`) |
| Corpus | [`wiki documents/`](wiki%20documents/) | 468 cleaned articles + metadata CSV |
| Downloader | [`wiki_clean download/`](wiki_clean%20download/) | MediaWiki crawl + HTML → Markdown cleaning |
| Containers | [`docker/`](docker/), `docker-compose.yml`, `setup.ps1`, `setup.sh` | the whole stack in one command |

Request path: browser → nginx (`/api`) → FastAPI → LangGraph agent → MCP servers → Qdrant / public APIs, with
Azure AI Foundry for every LLM, embedding and transcription call. Live events go back over the WebSocket through
Redis pub/sub, so any API instance can serve any socket.

---

## Agent workflow

![Agent workflow](docs/images/agent-workflow.svg)

- **Router** – one LLM call per hop with structured output `{next_agent, task, reason}`; code-level guardrails:
  no agent twice, at most `MAX_HOPS` (5), anything invalid goes to the final agent.
- **Sub-agents** – the same three steps each: a **rewriter LLM** turns the task into a `ToolPlan` (tool calls
  with arguments), the **MCP tools** run (one retry with feedback if the result is empty), a **generator LLM**
  writes the findings from the tool data only, with source tags.
- **Final agent** – merges all findings into one answer with numbered citations, streamed token by token.
- **State** – `AgentState` holds the conversation, the router block, every agent's findings and sources, the
  hop count and token usage for the run and the thread. LangGraph checkpoints it in Postgres after every step;
  every event is also appended to `agent_events`, so the UI can replay any run exactly.
- **Separate LLM per role** – router, 4 rewriters, 4 generators, final and title each have a role name and can
  use their own model (`MODEL_<ROLE>`); every call is logged with tokens, latency and rate-limit headers.

---

## Knowledge base & RAG

![RAG pipeline](docs/images/rag-pipeline.svg)

### Methodology – and why

The corpus is encyclopaedic text with a lot of **structure**: a lead, nested sections, an infobox full of facts
(launch date, rocket, mass, orbit) and many tables (launch lists, payloads). Questions are mostly factual and
often name an exact identifier ("PSLV-C47", "GSAT-7A"). The methodology follows from that:

| Stage | What we do | Why |
|---|---|---|
| **Ingestion** | 7 root Wikipedia categories crawled to depth 3 → 487 titles → 468 articles. The *rendered* HTML is cleaned to Markdown: infobox → "Key facts" list, wikitables → Markdown tables. URL + revision id kept per article | plain-text extracts drop infoboxes and tables – exactly where most facts live |
| **Chunking** | structure-aware: split by section, ~350-token chunks, Key facts and tables kept as their own chunks (large tables repeat their header), tiny chunks merged into neighbours, parent sections stored | a chunk should answer one thing; a fixed window cuts tables and mixes sections |
| **Breadcrumb** | every chunk is embedded as `Article > Section` + text | a Key-facts or table chunk often never names its subject ("Launch mass: 1,625 kg") – the breadcrumb tells the retriever whose facts these are |
| **Dense + sparse** | dense `text-embedding-3-large` for meaning, BM25 for exact terms, both stored on the same Qdrant point | semantic search misses exact ids; keyword search misses paraphrases – each covers the other's gap |
| **Fusion** | 30 dense + 30 BM25 candidates → Reciprocal Rank Fusion in Qdrant → top 5 | rank-based fusion needs no score calibration; one query, ~15–30 ms |
| **No reranker** | – | measured slower and not better (below) |
| **Out-of-scope guard** | prompt rule (answer only from sources, fixed refusal) + best dense score < 0.5 → `likely_in_corpus: false` | LLMs know Wikipedia and would otherwise answer from memory |

### How the configuration was chosen – A/B test and RAGAS

Everything was measured before choosing (`isro rag/rag_evals`):

1. **Eval set** – gpt-6-luna generated 60 questions from sampled passages (33 prose, 15 Key facts, 12 tables),
   each with the **verbatim evidence sentence** it must be answered from (checked automatically), plus 5
   out-of-scope questions (e.g. NASA Apollo).
2. **Chunking variants** – the same corpus indexed five ways: structure-aware 200 / 350 / 600 tokens, 350
   *without* breadcrumb, and a naive fixed 400-token window with 60-token overlap.
3. **Retrieval A/B (no LLM, free, ~1 min)** – every variant × dense / BM25 / hybrid, plus two rerankers; a hit
   means the evidence sentence is inside the retrieved chunks.
4. **RAGAS end-to-end** – gpt-6-luna answers from the retrieved context and RAGAS (gpt-6-luna as judge) scores
   answer accuracy, faithfulness, context recall, answer relevancy; also refusal of out-of-scope questions.
   Compared with a **no-RAG baseline** to prove retrieval matters.

**Chunk size and method (Recall@5 = evidence in the top 5 chunks, 60 questions):**

| Variant | Chunks | Dense | BM25 | **Hybrid** | Context tokens (hybrid) |
|---|---|---|---|---|---|
| **struct_350 (chosen)** | 3,703 | 0.93 | 0.88 | **0.98** | **956** |
| struct_600 | 2,872 | 0.97 | 0.88 | 0.98 | 1,260 |
| struct_200 | 4,997 | 0.97 | 0.88 | 0.95 | 727 |
| fixed_400 (naive window) | 2,156 | 0.93 | 0.92 | 0.95 | 1,810 |
| struct_350 without breadcrumb | 3,703 | 0.68 | 0.70 | 0.75 | 1,023 |

**Rerankers (on top of hybrid):** MiniLM dropped struct_350 from 0.98 to 0.88 at 13 s/query on CPU;
bge-reranker-v2-m3 gained +3 points R@1 (within noise) at **43 s/query** – not worth it without a GPU.

**RAGAS end-to-end:**

| Pipeline | Answer accuracy | Faithfulness | Context recall | Answer relevancy | Out-of-scope refused | False refusals | Latency |
|---|---|---|---|---|---|---|---|
| No RAG (model memory) | 0.54 | – | – | 0.87 | **0%** | 5% | 3.7 s |
| **struct_350 · hybrid** | **0.88** | 0.99 | 1.00 | 0.91 | **100%** | 0% | 1.6 s |
| struct_600 · hybrid (20-question subset) | 0.82 | 1.00 | 1.00 | 0.88 | 100% | 0% | 2.0 s |

On the same 20 questions struct_350 and struct_600 tie (0.81 vs 0.82 answer accuracy).

**Result:** structure-aware ~350-token chunks with breadcrumb and hybrid search – the same recall as 600-token
chunks with **24% less context** and faster answers, far better than a naive window, and +34 points answer
accuracy over the model alone. The breadcrumb was the single largest effect (0.75 → 0.98).

Caveats: 60 synthetic questions (≈ ±10 points at 95%), and the same model generated, answered and judged. Full
tables: [`REPORT.md`](isro%20rag/rag_evals/results/REPORT.md) · interpretation:
[`CONCLUSIONS.md`](isro%20rag/rag_evals/results/CONCLUSIONS.md).

---

## MCP servers and transport

Each external source is its own **MCP server** ([`isromcp/`](isromcp/)), so the sources stay independent,
testable and reusable by any MCP client (Claude Desktop, IDEs, other agents) – not only this app.

| Server | Port | Tools | Source |
|---|---|---|---|
| `isro_knowledge_base` | 8101 | `search_isro_documents`, `get_section_context` | our Qdrant knowledge base (hybrid search above) |
| `launch_library` | 8102 | `upcoming_isro_launches`, `recent_isro_launches`, `search_launches`, `launch_details` | Launch Library 2 (The Space Devs) |
| `wikidata` | 8103 | `find_wikidata_entity`, `get_space_object_facts`, `list_isro_missions` | Wikidata SPARQL |
| `celestrak` | 8104 | `search_satellites`, `get_satellite`, `get_orbital_elements` | CelesTrak SATCAT + orbital elements |

**Transport: streamable HTTP.** All four servers run in the `mcp` container and the agent connects with
`langchain-mcp-adapters` (`MultiServerMCPClient`) at `http://mcp:<port>/mcp`. The servers also support **stdio**
(the MCP default, the client spawns the server as a subprocess) for standalone use, but HTTP was chosen because:

- the servers are **long-lived** – Qdrant / Azure clients and the BM25 model load once instead of per session;
- they **scale and deploy separately** from the API (own container, own health check) and can be shared by
  several API instances;
- on Windows, async psycopg needs the selector event loop, which cannot spawn stdio subprocesses, and the
  knowledge-base server hung over stdio – HTTP avoids both.

Every tool returns provenance (`source`, `source_url`, `fetched_at`, `from_cache`) so answers can cite it;
web responses are cached per tool (TTL) and the last good answer is served with a warning if an API fails or
rate-limits. Version note: FastMCP 3 + MCP SDK 1.x, because `langchain-mcp-adapters` requires `mcp<2`.

---

## Microsoft Azure AI Foundry and guardrails

All model calls go to one **Azure AI Foundry** resource:

| Use | Model / service | Called from |
|---|---|---|
| Router, 4 rewriters, 4 generators, final answer, conversation title | `gpt-6-luna` chat deployment (OpenAI v1-compatible endpoint) – overridable per role with `MODEL_<ROLE>` | agent + API |
| Dense embeddings | `text-embedding-3-large` deployment | knowledge-base build + search |
| Speech-to-text | Azure AI Speech Fast Transcription (phrase list of ISRO names) | agent (voice questions) |

**AI guardrails are controlled in Azure AI Foundry.** The deployments' guardrails – content filters (hate,
sexual, violence, self-harm), Prompt Shields against jailbreak and indirect prompt injection, protected-material
detection – are configured on the Foundry resource and applied to every request and response, with no code in
the app; changing a policy needs no redeploy. The application adds the **scope guardrails** on top: answer only
from retrieved sources with citations, fixed refusal for unsupported questions, the out-of-scope score threshold,
a hop limit in the router, and access control (JWT, per-user ownership, admin-only analytics).

Every Foundry call is recorded by the app (`llm_calls`: role, model, input / output / reasoning / cached tokens,
latency and the rate-limit headroom headers), which feeds the usage and admin dashboards.

---

## RAG / LLM decisions

| Area | Decision | Why |
|---|---|---|
| **LLM** | Azure AI Foundry, `gpt-6-luna` for every role (configurable per role) | one provider for chat, embeddings and speech; per-role settings allow a cheaper model for router / rewriters later |
| **Embeddings** | `text-embedding-3-large` (3072-d) | best recall in the evals; the whole corpus costs cents to embed |
| **Vector DB** | Qdrant 1.20 | native named dense + sparse vectors and server-side RRF fusion – hybrid search in one query; good dashboard; runs locally and in the cloud |
| **Orchestration** | LangGraph + langchain-mcp-adapters | explicit graph with a typed state, checkpointing for history and replay, streaming of updates / custom events / tokens |
| **Tools** | MCP (FastMCP), one server per source | sources are independent, reusable by any MCP client, testable on their own; HTTP transport keeps clients and models loaded |
| **Prompt & context** | rewriter prompts per source; generator sees only its tool results; final agent sees findings + numbered sources; today's date in every prompt; tool results compacted to 12 KB | small, focused contexts per call; dates matter for "next launch" questions |
| **Memory** | per-thread conversation memory in the LangGraph checkpointer | follow-ups resolve "it" / "that satellite"; a new thread starts fresh |
| **Guardrails** | answer only from sources with citations, fixed refusal sentence, dense-score threshold, router hop limit, JWT + ownership checks, admin endpoints hidden (404) | evals showed 100% out-of-scope refusal; Azure's built-in content filters apply to every LLM call |
| **Quality** | offline evals (retrieval A/B + RAGAS), unit and live tests per component | numbers above; regressions visible before shipping |
| **Observability** | every LLM call stored (`llm_calls`: role, model, tokens incl. reasoning / cached, latency, rate-limit headroom); every agent event stored; usage and admin dashboards built on them | own tracking instead of an external APM, as asked – no extra service to run |
| **Speech** | Azure Fast Transcription with a phrase list built from the corpus titles | without it "Cartosat-3" was transcribed as "Cardasat-3" |

---

## Backend (API)

FastAPI + SQLAlchemy 2 (async) + Alembic + PostgreSQL + Redis – details in [`isro api/README.md`](isro%20api/README.md).

- **Auth**: argon2id password hashes; JWT access token (8 h) + refresh token (7 days) **rotated on every use**;
  refresh tokens and revocations in Redis; logout and logout-everywhere.
- **Data model**: `users → conversations → threads → runs → llm_calls`; `threads.id` is the LangGraph thread id,
  so checkpoints and `agent_events` join to runs.
- **WebSocket `/ws`**: authenticate, ask (text or audio), subscribe with `after_id` to resume, cancel; events fan out
  through Redis pub/sub; one active run per thread (Redis lock); a run continues if the socket drops.
- **REST**: conversations (cursor paging), threads, runs, events, AgentState snapshots, usage, admin analytics, health.
- **Conversation titles** from a separate LLM role, generated once per conversation (Redis lock).

## Frontend

React 19 + TypeScript (strict) + Vite + Tailwind v4 – details in [`isro assistant frontend/README.md`](isro%20assistant%20frontend/README.md).

- **Redux Toolkit** for live runs (one reducer folds every streamed event into the run), UI and auth state;
  **RTK Query** caches every REST call with tags, infinite paging for conversations, cache invalidation driven by
  WebSocket events (new title, finished run → usage).
- **WebSocket client** with automatic reconnect, resume from the last event id and de-duplication.
- **Voice** recorded in the browser and encoded to 16 kHz mono WAV before upload.
- Access token only in memory; refresh token in localStorage with single-flight refresh.

---

## Path to production (Azure)

| Concern | Local (this repo) | Production on Azure |
|---|---|---|
| Containers | docker compose | **Azure Container Apps** (api, mcp, frontend) from **Azure Container Registry**; scale api on HTTP + WebSocket connections; or AKS at larger scale |
| Edge | nginx in the frontend container | **Azure Front Door** (TLS, WAF, CDN for static assets) → frontend; sticky sessions not needed (Redis pub/sub) |
| PostgreSQL | container | **Azure Database for PostgreSQL – Flexible Server** (HA, PITR backups) |
| Redis | container | **Azure Cache for Redis** |
| Vector DB | Qdrant container | **Qdrant Cloud on Azure** or Qdrant on AKS with persistent disks (alternative: Azure AI Search hybrid) |
| Secrets | `.env` | **Azure Key Vault** + managed identities (no keys in env); Entra ID auth to Azure OpenAI |
| LLM | one deployment | provisioned throughput or several regional deployments behind **API Management** (retries, quotas, failover) |
| Ingestion | setup job | scheduled **Container Apps job** (weekly wiki refresh → re-index only changed chunks) |
| Observability | own tables + dashboards | add OpenTelemetry → **Application Insights**; alerts on error rate, latency p95, token spend |
| Safety | Azure default content filters | **Azure AI Content Safety** on input and output, prompt-shield for injection in tool results |
| CI/CD | – | **GitHub Actions**: tests + retrieval eval on every PR, build and push images, deploy with Bicep / Terraform |
| Auth | own JWT | keep, or move to **Entra ID / External ID** for SSO and email verification |

Other targets map the same way (AWS: ECS Fargate, RDS, ElastiCache, Secrets Manager; GCP: Cloud Run, Cloud SQL,
Memorystore).

---

## Engineering standards

**Followed**
- One responsibility per folder; each component runs and tests on its own and has its own README.
- Typed code: Python type hints + Pydantic schemas; TypeScript strict mode.
- Docstrings on modules and public functions; comments explain *why*, not *what*.
- Configuration only from environment / `.env`; secrets never committed (`.gitignore`, `.dockerignore`), generated locally by the setup script.
- Dependencies pinned with lock files (`uv.lock`, `package-lock.json`); container images pinned to versions.
- Database schema through Alembic migrations; cursor (keyset) pagination; ownership checks return 404.
- Idempotent jobs: resumable download, fingerprinted indexing, cached embeddings, UUIDv5 point ids.
- Health checks on every container and a deep `/health` endpoint.
- Tests per component (see below), evaluation before choosing the RAG configuration.

**Skipped (time-boxed take-home)**
- CI pipeline (GitHub Actions) – the tests and the retrieval eval are ready to wire in.
- Linters / formatters enforced in CI (ruff, eslint) and pre-commit hooks.
- Load testing, rate limiting per user, email verification, password reset.
- A full end-to-end test suite in CI – the UI walkthrough below is scripted (`docs/capture_screenshots.py`,
  Playwright) and fails if any step breaks, but it runs locally against live Azure models, not in CI.
- Infrastructure as code for the cloud deployment.

---

## Testing

| Component | Command (inside the folder, after `uv sync` / `npm ci`) | Tests |
|---|---|---|
| Frontend | `npm test` (+ `npx tsc -b` type check) | 15 – event reducer, step builder, WAV encoder + silent-recording check, citation links, cited-source cards, error messages |
| UI walkthrough | `python docs/capture_screenshots.py` (stack running) | sign up → 3 live questions → drawer → history → usage → admin → mobile → consoles |
| API | `uv run pytest -q` | 19 – auth & token rotation, ownership, paging, usage, admin access, WebSocket protocol |
| Agent | `uv run pytest -q` | 24 – unit + live graph runs (live tests skip when services are down) |
| MCP servers | `uv run pytest -q` | 12 – every tool through a real MCP client |
| Knowledge base | `uv run pytest -q` | 18 – chunking + indexing with a fake embedder and in-memory Qdrant |

The API and agent tests use the running compose stack (Postgres, Redis, MCP servers on localhost) with their own
databases (`isro_agent_test`, `isro_orchestrator`), reading the credentials from the root `.env`; the agent's
live tests skip themselves when the stack is down.

---

## How AI tools were used

I used Claude Code as a pair programmer throughout: exploring the MediaWiki and space-data APIs, drafting code
for each component, writing tests, running the evaluations and debugging (for example the Windows event-loop
issue with async psycopg, the FastMCP / MCP SDK version conflict, and RAGAS rate limits). Design decisions –
the corpus, structure-aware chunking, hybrid search without a reranker, one MCP server per source, the router +
specialist-agent graph, own observability instead of an APM – were made by me and checked against the eval
numbers and live tests. Every feature was verified by running it.

## What I would do with more time

- CI with GitHub Actions: unit tests, the retrieval A/B (free, ~1 min) and a small RAGAS gate on every PR.
- A larger, hand-written and multi-hop eval set, and a different judge model than the generator.
- Azure AI Content Safety on input / output and prompt-injection screening of tool results.
- A cheaper model for router and rewriters, chosen by the per-role cost / latency data already collected.
- Shared conversations between users; email verification and password reset.
- Scheduled wiki refresh with change detection by revision id.
- Playwright end-to-end tests and a Bicep / Terraform deployment to Azure Container Apps.

---

## Repository layout

```
.
├── setup.ps1 / setup.sh          one-command setup (Windows / macOS-Linux)
├── docker-compose.yml            the whole stack + jobs (wiki, ingest)
├── .env.example                  every setting, documented
├── docker/                       Python image recipe
├── docs/images, docs/screenshots diagrams and UI screenshots used in this README
├── wiki_clean download/          Wikipedia crawler + cleaner
├── wiki documents/               468 articles (Markdown + front matter) + metadata CSV
├── isro rag/                     chunking, embeddings, Qdrant index, hybrid search, rag_evals/
├── isromcp/                      4 FastMCP servers
├── isro agentic orchestration/   LangGraph agent, speech, event log
├── isro api/                     FastAPI backend
└── isro assistant frontend/      React app
```

## Credits and licence

Article text from [Wikipedia](https://en.wikipedia.org/), © Wikipedia contributors, licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); each document keeps its source URL and
revision id. Live data: [Launch Library 2](https://thespacedevs.com/llapi) (The Space Devs),
[Wikidata](https://www.wikidata.org/) (CC0), [CelesTrak](https://celestrak.org/).
