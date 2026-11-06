"""Conversations / threads CRUD and ownership isolation between users."""


async def test_conversation_and_thread_lifecycle(client, user_factory):
    headers, _, _ = await user_factory()
    conv = (await client.post("/conversations", json={}, headers=headers)).json()
    assert conv["title"] is None and conv["title_source"] is None and conv["thread_count"] == 0

    t1 = (await client.post(f"/conversations/{conv['id']}/threads", json={}, headers=headers)).json()
    t2 = (await client.post(f"/conversations/{conv['id']}/threads", json={"title": "orbits"}, headers=headers)).json()
    listed = (await client.get(f"/conversations/{conv['id']}/threads", headers=headers)).json()
    assert [t["id"] for t in listed] == [t1["id"], t2["id"]]

    renamed = (await client.patch(f"/conversations/{conv['id']}", json={"title": "Moon missions"}, headers=headers)).json()
    assert renamed["title"] == "Moon missions" and renamed["title_source"] == "user" and renamed["thread_count"] == 2

    assert (await client.delete(f"/threads/{t2['id']}", headers=headers)).status_code == 204
    detail = (await client.get(f"/conversations/{conv['id']}", headers=headers)).json()
    assert [t["id"] for t in detail["threads"]] == [t1["id"]]

    assert (await client.delete(f"/conversations/{conv['id']}", headers=headers)).status_code == 204
    assert conv["id"] not in [c["id"] for c in (await client.get("/conversations", headers=headers)).json()["items"]]
    archived = (await client.get("/conversations", params={"include_archived": True}, headers=headers)).json()
    assert conv["id"] in [c["id"] for c in archived["items"]]


async def test_cursor_pagination_pages_of_ten(app, client, user_factory):
    from datetime import datetime, timedelta, timezone

    from app.db.models import Conversation
    headers, _, _ = await user_factory()
    me = (await client.get("/auth/me", headers=headers)).json()
    base = datetime.now(timezone.utc)
    async with app.state.db.sessionmaker() as s:   # 25 conversations with distinct activity times
        for i in range(25):
            s.add(Conversation(user_id=me["id"], title=f"c{i:02d}", last_activity_at=base - timedelta(minutes=i)))
        await s.commit()

    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 10, **({"cursor": cursor} if cursor else {})}
        page = (await client.get("/conversations", params=params, headers=headers)).json()
        seen += [c["title"] for c in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert pages == 3 and len(seen) == 25 and len(set(seen)) == 25
    assert seen == [f"c{i:02d}" for i in range(25)]                       # most recent first
    bad = await client.get("/conversations", params={"cursor": "%%%"}, headers=headers)
    assert bad.status_code == 422


async def test_users_cannot_see_each_others_data(client, user_factory):
    alice, _, _ = await user_factory()
    bob, _, _ = await user_factory()
    conv = (await client.post("/conversations", json={"title": "private"}, headers=alice)).json()
    thread = (await client.post(f"/conversations/{conv['id']}/threads", json={}, headers=alice)).json()

    for method, path in [("get", f"/conversations/{conv['id']}"), ("patch", f"/conversations/{conv['id']}"),
                         ("post", f"/conversations/{conv['id']}/threads"), ("get", f"/threads/{thread['id']}"),
                         ("get", f"/threads/{thread['id']}/runs"), ("get", f"/usage/threads/{thread['id']}"),
                         ("get", f"/usage/conversations/{conv['id']}")]:
        kwargs = {"json": {}} if method in ("post", "patch") else {}
        r = await getattr(client, method)(path, headers=bob, **kwargs)
        assert r.status_code == 404, (method, path, r.status_code)       # 404, not 403: no existence leak
    assert (await client.get("/conversations", headers=bob)).json() == {"items": [], "next_cursor": None}


async def test_agent_endpoints_report_unavailable_agent(client, user_factory):
    headers, _, _ = await user_factory()
    conv = (await client.post("/conversations", json={}, headers=headers)).json()
    thread = (await client.post(f"/conversations/{conv['id']}/threads", json={}, headers=headers)).json()
    r = await client.post(f"/threads/{thread['id']}/ask", json={"question": "hi"}, headers=headers)
    assert r.status_code == 503 and "agent" in r.json()["detail"]
