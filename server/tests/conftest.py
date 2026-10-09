import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings
from tests.helpers import FAKE_AGENT, FAKE_CODEX, _git

GH = "https://api.github.test"
GH_USER = {"id": 42, "login": "octo", "name": "Octo Cat", "avatar_url": "https://a/x.png"}


@pytest.fixture
def env(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ZIMUA_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("ZIMUA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ZIMUA_GITHUB_API_URL", GH)
    monkeypatch.setenv("ZIMUA_GITHUB_OAUTH_URL", "https://github.test")
    monkeypatch.setenv("ZIMUA_GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("ZIMUA_GITHUB_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("ZIMUA_ALLOWED_GITHUB_LOGIN", "octo")
    monkeypatch.setenv("ZIMUA_PUBLIC_URL", "http://ide.test")
    monkeypatch.setenv("ZIMUA_DEV_LOGIN", "1")
    get_settings.cache_clear()
    db._engine = None
    yield
    get_settings.cache_clear()
    db._engine = None


@pytest.fixture
def gh(env: None) -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=GH, assert_all_called=False) as router:
        router.get("/user").respond(json=GH_USER)
        yield router


@pytest.fixture
def client(env: None) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app(), base_url="http://ide.test") as c:
        yield c


@pytest.fixture
def authed(client: TestClient, gh: respx.MockRouter) -> TestClient:
    assert client.post("/api/auth/dev-login", json={"token": "ghtok"}).status_code == 200
    client.headers["x-zimua"] = "1"
    return client


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A bare repo standing in for github.com/octo/app."""
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    (src / "README.md").write_text("# App\n")
    _git(src, "add", ".")
    _git(src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    bare = tmp_path / "git" / "octo" / "app.git"
    bare.parent.mkdir(parents=True)
    _git(tmp_path, "clone", "-q", "--bare", str(src), str(bare))
    return bare


@pytest.fixture
def runner_env(env: None, tmp_path: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZIMUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ZIMUA_GIT_URL_TEMPLATE", f"file://{tmp_path}/git/{{owner}}/{{name}}.git")
    monkeypatch.setenv("ZIMUA_CLAUDE_BIN", f"{sys.executable} {FAKE_AGENT}")
    monkeypatch.setenv("ZIMUA_CODEX_BIN", f"{sys.executable} {FAKE_CODEX}")
    get_settings.cache_clear()


@pytest.fixture
def app_client(runner_env: None, gh: respx.MockRouter) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app(), base_url="http://ide.test") as c:
        assert c.post("/api/auth/dev-login", json={"token": "ghtok"}).status_code == 200
        c.headers["x-zimua"] = "1"
        yield c
