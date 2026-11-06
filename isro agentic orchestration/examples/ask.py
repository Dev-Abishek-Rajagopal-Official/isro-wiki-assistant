"""
Ask one question (or an audio file) and print every event as the frontend would receive it.

    uv run python examples/ask.py "When is the next ISRO launch?" --thread demo-1
    uv run python examples/ask.py --audio question.wav --thread demo-1
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrator.service import IsroAgentService, use_selector_event_loop  # noqa: E402


def show(ev: dict) -> None:
    et, node, p = ev["event_type"], ev.get("node") or "", ev.get("payload", {})
    if et == "token":
        print(p["text"], end="", flush=True)
        return
    if et == "router_decision":
        s = p["structured"]
        filled = [a for a in ("rag_agent", "launch_agent", "wikidata_agent", "celestrak_agent") if s[a]]
        detail = f"next={s['next_agent']} | task={s['task'][:90]!r} | filled={filled} | {p['llm']['seconds']}s"
    elif et == "query_rewritten":
        detail = f"{p['rewritten_query'][:80]!r} -> {[(c['tool'], c['arguments_json']) for c in p['tool_calls']]}"
    elif et in ("tool_called", "tool_result"):
        detail = json.dumps({k: v for k, v in p.items() if v not in (None, "")})[:140]
    elif et == "agent_content":
        detail = f"{len(p['content'])} chars, {len(p['sources'])} sources, {p['llm']['seconds']}s: {p['content'][:120]!r}"
    elif et == "state_update":
        detail = "changed: " + ", ".join(p["changes"].keys())
    elif et == "final_answer":
        print()
        detail = f"{len(p['answer'])} chars, {len(p['sources'])} sources"
    else:
        detail = json.dumps(p)[:160]
    print(f"[{ev.get('seq', '-'):>3}] {et:<16} {node:<15} {detail}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?")
    ap.add_argument("--audio")
    ap.add_argument("--thread", default="demo")
    args = ap.parse_args()
    svc = IsroAgentService()
    await svc.startup()
    try:
        if args.audio:
            data = Path(args.audio).read_bytes()
            stream = svc.stream_audio(data, Path(args.audio).name, "audio/wav", args.thread)
        else:
            stream = svc.stream(args.question, args.thread)
        async for ev in stream:
            show(ev)
    finally:
        await svc.shutdown()


if __name__ == "__main__":
    use_selector_event_loop()
    asyncio.run(main())
