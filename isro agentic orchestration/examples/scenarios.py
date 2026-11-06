"""
Run the live scenarios and print route, timing and answer preview for each (results also in Postgres).

    uv run python examples/scenarios.py
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrator.service import IsroAgentService, use_selector_event_loop  # noqa: E402

SCENARIOS = [
    ("orbit", ["Is Cartosat-3 still in orbit, and what is its current altitude?"]),
    ("list", ["List the Chandrayaan missions with their launch dates."]),
    ("explain", ["Why did the atomic clocks on the IRNSS navigation satellites fail?"]),
    ("out_of_scope", ["Who won the 2018 FIFA World Cup?"]),
    ("follow_up", ["Which rocket launched the Mars Orbiter Mission?", "How much did that spacecraft weigh at launch?"]),
]


async def main() -> None:
    svc = IsroAgentService()
    await svc.startup()
    try:
        for name, turns in SCENARIOS:
            thread = f"scenario-{name}-{uuid.uuid4().hex[:6]}"
            for q in turns:
                r = await svc.ask(q, thread)
                route = " -> ".join(d["next_agent"] for d in r["router_decisions"])
                print(f"\n=== [{name}] {q}\nroute: router -> {route}   ({r['seconds']}s, {len(r['sources'])} sources)")
                print("answer:", r["answer"][:600].replace("\n", " "))
    finally:
        await svc.shutdown()


if __name__ == "__main__":
    use_selector_event_loop()
    asyncio.run(main())
