# RAG evaluation report

Eval set: 65 questions (types={'text': 33, 'facts': 15, 'table': 12, 'out_of_scope': 5}; rejected=0 of 89 generations; model=gpt-6-luna).

## 1. Chunking variants

| Variant | Chunks | Notes |
|---|---|---|
| struct_350 | 3703 | structure-aware, ~350-token children (production config); median_tokens=190, p90=312, max=495, parents=621, new_embeddings=0, cached=3703, seconds=67 |
| struct_200 | 4997 | structure-aware, ~200-token children; median_tokens=149, p90=219, max=495, parents=805, new_embeddings=2652, cached=2345, seconds=107 |
| struct_600 | 2872 | structure-aware, ~600-token children; median_tokens=197, p90=483, max=722, parents=568, new_embeddings=825, cached=2047, seconds=66 |
| struct_350_nocrumb | 3703 | as struct_350 but embedded WITHOUT the breadcrumb prefix; median_tokens=190, p90=312, max=495, parents=621, new_embeddings=3700, cached=3, seconds=127 |
| fixed_400 | 2156 | naive baseline: fixed ~400-token windows, 60 overlap, ignores structure; median_tokens=399, p90=400, max=400, parents=0, new_embeddings=2156, cached=0, seconds=119 |

## 2. Retrieval A/B (evidence sentence found in retrieved chunks; 60 in-scope questions)

| Variant + pipeline | R@1 | R@3 | **R@5** | R@10 | MRR@10 | Doc hit@5 | Context tokens | Latency ms |
|---|---|---|---|---|---|---|---|---|
| struct_600 · hybrid+rerank:bge-m3+parent | 0.68 | 0.88 | **0.98** | 1.00 | 0.80 | 1.00 | 2551 | 43210 |
| struct_600 · hybrid | 0.65 | 0.95 | **0.98** | 0.98 | 0.79 | 1.00 | 1260 | 30 |
| struct_350 · hybrid | 0.63 | 0.90 | **0.98** | 0.98 | 0.77 | 1.00 | 956 | 14 |
| struct_600 · hybrid+rerank:bge-m3 | 0.68 | 0.88 | **0.97** | 1.00 | 0.80 | 1.00 | 1280 | 43210 |
| struct_600 · dense | 0.58 | 0.87 | **0.97** | 0.98 | 0.73 | 1.00 | 1178 | 30 |
| struct_600 · hybrid+rerank:minilm+parent | 0.60 | 0.85 | **0.97** | 0.97 | 0.73 | 1.00 | 2577 | 4952 |
| struct_200 · dense | 0.52 | 0.88 | **0.97** | 0.98 | 0.70 | 1.00 | 703 | 35 |
| fixed_400 · hybrid | 0.67 | 0.90 | **0.95** | 1.00 | 0.79 | 1.00 | 1810 | 29 |
| struct_200 · hybrid | 0.60 | 0.92 | **0.95** | 1.00 | 0.75 | 1.00 | 727 | 29 |
| fixed_400 · dense | 0.60 | 0.87 | **0.93** | 0.97 | 0.73 | 0.98 | 1797 | 26 |
| struct_350 · dense | 0.55 | 0.85 | **0.93** | 0.97 | 0.70 | 0.98 | 925 | 435 |
| fixed_400 · bm25 | 0.68 | 0.83 | **0.92** | 0.97 | 0.78 | 0.97 | 1842 | 21 |
| struct_350 · hybrid+rerank:minilm+parent | 0.62 | 0.83 | **0.92** | 0.95 | 0.73 | 1.00 | 1914 | 13067 |
| struct_600 · hybrid+rerank:minilm | 0.60 | 0.85 | **0.92** | 0.97 | 0.73 | 1.00 | 1221 | 4952 |
| struct_350 · hybrid+rerank:minilm | 0.62 | 0.83 | **0.88** | 0.95 | 0.73 | 1.00 | 962 | 13067 |
| struct_350 · bm25 | 0.62 | 0.80 | **0.88** | 0.95 | 0.73 | 0.98 | 1030 | 14 |
| struct_600 · bm25 | 0.58 | 0.80 | **0.88** | 0.97 | 0.71 | 0.98 | 1339 | 21 |
| struct_200 · bm25 | 0.57 | 0.82 | **0.88** | 0.95 | 0.70 | 0.98 | 747 | 20 |
| struct_350_nocrumb · hybrid | 0.42 | 0.67 | **0.75** | 0.83 | 0.56 | 0.98 | 1023 | 30 |
| struct_350_nocrumb · bm25 | 0.47 | 0.62 | **0.70** | 0.73 | 0.55 | 0.90 | 1072 | 22 |
| struct_350_nocrumb · dense | 0.38 | 0.63 | **0.68** | 0.80 | 0.52 | 1.00 | 953 | 31 |

## 3. End-to-end RAGAS (generator + judge: gpt-6-luna)

