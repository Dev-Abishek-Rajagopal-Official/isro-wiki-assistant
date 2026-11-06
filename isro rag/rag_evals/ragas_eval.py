"""
End-to-end A/B with RAGAS: retrieve -> generate (gpt-6-luna, Responses API) -> judge (RAGAS, gpt-6-luna).

Pipelines are written  <variant>|<mode>|<reranker or ->|<parent or ->   e.g.  struct_350|hybrid|bge-m3|parent
plus the special  norag  (LLM answers from its own knowledge, no retrieval) as the baseline.
Default: the 2 best retrieval pipelines from results/experiments.csv + norag.

Metrics (in-scope questions)
  faithfulness         answer claims supported by the retrieved context
  answer_relevancy     answer addresses the question
  context_precision    relevant chunks ranked high (vs reference answer)
  context_recall       reference answer covered by the context
  factual_correctness  answer vs reference answer (F1 over claims)
Behaviour
  oos_refusal_rate     out-of-scope questions answered with "could not find" (higher = better)
  false_refusal_rate   in-scope questions wrongly refused (lower = better)

Usage:
    uv run python rag_evals/ragas_eval.py                                # auto-pick
    uv run python rag_evals/ragas_eval.py --pipelines norag "struct_350|hybrid|bge-m3|parent" --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import statistics
from concurrent.futures import ThreadPoolExecutor

from common import (EVAL_SET, EXPERIMENTS_CSV, LLM, LLM_MODEL, V1_BASE_URL, log, read_jsonl, record,
                    write_details)
from retrieval_ab import FINAL_K, RERANK_CANDIDATES, RERANKERS, Retriever
from variants import VARIANTS

from config import get_settings  # noqa: E402
from embeddings import BM25Embedder, build_dense_embedder  # noqa: E402
from index import get_client  # noqa: E402

REFUSAL = "I could not find this in the provided documents."
REFUSAL_RE = re.compile(r"could not find this in the provided documents|i don't know|i do not know", re.I)

RAG_INSTRUCTIONS = f"""You answer questions about the Indian space programme using ONLY the numbered sources provided.
- Answer in 1-3 sentences, with the specific fact asked for.
- Cite the sources you used like [1] or [2][3].
- If the sources do not contain the answer, reply exactly: "{REFUSAL}"
- Never use outside knowledge."""

NORAG_INSTRUCTIONS = """Answer the question about the Indian space programme in 1-3 sentences.
If you do not know the answer, reply exactly: "I don't know." """


def parse_pipeline(spec: str) -> dict:
    if spec == "norag":
        return {"label": "norag", "norag": True}
    variant, mode, rr, parent = (spec.split("|") + ["-", "-"])[:4]
    return {"label": spec, "norag": False, "variant": variant, "mode": mode,
            "reranker": None if rr in ("-", "") else rr, "parent": parent == "parent"}


def best_retrieval_pipelines(n: int) -> list[str]:
    with open(EXPERIMENTS_CSV, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["stage"] == "retrieval"]
    rows.sort(key=lambda r: (float(r["evidence_recall@5"]), float(r["mrr@10"])), reverse=True)
    out = []
    for r in rows:
        spec = f"{r['chunk_config']}|{r['retrieval']}|{r['reranker'] or '-'}|{'parent' if r['parent_expansion'] == 'yes' else '-'}"
        if spec not in out:
            out.append(spec)
        if len(out) == n:
            break
    return out


def stratified_subset(items: list[dict], n: int, seed: int) -> list[dict]:
    """n questions with the same type mix as the full set (largest remainder), each from a different
    article where possible, picked with a fixed seed so the subset is reproducible."""
    import random

    rng = random.Random(seed)
    by_type: dict[str, list[dict]] = {}
    for it in items:
        by_type.setdefault(it["type"], []).append(it)
    exact = {t: n * len(v) / len(items) for t, v in by_type.items()}
    quota = {t: int(x) for t, x in exact.items()}
    for t in sorted(exact, key=lambda t: exact[t] - quota[t], reverse=True)[: n - sum(quota.values())]:
        quota[t] += 1
    chosen, used_articles = [], set()
    for t in sorted(by_type):
        pool = by_type[t][:]
        rng.shuffle(pool)
        fresh = [i for i in pool if i["source_title"] not in used_articles]
        pick = (fresh + [i for i in pool if i not in fresh])[: quota[t]]
        chosen += pick
        used_articles |= {i["source_title"] for i in pick}
    return sorted(chosen, key=lambda i: i["id"])


def build_ragas(s):
    from openai import AsyncOpenAI
    from ragas.embeddings import OpenAIEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (AnswerAccuracy, AnswerRelevancy, ContextRecall, FactualCorrectness,
                                           Faithfulness)

    aclient = AsyncOpenAI(base_url=V1_BASE_URL, api_key=s.azure_api_key, max_retries=6, timeout=180)
    llm = llm_factory(LLM_MODEL, client=aclient)
    emb = OpenAIEmbeddings(client=aclient, model=s.embed_deployment)
    # context_precision is not run here: chunk ranking is measured exactly (and free) in retrieval_ab.py.
    # factual_correctness in RECALL mode: "does the answer contain the reference facts?" - F1 mode
    # punished correct answers that add true detail (scored 0.0 on exact-date answers in the smoke test).
    return {
        "faithfulness": Faithfulness(llm=llm),
        "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=emb),
        "context_recall": ContextRecall(llm=llm),
        "factual_correctness": FactualCorrectness(llm=llm, mode="recall"),
        "answer_accuracy": AnswerAccuracy(llm=llm),
    }


async def score_item(metrics: dict, sem: asyncio.Semaphore, item: dict, norag: bool) -> dict:
    q, ref, ctx = item["question"], item["reference_answer"], item["contexts"]
    a = re.sub(r"\s*\[\d+\]", "", item["answer"]).strip()  # citation markers are not claims
    calls = {
        "answer_relevancy": lambda: metrics["answer_relevancy"].ascore(user_input=q, response=a),
        "factual_correctness": lambda: metrics["factual_correctness"].ascore(response=a, reference=ref),
        "answer_accuracy": lambda: metrics["answer_accuracy"].ascore(user_input=q, response=a, reference=ref),
    }
    if not norag:
        calls |= {
            "faithfulness": lambda: metrics["faithfulness"].ascore(user_input=q, response=a, retrieved_contexts=ctx),
            "context_recall": lambda: metrics["context_recall"].ascore(user_input=q, retrieved_contexts=ctx,
                                                                       reference=ref),
        }

    async def one(name, fn):
        # ragas/instructor makes a single attempt; transient connection errors are retried here so
        # that failed scores are not silently dropped from the averages.
        last = None
        for attempt in range(4):
            async with sem:
                try:
                    value = float((await fn()).value)
                    PROGRESS["done"] += 1
                    if PROGRESS["done"] % 25 == 0 or PROGRESS["done"] == PROGRESS["total"]:
                        log(f"[ragas]   progress: {PROGRESS['done']}/{PROGRESS['total']} judge jobs done")
                    return name, value
                except Exception as e:  # noqa: BLE001
                    last = e
            await asyncio.sleep(5 * 2 ** attempt)
        PROGRESS["done"] += 1
        log(f"[ragas] {name} FAILED after 4 attempts on {item['id']}: {type(last).__name__}: {str(last)[:150]}")
        return name, None

    return dict(await asyncio.gather(*(one(n, f) for n, f in calls.items())))


PROGRESS = {"done": 0, "total": 0}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipelines", nargs="*", help="default: norag + 2 best retrieval pipelines")
    ap.add_argument("--limit", type=int, help="only the first N in-scope questions (quick runs)")
    ap.add_argument("--subset", type=int, help="stratified subset of N in-scope questions (by type, distinct articles)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--concurrency", type=int, default=12)
    args = ap.parse_args()

    specs = args.pipelines or ["norag", *best_retrieval_pipelines(2)]
    s = get_settings()
    llm = LLM()
    needed_rr = {p["reranker"] for p in map(parse_pipeline, specs) if not p["norag"] and p["reranker"]}
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    rerankers = {n: TextCrossEncoder(RERANKERS[n], cache_dir=str(s.model_cache)) for n in needed_rr}
    retriever = Retriever(get_client(s), build_dense_embedder(s), BM25Embedder(s.sparse_model, s.model_cache),
                          rerankers)
    metrics = build_ragas(s)

    all_items = read_jsonl(EVAL_SET)
    in_scope = [i for i in all_items if i["in_scope"]][: args.limit] if args.limit else \
        [i for i in all_items if i["in_scope"]]
    if args.subset:
        in_scope = stratified_subset(in_scope, args.subset, args.seed)
        log(f"[ragas] stratified subset of {len(in_scope)} (seed {args.seed}): {[i['id'] for i in in_scope]}")
    items = in_scope + [i for i in all_items if not i["in_scope"]]
    log(f"[ragas] pipelines={specs}, questions={len(in_scope)} in-scope + {len(items) - len(in_scope)} out-of-scope")

    for spec in specs:
        p = parse_pipeline(spec)

        def answer(it, p=p):
            if p["norag"]:
                ctx = []
                r = llm.generate(NORAG_INSTRUCTIONS, it["question"])
            else:
                v = VARIANTS[p["variant"]]
                ranked = retriever.search(v.chunks_collection, it["question"], p["mode"],
                                          RERANK_CANDIDATES if p["reranker"] else FINAL_K)
                if p["reranker"]:
                    ranked = retriever.rerank(p["reranker"], it["question"], ranked, FINAL_K)
                final = ranked[:FINAL_K]
                if p["parent"]:
                    bodies = retriever.expand_parents(v.parents_collection, final)
                    heads = [h["breadcrumb"] for h in final][: len(bodies)]
                else:
                    bodies, heads = [h["content"] for h in final], [h["breadcrumb"] for h in final]
                ctx = [f"{h}\n{b}" for h, b in zip(heads, bodies)]
                prompt = "Sources:\n\n" + "\n\n".join(f"[{n}] {c}" for n, c in enumerate(ctx, 1)) + \
                         f"\n\nQuestion: {it['question']}"
                r = llm.generate(RAG_INSTRUCTIONS, prompt)
            return {**it, "answer": r["text"].strip(), "contexts": ctx, "latency_s": r["latency_s"],
                    "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"],
                    "refused": bool(REFUSAL_RE.search(r["text"]))}

        with ThreadPoolExecutor(max_workers=6) as pool:
            answered = list(pool.map(answer, items))
        log(f"[ragas] {spec}: {len(answered)} answers generated, scoring with RAGAS ...")

        n_in = sum(a["in_scope"] for a in answered)
        PROGRESS.update(done=0, total=n_in * (3 if p["norag"] else 5))

        async def score_all():
            sem = asyncio.Semaphore(args.concurrency)
            return await asyncio.gather(*(score_item(metrics, sem, a, p["norag"]) for a in answered if a["in_scope"]))

        scores = asyncio.run(score_all())
        scored = [a for a in answered if a["in_scope"]]
        for a, sc in zip(scored, scores):
            a["scores"] = sc

        def avg(name):
            vals = [a["scores"].get(name) for a in scored if a["scores"].get(name) is not None]
            return statistics.mean(vals) if vals else ""

        oos_items = [a for a in answered if not a["in_scope"]]
        res = {
            "n_questions": len(answered),
            "faithfulness": avg("faithfulness"), "answer_relevancy": avg("answer_relevancy"),
            "context_precision": avg("context_precision"), "context_recall": avg("context_recall"),
            "factual_correctness": avg("factual_correctness"), "answer_accuracy": avg("answer_accuracy"),
            "oos_refusal_rate": sum(a["refused"] for a in oos_items) / len(oos_items) if oos_items else "",
            "false_refusal_rate": sum(a["refused"] for a in scored) / len(scored),
            "avg_answer_latency_s": statistics.mean(a["latency_s"] for a in answered),
            "llm_input_tokens": sum(a["input_tokens"] for a in answered),
            "llm_output_tokens": sum(a["output_tokens"] for a in answered),
        }
        if not p["norag"]:
            res |= {"chunk_config": p["variant"], "retrieval": p["mode"], "reranker": p["reranker"] or "",
                    "parent_expansion": "yes" if p["parent"] else "no"}
        n_failed = sum(1 for a in scored for v in a["scores"].values() if v is None)
        record("ragas", spec, {k: v for k, v in res.items() if v != ""},
               notes=(f"generator+judge={LLM_MODEL}; in-scope={len(scored)}, out-of-scope={len(oos_items)}; "
                      f"failed judge calls={n_failed}"
                      + (f"; SMOKE TEST (--limit {args.limit}), not a result" if args.limit else "")
                      + (f"; stratified subset {args.subset} (seed {args.seed})" if args.subset else "")))
        write_details(f"ragas__{spec}", [{k: a[k] for k in ("id", "type", "question", "reference_answer", "answer",
                                                             "refused", "latency_s")} | {"scores": a.get("scores"),
                                                                                         "contexts": a["contexts"]}
                                         for a in answered])


if __name__ == "__main__":
    main()
