"""Usage aggregation over runs and llm_calls (rows inserted directly, no LLM involved)."""

import uuid

from app.db.models import LlmCall, Run


async def _seed(app, user_id, thread_id, conv_id):
    async with app.state.db.sessionmaker() as s:
        runs = [Run(id=uuid.uuid4(), thread_id=thread_id, user_id=user_id, question="q1", status="succeeded",
                    seconds=10.0, input_type="text"),
                Run(id=uuid.uuid4(), thread_id=thread_id, user_id=user_id, question="q2", status="failed",
                    seconds=30.0, input_type="voice")]
        s.add_all(runs)
        await s.flush()
        for role, model, i, o, r in [("router", "m-a", 100, 10, 2), ("router", "m-a", 120, 12, 0),
                                     ("final", "m-b", 300, 80, 20)]:
            s.add(LlmCall(run_id=runs[0].id, thread_id=thread_id, conversation_id=conv_id, user_id=user_id,
                          node=role, role=role, model=model, input_tokens=i, output_tokens=o, reasoning_tokens=r,
                          seconds=1.0, ratelimit_remaining_tokens=5000))
        await s.commit()


async def test_usage_totals_and_groups(app, client, user_factory):
    headers, _, _ = await user_factory()
    me = (await client.get("/auth/me", headers=headers)).json()
    conv = (await client.post("/conversations", json={"title": "u"}, headers=headers)).json()
    thread = (await client.post(f"/conversations/{conv['id']}/threads", json={}, headers=headers)).json()
    await _seed(app, uuid.UUID(me["id"]), uuid.UUID(thread["id"]), uuid.UUID(conv["id"]))

    rep = (await client.get("/usage/me", params={"group_by": "role"}, headers=headers)).json()
    assert rep["runs"]["requests"] == 2 and rep["runs"]["failed"] == 1 and rep["runs"]["voice_requests"] == 1
    assert rep["runs"]["error_rate"] == 0.5 and rep["runs"]["p50_seconds"] == 20.0
    t = rep["tokens"]
    assert (t["llm_calls"], t["input_tokens"], t["output_tokens"], t["reasoning_tokens"]) == (3, 520, 102, 22)
    assert t["total_tokens"] == 622
    roles = {g["key"]: g for g in rep["groups"]}
    assert roles["router"]["llm_calls"] == 2 and roles["final"]["input_tokens"] == 300
    assert rep["latest_rate_limit"]["remaining_tokens"] == 5000

    by_model = (await client.get(f"/usage/threads/{thread['id']}", params={"group_by": "model"}, headers=headers)).json()
    assert {g["key"]: g["llm_calls"] for g in by_model["groups"]} == {"m-a": 2, "m-b": 1}
    by_thread = (await client.get(f"/usage/conversations/{conv['id']}", headers=headers)).json()
    assert by_thread["groups"][0]["key"] == thread["id"]


async def test_usage_is_per_user(client, user_factory):
    headers, _, _ = await user_factory()
    rep = (await client.get("/usage/me", headers=headers)).json()
    assert rep["runs"]["requests"] == 0 and rep["tokens"]["llm_calls"] == 0
