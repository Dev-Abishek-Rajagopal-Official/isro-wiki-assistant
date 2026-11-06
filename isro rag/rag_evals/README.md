# rag_evals – finding the best RAG configuration

Run from `isro rag/` (Qdrant server running, `.env` filled in).

| Step | Command | Cost / time |
|---|---|---|
| 1. Eval set from the documents (questions + verbatim evidence) | `uv run python rag_evals/build_dataset.py --n 60` | ~1 min, gpt-6-luna |
| 2. Chunk + index every variant into `eval_<variant>_*` collections | `uv run python rag_evals/build_variants.py` | ~8 min, embeddings cached |
| 3. Retrieval A/B (no LLM): variants × dense / bm25 / hybrid, rerankers on the top 2 | `uv run python rag_evals/retrieval_ab.py` | ~1 min without rerankers; CPU rerankers are slow |
| 4. End-to-end RAGAS (gpt-6-luna generates + judges) | `uv run python rag_evals/ragas_eval.py --pipelines norag "struct_350\|hybrid\|-\|-"` (add `--subset 20` for a stratified 20-question run) | ~15 min per pipeline on 60 questions |
| 5. Report | `uv run python rag_evals/report.py` → `results/REPORT.md` | seconds |

Files
- `variants.py` – the chunking variants under test (sizes, breadcrumb on/off, naive fixed window).
- `common.py` – LLM client (Responses API), evidence matching, experiment logger.
- `results/experiments.csv` / `experiments.log` – every finding, appended as it is produced (re-runs supersede earlier rows in the report).
- `results/details/` – per-question results for every run.
- `results/CONCLUSIONS.md` – the written interpretation, appended to the report.

Pipelines in `ragas_eval.py` are written `<variant>|<dense|bm25|hybrid>|<reranker or ->|<parent or ->`, or `norag`.
