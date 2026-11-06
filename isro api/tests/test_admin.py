"""Admin role: reserved emails, access control (404 for others), analytics endpoints."""

import uuid

from app.core.security import hash_password
from app.db.models import LlmCall, Run, Thread, User
from app.db.models import Conversation as Conv

ADMIN_EMAIL = "admin-test@example.com"
ADMIN_PASSWORD = "admin-pass-123"


async def _admin_headers(app, client):
    async with app.state.db.sessionmaker() as s:
        from sqlalchemy import select
        if (await s.execute(select(User).where(User.email == ADMIN_EMAIL))).scalar_one_or_none() is None:
            s.add(User(email=ADMIN_EMAIL, full_name="Admin", password_hash=hash_password(ADMIN_PASSWORD)))
            await s.commit()
    tokens = (await client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_admin_emails_are_reserved_from_registration(client):
    for email in ("official@abishekrajagopal.com", "OFFICIAL@abishekrajagopal.com", ADMIN_EMAIL):
        r = await client.post("/auth/register", json={"email": email, "full_name": "x", "password": "abc12345"})
        assert r.status_code == 403 and r.json()["detail"] == "this email is reserved"


async def test_is_admin_flag(app, client, user_factory):
    normal, _, _ = await user_factory()
    assert (await client.get("/auth/me", headers=normal)).json()["is_admin"] is False
    admin = await _admin_headers(app, client)
    assert (await client.get("/auth/me", headers=admin)).json()["is_admin"] is True


async def test_admin_endpoints_hidden_from_normal_users(client, user_factory):
    normal, _, _ = await user_factory()
    for path in ("/admin/overview", "/admin/timeseries", "/admin/agents", "/admin/tools", "/admin/models",
                 "/admin/users", f"/admin/users/{uuid.uuid4()}", "/admin/runs", f"/admin/runs/{uuid.uuid4()}"):
        assert (await client.get(path, headers=normal)).status_code == 404, path
    assert (await client.get("/admin/overview")).status_code == 401


async def test_admin_analytics(app, client, user_factory):
    _, _, email = await user_factory()
    async with app.state.db.sessionmaker() as s:
        from sqlalchemy import select
        user = (await s.execute(select(User).where(User.email == email))).scalar_one()
        conv = Conv(user_id=user.id, title="t")
        s.add(conv)
        await s.flush()
        thread = Thread(conversation_id=conv.id, user_id=user.id)
        s.add(thread)
        await s.flush()
        ok = Run(thread_id=thread.id, user_id=user.id, question="a", status="succeeded", seconds=5.0,
                 agents_used=["rag_agent"], input_tokens=100, output_tokens=10)
        bad = Run(thread_id=thread.id, user_id=user.id, question="b", status="failed", error="boom", seconds=2.0,
                  agents_used=["rag_agent", "launch_agent"])
        s.add_all([ok, bad])
        await s.flush()
        s.add(LlmCall(run_id=ok.id, thread_id=thread.id, conversation_id=conv.id, user_id=user.id, node="router",
                      role="router", model="m", input_tokens=100, output_tokens=10, seconds=1.0))
        await s.commit()

    admin = await _admin_headers(app, client)
    ov = (await client.get("/admin/overview", headers=admin)).json()
    assert ov["users"]["total"] >= 2 and ov["runs"]["requests"] >= 2 and ov["runs"]["failed"] >= 1
    assert ov["tokens"]["input_tokens"] >= 100

    ts = (await client.get("/admin/timeseries", params={"bucket": "day"}, headers=admin)).json()
    assert ts and ts[-1]["requests"] >= 2

    ag = (await client.get("/admin/agents", headers=admin)).json()
    assert {a["agent"] for a in ag["agent_usage"]} >= {"rag_agent", "launch_agent"}
    assert any(r["route"] == ["router", "rag_agent", "final_agent"] for r in ag["routes"])

    assert isinstance((await client.get("/admin/tools", headers=admin)).json(), list)
    assert (await client.get("/admin/models", headers=admin)).json()["by_model"]

    users = (await client.get("/admin/users", params={"search": email}, headers=admin)).json()
    assert users["total"] == 1 and users["items"][0]["requests"] == 2 and users["items"][0]["failed"] == 1
    detail = (await client.get(f"/admin/users/{users['items'][0]['id']}", headers=admin)).json()
    assert detail["user"]["email"] == email

    failed = (await client.get("/admin/runs", params={"status": "failed"}, headers=admin)).json()
    assert any(r["error"] == "boom" and r["user_email"] == email for r in failed["items"])
    run = (await client.get(f"/admin/runs/{failed['items'][0]['id']}", headers=admin)).json()
    assert run["run"]["status"] == "failed" and "events" in run
