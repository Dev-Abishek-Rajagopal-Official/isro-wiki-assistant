"""WebSocket handshake and protocol errors (Starlette TestClient on a separate app instance)."""

import uuid

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture(scope="module")
def tc(test_environment):
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _login(tc) -> tuple[str, dict]:
    email = f"ws-{uuid.uuid4().hex[:8]}@example.com"
    tc.post("/auth/register", json={"email": email, "full_name": "W", "password": "ws-pass-123"})
    token = tc.post("/auth/login", json={"email": email, "password": "ws-pass-123"}).json()["access_token"]
    return token, {"Authorization": f"Bearer {token}"}


def test_first_message_must_authenticate(tc):
    with tc.websocket_connect("/ws") as ws:
        ws.send_json({"type": "ask", "thread_id": "x", "question": "hi"})
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
    assert e.value.code == 4401


def test_bad_token_is_rejected(tc):
    with tc.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": "garbage"})
        assert ws.receive_json()["type"] == "auth_failed"
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
    assert e.value.code == 4401


def test_authenticated_protocol(tc):
    token, headers = _login(tc)
    _, other_headers = _login(tc)
    conv = tc.post("/conversations", json={}, headers=other_headers).json()
    foreign_thread = tc.post(f"/conversations/{conv['id']}/threads", json={}, headers=other_headers).json()
    own_conv = tc.post("/conversations", json={}, headers=headers).json()
    own_thread = tc.post(f"/conversations/{own_conv['id']}/threads", json={}, headers=headers).json()

    with tc.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "auth_ok"
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
        ws.send_json({"type": "ask", "thread_id": foreign_thread["id"], "question": "hi"})
        assert ws.receive_json()["data"]["error"] == "thread not found"        # other user's thread
        ws.send_json({"type": "ask", "thread_id": own_thread["id"], "question": "hi"})
        assert "agent unavailable" in ws.receive_json()["data"]["error"]        # agent disabled in tests
        ws.send_json({"type": "ask_audio", "thread_id": own_thread["id"], "audio_b64": "%%%"})
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "bogus"})
        assert "unknown message type" in ws.receive_json()["data"]["error"]
        ws.send_json({"type": "subscribe", "thread_id": own_thread["id"]})
        assert ws.receive_json()["type"] == "subscribed"
