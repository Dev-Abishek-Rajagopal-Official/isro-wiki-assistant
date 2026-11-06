# Project notes – ISRO Wikipedia RAG (what we did, and how we got the results)

Working notes for the Newpage FDE assignment (Option 1 – Chat With Your Docs). Dates: 5–6 Nov 2026.
These are my working notes, not the README.

---

## 1. Data: which articles, and how many

**Goal:** an English-Wikipedia corpus about ISRO / the Indian space programme.

- Source: the free MediaWiki API, walking these root categories and their subcategories:
  Indian Space Research Organisation, Space programme of India, ISRO satellites, Satellites of India,
  Earth observation satellites of India, Space launch vehicles of India, ISRO facilities.
- Off-topic subcategories skipped (births, deaths, alumni, stubs, images, templates…).
- **How deep to go:** dry runs at different category depths:

  | Depth | Categories | Unique articles |
  |---|---|---|
  | 1 | 26 | 297 |
  | 2 | 42 | 458 |
  | 3 | 60 | 487 |
  | 4, 5, 10 | 60 | 487 |

  The tree stops growing at depth 3 (the deepest level ever reached is 3), so **depth 3 = the whole tree**.
  More articles would need more root categories, not more depth.
- Excluded by hand: `SpaceX Crew-12` (appears in "Spacecraft launched by India in 2026" but is not about ISRO).

## 2. Download + cleaning (`wiki_clean download/wiki_clean_download.py`)

**Tested on 10 sample articles first** (Chandrayaan-3, PSLV, Vikram Sarabhai, GSAT-7, SDSC, Gaganyaan,
Mars Orbiter Mission, IRNSS-1A, Aditya-L1, Cartosat-2) to decide the cleaning approach:

- The plain-text extract API **drops infoboxes and tables**. All 10 samples had an infobox (mass, launch
  date, rocket, orbit, COSPAR id…) and several had 4–5 tables (launch histories). For a satellite stub
  that is about half of the facts.
- **Decision:** fetch the rendered HTML (`action=parse`) and convert to Markdown myself:
  - infobox → `## Key facts` list (`- Launch mass: 1,425 kilograms`), placed after the lead
  - wikitables → Markdown tables (rowspan repeated down; colspan only in the first column)
  - removed: citation markers, edit links, navboxes, hatnotes, maintenance banners, images, hidden
    microformat text, "See also / References / External links…" sections, empty sections
  - one `.md` per article with a front-matter header (title, url, pageid, revid, last edited, short
    description, Wikidata id, categories, TF-IDF keywords, licence)
- Writes **one article at a time** (low memory, resumable), then a second pass adds TF-IDF keywords.
- `wiki_metadata.csv`: one row per article (name, link, keywords, categories, ids, word/char counts,
  sections, infobox yes/no, table count, licence).

**Result:** 468 articles saved (15 duplicates via redirects, 3 too short), ~486k words, 417 with Key facts,
188 tables. Licence: CC BY-SA 4.0 (URLs + revision ids kept for attribution).

**Fix found later (from chunk statistics):** cells spanning several columns were copied into every column
(e.g. a GSLV notes row repeated 8×), and line breaks inside table cells / infobox values split rows.
Fixed in the converter and re-downloaded. Lesson: cache raw HTML so cleaning fixes don't need a re-download.

## 3. Chunking design (`isro rag/chunking.py`)

Measured the corpus before choosing (≈ tokens): median article 796; median leaf section **147**
(p90 446, max 28k); 984 sections under 100 tokens; tables median 78, max 12.5k.

→ Classic parent-child (tiny children, big parents) adds little when most sections are already ~150 tokens.
**Chosen: structure-aware chunking with limited parent expansion.**

- Prose packed per top-level section, paragraph by paragraph (~350 tokens target, 450 max);
  long sections split at paragraphs/sentences; tiny neighbouring sections merged (sub-headings kept inline).
- `Key facts` → one `facts` chunk. Tables → one `table` chunk or row groups that **repeat caption + header**.
- Every chunk carries a **breadcrumb** (`Article > Section > Subsection`) prepended before embedding.
- Parents (the `##` section, or the whole article if short) stored separately, not embedded, capped at
  1,500 tokens; children keep `parent_id`, `prev_id`, `next_id`.
