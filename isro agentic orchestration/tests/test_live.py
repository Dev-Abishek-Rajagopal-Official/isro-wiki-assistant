"""
Live tests: real LLM, MCP servers (HTTP), Postgres and Azure Speech. Skipped automatically when the
infrastructure is not running.  Start: docker compose up -d ; isromcp: uv run python run_http_servers.py
"""

import socket
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

from orchestrator.service import LIVE_ONLY_EVENTS, IsroAgentService


def _up(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


pytestmark = [
    pytest.mark.skipif(not all(_up(p) for p in (5432, 8101, 8102, 8103, 8104)),
                       reason="Postgres or MCP servers not running"),
    # One event loop for all live tests, like the FastAPI app (langchain-openai shares one async HTTP client
    # per endpoint at module level, which must stay on the loop that created it).
    pytest.mark.asyncio(loop_scope="session"),
]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def svc():
    s = IsroAgentService()
    await s.startup()
    yield s
    await s.shutdown()


async def test_stream_is_persisted_in_order(svc):
    thread = f"test-{uuid.uuid4().hex[:8]}"
    streamed = [ev async for ev in svc.stream("Who won the 2018 FIFA World Cup?", thread)]
    stored = await svc.history(thread)

    persisted = [e for e in streamed if e["event_type"] not in LIVE_ONLY_EVENTS]
    assert any(e["event_type"] == "state" for e in streamed)            # live AgentState snapshots
    assert streamed[-1]["payload"]["run_usage"]["llm_calls"] >= 2        # router + final at least
    assert [e["seq"] for e in stored] == list(range(1, len(stored) + 1))           # gap-free order
    assert [(e["event_type"], e["node"]) for e in stored] == [(e["event_type"], e["node"]) for e in persisted]
    types = [e["event_type"] for e in stored]
    assert types[0] == "run_started" and types[-1] == "run_finished"
    assert "router_decision" in types and "final_answer" in types


async def test_router_skips_agents_for_out_of_scope(svc):
    r = await svc.ask("What is the capital of Australia?", f"test-{uuid.uuid4().hex[:8]}")
    assert r["agents_used"] == [] and r["answer"]


async def test_live_question_uses_celestrak_with_sources(svc):
    r = await svc.ask("Is Cartosat-3 still in orbit?", f"test-{uuid.uuid4().hex[:8]}")
    assert "celestrak_agent" in r["agents_used"]
    assert any("celestrak" in (s.get("url") or "") for s in r["sources"])


async def test_conversation_memory(svc):
    thread = f"test-{uuid.uuid4().hex[:8]}"
    first = await svc.ask("Which rocket launched Chandrayaan-3?", thread)
    r = await svc.ask("When did that mission land on the Moon?", thread)
    assert "2023" in r["answer"]
    # thread usage accumulates across runs; run usage covers only the current question
    assert r["thread_usage"]["llm_calls"] == first["run_usage"]["llm_calls"] + r["run_usage"]["llm_calls"]


async def test_audio_question(svc, tmp_path):
    wav = Path(__file__).parent / "data" / "question.wav"
    if not wav.exists():
        pytest.skip("tests/data/question.wav missing")
    r = await svc.ask_audio(wav.read_bytes(), "question.wav", "audio/wav", f"test-{uuid.uuid4().hex[:8]}")
    assert "Cartosat" in r["transcript"]["text"] and r["answer"]
