"""Registration, login, token refresh/rotation, logout and revocation."""

import uuid


async def test_register_validation_and_duplicates(client):
    email = f"a-{uuid.uuid4().hex[:8]}@example.com"
    ok = await client.post("/auth/register", json={"email": email, "full_name": "Ann", "password": "abc12345"})
    assert ok.status_code == 201 and ok.json()["email"] == email and "password" not in ok.text
    dup = await client.post("/auth/register", json={"email": email.upper(), "full_name": "Ann", "password": "abc12345"})
    assert dup.status_code == 409                                    # case-insensitive uniqueness
    weak = await client.post("/auth/register", json={"email": f"x{email}", "full_name": "A", "password": "onlyletters"})
    assert weak.status_code == 422
    bad = await client.post("/auth/register", json={"email": "not-an-email", "full_name": "A", "password": "abc12345"})
    assert bad.status_code == 422


async def test_login_and_me(client, user_factory):
    headers, tokens, email = await user_factory()
    assert tokens["token_type"] == "bearer" and tokens["expires_in"] == 8 * 3600
    me = await client.get("/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["email"] == email and me.json()["last_login_at"]
    wrong = await client.post("/auth/login", json={"email": email, "password": "wrong-pass-1"})
    unknown = await client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong-pass-1"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]        # no user enumeration


async def test_protected_routes_need_a_valid_token(client):
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.get("/conversations", headers={"Authorization": "Bearer nonsense"})).status_code == 401


async def test_refresh_rotates_tokens(client, user_factory):
    _, tokens, _ = await user_factory()
    r1 = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r1.status_code == 200
    again = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert again.status_code == 401                                  # old refresh token is single-use
    new = r1.json()
    assert (await client.get("/auth/me", headers={"Authorization": f"Bearer {new['access_token']}"})).status_code == 200


async def test_logout_revokes_access_and_refresh(client, user_factory):
    headers, tokens, _ = await user_factory()
    assert (await client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]},
                              headers=headers)).status_code == 204
    assert (await client.get("/auth/me", headers=headers)).status_code == 401
    assert (await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401


async def test_logout_all_revokes_every_session(client, user_factory):
    headers, tokens, email = await user_factory()
    other = (await client.post("/auth/login", json={"email": email, "password": "secret-pass-1"})).json()
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    assert (await client.post("/auth/logout-all", headers=headers)).status_code == 204
    assert (await client.get("/auth/me", headers=headers)).status_code == 401
    assert (await client.post("/auth/refresh", json={"refresh_token": other["refresh_token"]})).status_code == 401
    # a fresh login afterwards works
    fresh = (await client.post("/auth/login", json={"email": email, "password": "secret-pass-1"})).json()
    assert (await client.get("/auth/me", headers={"Authorization": f"Bearer {fresh['access_token']}"})).status_code == 200
    del other_headers