- Result: **3,703 chunks** (text median 181, facts 130, tables 243 tokens; none above ~500) and 621 parents.

## 4. Vector DB + embeddings (`isro rag/index.py`, `embeddings.py`, `search.py`)

- **Qdrant** chosen: dense + sparse (BM25) vectors on the same point, fused in one query (RRF), payload
  filters for citations, local mode for tests, Docker for the server/dashboard, same API on Qdrant Cloud.
- **Dense:** Azure OpenAI `text-embedding-3-large` (3,072 dims) via Azure AI Foundry.
  **Sparse:** BM25 from fastembed (`Qdrant/bm25`), computed locally – Qdrant applies IDF (`Modifier.IDF`).
  (An embedding model does not produce BM25; BM25 is a word-count formula.)
- Embeddings cached in SQLite → re-indexing costs nothing unless chunk text changes.
- Collections: `isro_chunks` (3,703 points) and `isro_parents` (621, no vectors).
- Qdrant runs in Docker (`docker-compose.yml`, `qdrant/qdrant:v1.20.0`), dashboard at
  http://localhost:6333/dashboard. Needed WSL 2 + Docker Desktop installed first.
- Environment: `uv` project (`pyproject.toml` + `uv.lock`), secrets in `.env` (git-ignored).

## 5. Evaluation – how we found the best RAG (`isro rag/rag_evals/`)

### 5.1 Eval set (`build_dataset.py`)
- Questions generated from the **documents** (not from chunks), so every chunking variant is judged on the
  same questions.
- Passages sampled across all 468 articles (max one per content type per article), stratified by type.
- gpt-6-luna wrote, per passage: a self-contained question, a short reference answer, and a **verbatim
  evidence quote**. Items kept only if the quote is found verbatim in the passage (0 of 89 rejected).
- Out-of-scope questions added and checked to be absent from the corpus.
- **Final set: 60 in-scope (33 prose, 15 Key facts, 12 table) from 36 articles + 5 out-of-scope.**

### 5.2 Variants (`variants.py`, `build_variants.py`)
Each indexed over the **full corpus** into its own `eval_<variant>_*` collections:

| Variant | What it tests | Chunks |
|---|---|---|
| struct_350 | production config | 3,703 |
| struct_200 | smaller chunks | 4,997 |
| struct_600 | bigger chunks | 2,872 |
| struct_350_nocrumb | same chunks, no breadcrumb | 3,703 |
| fixed_400 | naive 400-token windows, 60 overlap | 2,156 |

### 5.3 Retrieval A/B (`retrieval_ab.py`) – no LLM, cheap
- Metric: **evidence recall@k** – is the verbatim evidence inside the top-k chunks? (fair across chunkings)
  plus MRR@10, right-article hit, context tokens, latency.
- Phase A: every variant × dense / BM25 / hybrid. Phase B: rerankers (MiniLM-L12, bge-reranker-v2-m3)
  ± parent expansion on the top-2 variants only.

Key numbers (60 questions):

| Pipeline | R@1 | R@5 | MRR | Context tokens | Latency |
|---|---|---|---|---|---|
| struct_350 · hybrid | 0.63 | **0.98** | 0.77 | **956** | 14 ms |
| struct_600 · hybrid | 0.65 | **0.98** | 0.79 | 1,260 | 30 ms |
| fixed_400 · hybrid | 0.67 | 0.95 | 0.79 | 1,810 | 29 ms |
| struct_200 · hybrid | 0.60 | 0.95 | 0.75 | 727 | 29 ms |
| struct_350 · dense / bm25 | 0.55 / 0.62 | 0.93 / 0.88 | 0.70 / 0.73 | ~950 | – |
| struct_350_nocrumb · hybrid | 0.42 | **0.75** | 0.56 | 1,023 | 30 ms |
| struct_600 · hybrid + MiniLM | 0.60 | 0.92 | 0.73 | 1,221 | 4,952 ms |
| struct_600 · hybrid + bge-m3 | 0.68 | 0.97 | 0.80 | 1,280 | **43,210 ms** |

### 5.4 End-to-end RAGAS (`ragas_eval.py`)
- gpt-6-luna generates (Responses API; answer only from numbered sources, cite [n], fixed refusal
  sentence) and judges (RAGAS 0.4.3): faithfulness, answer relevancy, context recall, factual correctness
  (recall mode), answer accuracy; plus out-of-scope refusal and false-refusal rates.

