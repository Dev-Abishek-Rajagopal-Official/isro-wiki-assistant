"""
End-to-end client: register -> login -> conversation with two threads -> ask both concurrently over one
WebSocket (streamed chunks + live AgentState) -> history, usage, replay -> logout.

    uv run python examples/ws_client.py [--base http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from collections import Counter

import httpx
import websockets

QUESTIONS = ["Is Cartosat-3 still in orbit?", "What was the launch mass of GSAT-7?"]


async def main(base: str) -> None:
    ws_url = base.replace("http", "ws", 1) + "/ws"
    async with httpx.AsyncClient(base_url=base, timeout=300) as http:
        email = f"demo-{uuid.uuid4().hex[:8]}@example.com"
        r = await http.post("/auth/register", json={"email": email, "full_name": "Demo User", "password": "demo-pass-123"})
        print("register:", r.status_code)
        tokens = (await http.post("/auth/login", json={"email": email, "password": "demo-pass-123"})).json()
        auth = {"Authorization": f"Bearer {tokens['access_token']}"}
        print("login: access token expires in", tokens["expires_in"] // 3600, "h")

        conv = (await http.post("/conversations", json={}, headers=auth)).json()
        threads = [(await http.post(f"/conversations/{conv['id']}/threads", json={}, headers=auth)).json()
                   for _ in QUESTIONS]
        print("conversation:", conv["id"], "| threads:", [t["id"][:8] for t in threads])

        # ---- one socket, two concurrent runs
        counts: dict[str, Counter] = {t["id"]: Counter() for t in threads}
        finished, answers, last_state, title = set(), {}, {}, None
        async with websockets.connect(ws_url, max_size=None) as ws:
            await ws.send(json.dumps({"type": "auth", "token": tokens["access_token"]}))
            print("ws:", json.loads(await ws.recv())["type"])
            for t, q in zip(threads, QUESTIONS):
                await ws.send(json.dumps({"type": "ask", "thread_id": t["id"], "question": q, "client_msg_id": q[:10]}))
            while len(finished) < len(threads) or title is None:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=300))
                kind, tid = msg["type"], msg.get("thread_id")
                if kind == "conversation_titled":
                    title = msg["title"]
                    continue
                if tid in counts:
                    counts[tid][kind if kind != "agent_progress" else f"progress:{msg['step']}"] += 1
                if kind == "router_decision":
                    print(f"  [{tid[:8]}] router -> {msg['data']['structured']['next_agent']}")
                elif kind == "state":
                    last_state[tid] = msg["data"]["agent_state"]
                elif kind == "final_answer":
                    answers[tid] = msg["data"]["answer"]
                elif kind == "run_finished":
                    finished.add(tid)
                    print(f"  [{tid[:8]}] finished in {msg['data']['seconds']}s, "
                          f"run tokens in/out = {msg['data']['run_usage']['input_tokens']}/"
                          f"{msg['data']['run_usage']['output_tokens']}")
                elif kind in ("error", "busy"):
                    print("  !!", msg)
        for t, q in zip(threads, QUESTIONS):
            c = counts[t["id"]]
            print(f"\nQ: {q}\n  streamed: tokens={c['token']} state={c['state']} router={c['router_decision']} "
                  f"llm_call={c['llm_call']} progress={sum(v for k, v in c.items() if k.startswith('progress'))}")
            print("  live AgentState keys:", sorted(last_state[t["id"]].keys()))
            print("  answer:", answers[t["id"]][:160].replace("\n", " "))
        print("\nconversation title (LLM):", title)

        # ---- history & usage over REST
        detail = (await http.get(f"/threads/{threads[0]['id']}", headers=auth)).json()
        states = (await http.get(f"/threads/{threads[0]['id']}/states", headers=auth)).json()
        events = (await http.get(f"/threads/{threads[0]['id']}/events", headers=auth)).json()
        print(f"\nthread detail: {len(detail['messages'])} messages, {len(detail['runs'])} run(s), "
              f"thread_usage llm_calls={detail['thread_usage'].get('llm_calls')}; "
              f"{len(states)} AgentState snapshots; {len(events)} stored events")
        usage = (await http.get("/usage/me", params={"group_by": "role"}, headers=auth)).json()
        print("usage/me:", {k: usage["runs"][k] for k in ("requests", "succeeded", "p50_seconds")},
              {k: usage["tokens"][k] for k in ("llm_calls", "input_tokens", "output_tokens", "reasoning_tokens")})
        print("  by role:", [(g["key"], g["llm_calls"], g["input_tokens"]) for g in usage["groups"]])
        convs = (await http.get("/conversations", headers=auth)).json()["items"]
        print("conversations:", [(c["title"], c["title_source"], c["thread_count"]) for c in convs])

        # ---- replay on a fresh socket
        async with websockets.connect(ws_url, max_size=None) as ws:
            await ws.send(json.dumps({"type": "auth", "token": tokens["access_token"]}))
            await ws.recv()
            await ws.send(json.dumps({"type": "subscribe", "thread_id": threads[0]["id"], "after_id": 0}))
            replayed = 0
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("replay"):
                    replayed += 1
                if msg["type"] == "replay_done":
                    break
            print("replay on new socket:", replayed, "events")

        # ---- logout revokes the access token
        await http.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=auth)
        print("after logout, /auth/me ->", (await http.get("/auth/me", headers=auth)).status_code)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    asyncio.run(main(ap.parse_args().base))
