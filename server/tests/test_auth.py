from urllib.parse import parse_qs, urlparse

import httpx
import respx
from fastapi.testclient import TestClient

from tests.conftest import GH_USER


def test_requires_login(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/repos").status_code == 401


def test_oauth_flow(client: TestClient, gh: respx.MockRouter) -> None:
    resp = client.get("/api/auth/login", follow_redirects=False)
    assert resp.status_code == 307
    query = parse_qs(urlparse(resp.headers["location"]).query)
    assert query["redirect_uri"] == ["http://ide.test/api/auth/callback"]
    state = query["state"][0]

    with respx.mock(assert_all_called=False) as oauth:
        oauth.post("https://github.test/login/oauth/access_token").respond(
            json={"access_token": "ghtok"}
        )
        oauth.get("https://api.github.test/user").respond(json=GH_USER)
        resp = client.get(
            "/api/auth/callback", params={"code": "c", "state": state}, follow_redirects=False
        )
    assert resp.status_code == 307
    assert resp.headers["location"] == "http://ide.test/"
    me = client.get("/api/auth/me").json()
    assert me["login"] == "octo"


def test_oauth_rejects_bad_state(client: TestClient) -> None:
    client.get("/api/auth/login", follow_redirects=False)
    resp = client.get("/api/auth/callback", params={"code": "c", "state": "forged"})
    assert resp.status_code == 400


def test_oauth_rejects_other_users(client: TestClient) -> None:
    resp = client.get("/api/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
    with respx.mock() as oauth:
        oauth.post("https://github.test/login/oauth/access_token").respond(
            json={"access_token": "t"}
        )
        oauth.get("https://api.github.test/user").respond(json={**GH_USER, "login": "mallory"})
        resp = client.get("/api/auth/callback", params={"code": "c", "state": state})
    assert resp.status_code == 403
    assert client.get("/api/auth/me").status_code == 401


def test_bearer_token_works(authed: TestClient) -> None:
    token = authed.cookies["zimua_session"]
    fresh = TestClient(authed.app, base_url="http://ide.test")
    resp = fresh.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_mutations_require_csrf_header(authed: TestClient) -> None:
    del authed.headers["x-zimua"]
    assert authed.put("/api/settings", json={"raw": "{}"}).status_code == 403


def test_token_is_encrypted_at_rest(authed: TestClient) -> None:
    from sqlmodel import Session, select

    from app.db import get_engine
    from app.models import User

    with Session(get_engine()) as s:
        user = s.exec(select(User)).one()
    assert "ghtok" not in user.token_enc


def test_github_401_is_passed_through(authed: TestClient, gh: respx.MockRouter) -> None:
    gh.get("/user/repos").mock(return_value=httpx.Response(401, json={"message": "Bad creds"}))
    resp = authed.get("/api/repos")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Bad creds"


def test_refuses_default_secret_in_production(env: None, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import pytest

    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("ZIMUA_COOKIE_SECURE", "true")
    monkeypatch.delenv("ZIMUA_SECRET_KEY")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="ZIMUA_SECRET_KEY"), TestClient(create_app()):
        pass