| Pipeline | Questions | Answer accuracy | Faithfulness | Context recall | OOS refused | False refusals | Latency |
|---|---|---|---|---|---|---|---|
| no RAG | 60 | 0.54 | – | – | 0% | 5% | 3.7 s |
| struct_350 · hybrid | 60 | **0.88** | 0.99 | 1.00 | 100% | 0% | 1.6 s |
| struct_600 · hybrid | 20 (stratified) | 0.82 | 1.00 | 1.00 | 100% | 0% | 2.0 s |

Same 20 questions for all three: answer accuracy no-RAG 0.54, struct_350 0.81, struct_600 0.82.

## 6. Result – the best RAG

**`struct_350 · hybrid` – structure-aware ~350-token chunks + breadcrumb, Azure `text-embedding-3-large`
+ BM25 fused with RRF in Qdrant, top 5, no reranker, no parent expansion** (= the production index).

Why:
1. Breadcrumb is essential (+23 points R@5; facts/tables need the article name).
2. Hybrid beats dense-only and BM25-only everywhere.
3. 350 ties 600 on quality with 24% less context and faster answers.
4. Rerankers on CPU: worse (MiniLM) or not significantly better (bge-m3) and 5–43 s per query.
5. RAG vs no RAG: answer accuracy 0.54 → 0.88, 0.99 faithfulness, refuses everything out of scope.
6. Guardrail signal: real questions' best dense score ≥ 0.51, out-of-scope ≤ 0.50 → threshold ≈ 0.5.

## 7. Problems hit along the way (and what we did)

| Problem | Fix |
|---|---|
| Extracts lost infoboxes/tables | switched to rendered HTML → Markdown |
| colspan duplication, line breaks in cells | fixed converter, re-downloaded (should have cached raw HTML) |
| First chunker run: oversize tables, 490 tiny chunks | header-repeating row groups, facts kept together, tiny-chunk merge |
| Tiny lead merged into a section lost the section's citation path | merged chunk keeps the receiving chunk's path |
| ragas 0.3.1 / 0.4.3 import error | pinned `langchain-community<0.4` |
| Responses API JSON mode needs the word "json" in the input | guard in the LLM wrapper |
| CPU rerankers 10–100 s per query → full grid 5+ h | phase A for all, rerankers only on top-2, 20 truncated candidates |
| RAGAS `factual_correctness` (F1) scored correct answers 0.0 | recall mode, citations stripped, added `answer_accuracy` |
| SQLite cache not thread-safe | shared connection + lock |
| 21 judge calls failed ("Connection error") at concurrency 32 | per-call retries with backoff, concurrency 12, failure count logged |
| 2 CSV rows misaligned after adding a column mid-run | re-aligned (backup `experiments.csv.bak`) |

All of this is also in `isro rag/rag_evals/results/experiments.log` (chronological) and `experiments.csv`.

## 8. Caveats

- 60 questions ≈ ±10 points (95%); small differences between top configs are not significant.
- Synthetic questions from the same model that generates and judges answers (possible bias).
- `factual_correctness` reads low (0.2–0.4) for all pipelines because of how RAGAS splits reference answers;
  `answer_accuracy` is the more reliable signal.
- Reranker test truncated candidates to ~300 tokens (may under-rate rerankers on long facts/table chunks).
- Only 5 out-of-scope questions.

## 9. Where things are

```
isro agent/
├── wiki documents/            468 cleaned .md + wiki_metadata.csv
├── wiki_clean download/       downloader / cleaner
└── isro rag/
    ├── chunking.py, embeddings.py, index.py, search.py, config.py
    ├── docker-compose.yml, pyproject.toml, .env (secrets, git-ignored)
    ├── data/                  chunks.jsonl, parents.jsonl, embedding cache
    └── rag_evals/             eval scripts + results/REPORT.md, experiments.csv/.log, details/
```

## 10. Next

- Agent phase (separate folder): hybrid top-5 retrieval from `isro_chunks`, refusal prompt + score
  threshold, citations (article + section + URL).
- Grow the eval set (~150, stratified by topic category, hand-written + multi-hop), run retrieval evals in CI.
- Rotate the Azure key (it was pasted in chat). Optionally delete the `eval_*` Qdrant collections.