| Pipeline | Questions | Answer accuracy | Factual correctness (recall) | Faithfulness | Context recall | Answer relevancy | OOS refused | False refusals | Answer latency s |
|---|---|---|---|---|---|---|---|---|---|
| norag | 60 + 5 OOS | 0.54 | 0.21 | – | – | 0.87 | 0.00 | 0.05 | 3.7 |
| struct_350 · hybrid | 60 + 5 OOS | 0.88 | 0.38 | 0.99 | 1.00 | 0.91 | 1.00 | 0.00 | 1.6 |
| struct_600 · hybrid | 20 + 5 OOS | 0.82 | 0.30 | 1.00 | 1.00 | 0.88 | 1.00 | 0.00 | 2.0 |

## 4. Same-question comparison (20 in-scope questions answered by every pipeline)

| Pipeline | answer_accuracy | factual_correctness | faithfulness | context_recall | answer_relevancy |
|---|---|---|---|---|---|
| norag | 0.54 | 0.25 | – | – | 0.85 |
| struct_350 · hybrid | 0.81 | 0.35 | 0.98 | 1.00 | 0.89 |
| struct_600 · hybrid | 0.82 | 0.30 | 1.00 | 1.00 | 0.88 |

Question ids: q001, q011, q012, q015, q016, q017, q020, q021, q025, q030, q031, q037, q041, q045, q046, q048, q049, q054, q056, q059

## 5. Conclusions – the best RAG for this corpus

**Winner: `struct_350 · hybrid` (no reranker, no parent expansion)** – this is the current production index.

| Setting | Choice | Evidence |
|---|---|---|
| Chunking | Structure-aware, ~350-token children (Key facts / tables / prose kept separate) | Ties `struct_600` on R@5 (0.98) and on the same-20 RAGAS answer accuracy (0.81 vs 0.82, within noise), with **24% less context** (956 vs 1,260 tokens) and faster answers (1.6 s vs 2.0 s). Beats `struct_200` (0.95) and the naive `fixed_400` window (0.95 at **~2x the context**, weaker on facts/tables). |
| Breadcrumb prefix | **Required** ("Article > Section" prepended before embedding / BM25) | Removing it drops R@5 from 0.98 to 0.75; Key facts and tables fall to ~0.5 because those chunks never name their subject. Single largest effect in the study. |
| Retrieval | Hybrid: Azure `text-embedding-3-large` dense + BM25 sparse, RRF fusion in Qdrant, top 5 | Hybrid ≥ either alone in every variant (dense 0.93, BM25 0.88, hybrid 0.98 on struct_350). BM25 alone is weak on Key facts (0.67). ~15–30 ms per query. |
| Reranker | **None** | MiniLM made results worse (R@5 0.98 → 0.88) and cost 5–13 s/query on CPU; bge-reranker-v2-m3 gave +3 pts R@1 (within noise) for **43 s/query**. Revisit only with a GPU / hosted rerank API. |
| Parent expansion | Off by default | Only useful together with a reranker; doubles context (~2,000–2,600 tokens) for no recall gain over plain hybrid. |
| Generation | gpt-6-luna, answer only from numbered sources, cite [n], fixed refusal sentence | vs no-RAG: answer accuracy **0.54 → 0.88**, faithfulness 0.99, context recall 1.00, out-of-scope refused **0% → 100%**, false refusals 5% → 0%, latency 3.7 s → 1.6 s. |
| "Not in my documents" guard | Prompt rule + optional dense-score threshold ≈ 0.5 | Best dense match for real questions was never below 0.51; for out-of-scope questions never above 0.50. |

### Caveats (read before quoting numbers)

- **Small eval set**: 60 in-scope questions → about ±10 points (95%) on recall-type scores; differences of a few points between the top configs are not significant. `struct_600` RAGAS used a stratified 20-question subset (seed 7); section 4 compares all pipelines on exactly those 20.
- **Synthetic questions**: generated by gpt-6-luna from sampled passages (verbatim evidence checked). Real user questions are vaguer and multi-hop – add a hand-written set before production.
- **Same model as generator and judge** (gpt-6-luna) → possible self-preference bias; a different judge model would make RAGAS scores more trustworthy.
- **factual_correctness (recall mode) is low for every pipeline (0.2–0.4)** because RAGAS splits the long reference answers into many atomic claims; `answer_accuracy` (0.88) is the more reliable correctness signal here – spot checks of answers agree.
- **Reranker test** truncated candidates to ~300 tokens to keep CPU time manageable; this may under-rate rerankers on long Key-facts/table chunks.
- Only 5 out-of-scope questions; the refusal rate needs a larger adversarial set.

### Next steps

1. Keep the production index (`isro_chunks`, struct_350 + breadcrumb) and use **hybrid top-5** in the agent.
2. Add the refusal prompt + dense-score threshold as the out-of-scope guardrail.
3. Grow the eval set to ~150 questions stratified by topic category and add hand-written / multi-hop questions; run evals in CI (retrieval A/B is free and takes ~1 minute).
4. Re-test a reranker only if a GPU or hosted rerank endpoint is available.
