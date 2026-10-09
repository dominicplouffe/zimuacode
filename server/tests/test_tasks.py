import json
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings
from app.tasks.providers import ClaudeParser

FAKE_AGENT = Path(__file__).with_name("fake_agent.py")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


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
    get_settings.cache_clear()


@pytest.fixture
def app_client(runner_env: None, gh: respx.MockRouter) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app(), base_url="http://ide.test") as c:
        assert c.post("/api/auth/dev-login", json={"token": "ghtok"}).status_code == 200
        c.headers["x-zimua"] = "1"
        yield c


def wait_for(
    client: TestClient, task_id: str, *statuses: str, timeout: float = 20
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] in statuses:
            return task
        time.sleep(0.1)
    raise AssertionError(f"task stayed {task['status']}, wanted {statuses}")


def events(client: TestClient, task_id: str) -> list[dict[str, Any]]:
    from app.tasks.events import EventBus

    return EventBus().history(task_id)


def start(client: TestClient, prompt: str) -> str:
    resp = client.post(
        "/api/tasks",
        json={"provider": "claude-code", "owner": "octo", "name": "app",
              "base_branch": "main", "prompt": prompt},
    )  # fmt: skip
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


def test_task_runs_and_streams_normalized_events(app_client: TestClient) -> None:
    task_id = start(app_client, "Add notes")
    task = wait_for(app_client, task_id, "idle", "failed")
    assert task["status"] == "idle"
    assert task["branch"].startswith("zimua/add-notes-")
    assert task["cost_usd"] == pytest.approx(0.01)
    assert task["input_tokens"] == 150

    types = [e["type"] for e in events(app_client, task_id)]
    assert types[0] == "user_message"
    for expected in ("thinking", "assistant_text", "tool_call", "tool_result", "usage", "log"):
        assert expected in types
    assert types[-1] == "status"

    changes = app_client.get(f"/api/tasks/{task_id}/changes").json()
    assert changes == [{"path": "AGENT.md", "status": "A"}]
    working = app_client.get(f"/api/tasks/{task_id}/file", params={"path": "AGENT.md"}).json()
    assert working["content"] == "Add notes\n"
    base = app_client.get(
        f"/api/tasks/{task_id}/file", params={"path": "AGENT.md", "side": "base"}
    ).json()
    assert base["exists"] is False


def test_follow_up_resumes_the_same_session(app_client: TestClient) -> None:
    task_id = start(app_client, "first")
    first = wait_for(app_client, task_id, "idle")
    app_client.post(f"/api/tasks/{task_id}/messages", json={"text": "second"})
    second = wait_for(app_client, task_id, "idle")
    texts = [
        e["data"]["text"] for e in events(app_client, task_id) if e["type"] == "assistant_text"
    ]
    assert texts == ["Started: first", "Resumed: second"]
    assert first["id"] == second["id"]


def test_messages_sent_while_running_are_queued(app_client: TestClient) -> None:
    task_id = start(app_client, "sleep 1.5")
    wait_for(app_client, task_id, "running")
    resp = app_client.post(f"/api/tasks/{task_id}/messages", json={"text": "after"})
    assert resp.json()["pending"] == ["after"]
    wait_for(app_client, task_id, "idle")
    task = wait_for(app_client, task_id, "idle")
    deadline = time.monotonic() + 10
    while (
        "Resumed: after" not in [e["data"].get("text") for e in events(app_client, task_id)]
        and time.monotonic() < deadline
    ):
        time.sleep(0.1)
    queued = [e for e in events(app_client, task_id) if e["type"] == "user_message"]
    assert queued[1]["data"] == {"text": "after", "queued": True}
    assert task["pending"] == []


def test_interrupt(app_client: TestClient) -> None:
    task_id = start(app_client, "sleep 30")
    wait_for(app_client, task_id, "running")
    # Wait until the agent has produced output, so it's really running.
    deadline = time.monotonic() + 10
    while "assistant_text" not in [e["type"] for e in events(app_client, task_id)]:
        assert time.monotonic() < deadline
        time.sleep(0.1)
    assert app_client.post(f"/api/tasks/{task_id}/interrupt").status_code == 202
    task = wait_for(app_client, task_id, "interrupted", "failed", "idle", timeout=10)
    assert task["status"] == "interrupted"
    assert app_client.post(f"/api/tasks/{task_id}/interrupt").status_code == 409


def test_failed_turn(app_client: TestClient) -> None:
    task_id = start(app_client, "fail")
    task = wait_for(app_client, task_id, "failed", "idle")
    assert task["status"] == "failed"
    errors = [e["data"]["message"] for e in events(app_client, task_id) if e["type"] == "error"]
    assert errors == ["Something broke"]


def test_turn_survives_server_restart(runner_env: None, gh: respx.MockRouter) -> None:
    from app.main import create_app

    with TestClient(create_app(), base_url="http://ide.test") as c:
        c.post("/api/auth/dev-login", json={"token": "ghtok"})
        c.headers["x-zimua"] = "1"
        task_id = start(c, "sleep 2")
        wait_for(c, task_id, "running")
    # The server is down; the agent keeps going. A new server picks the turn back up.
    db._engine = None
    with TestClient(create_app(), base_url="http://ide.test") as c:
        c.post("/api/auth/dev-login", json={"token": "ghtok"})
        task = wait_for(c, task_id, "idle", "failed", timeout=20)
        assert task["status"] == "idle"
        assert [e["type"] for e in events(c, task_id)].count("usage") == 1


def test_publish_pushes_branch_and_opens_pr(
    app_client: TestClient, gh: respx.MockRouter, remote: Path
) -> None:
    task_id = start(app_client, "Add notes")
    task = wait_for(app_client, task_id, "idle")
    route = gh.post("/repos/octo/app/pulls").respond(
        201, json={"number": 5, "html_url": "https://github.com/octo/app/pull/5"}
    )
    resp = app_client.post(f"/api/tasks/{task_id}/publish", json={"title": "Add notes"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "pr_number": 5,
        "url": "https://github.com/octo/app/pull/5",
        "created": True,
    }
    body = json.loads(route.calls.last.request.content)
    assert body["head"] == task["branch"]
    assert body["base"] == "main"
    # The branch landed on the remote with the agent's file.
    assert _git(remote, "show", f"{task['branch']}:AGENT.md") == "Add notes\n"
    log = _git(remote, "log", "-1", "--format=%an <%ae>|%s", task["branch"])
    assert log == "Octo Cat <42+octo@users.noreply.github.com>|Add notes\n"
    # The workspace never stored the token.
    assert (
        "ghtok"
        not in (
            Path(get_settings().data_dir) / "tasks" / task_id / "repo" / ".git" / "config"
        ).read_text()
    )

    # Publishing again pushes to the same PR.
    gh.get("/repos/octo/app/pulls/5").respond(
        json={"number": 5, "html_url": "https://github.com/octo/app/pull/5"}
    )
    app_client.post(f"/api/tasks/{task_id}/messages", json={"text": "more"})
    wait_for(app_client, task_id, "idle")
    again = app_client.post(f"/api/tasks/{task_id}/publish", json={"title": "More"}).json()
    assert again["created"] is False


def test_archive_removes_workspace(app_client: TestClient) -> None:
    task_id = start(app_client, "Add notes")
    wait_for(app_client, task_id, "idle")
    assert app_client.delete(f"/api/tasks/{task_id}").status_code == 204
    assert app_client.get(f"/api/tasks/{task_id}").json()["status"] == "stopped"
    assert not (Path(get_settings().data_dir) / "tasks" / task_id).exists()
    assert app_client.get("/api/tasks").json() == []
    assert app_client.post(f"/api/tasks/{task_id}/messages", json={"text": "x"}).status_code == 409


def test_file_endpoint_rejects_escapes(app_client: TestClient) -> None:
    task_id = start(app_client, "Add notes")
    wait_for(app_client, task_id, "idle")
    for path in ("../home/x", "/etc/passwd", ".git/config"):
        resp = app_client.get(f"/api/tasks/{task_id}/file", params={"path": path})
        assert resp.status_code == 400, path


async def test_event_stream_replays_then_follows_live(env: None) -> None:
    # The SSE endpoint is a thin wrapper over this; the web e2e tests cover the HTTP side.
    import asyncio

    from sqlmodel import Session

    from app.db import get_engine, init_db
    from app.models import Task
    from app.tasks.events import EventBus

    init_db()
    with Session(get_engine()) as s:
        s.add(Task(id="t1", user_id=1, provider="p", title="t", repo_owner="o", repo_name="n",
                   base_branch="main", branch="b"))  # fmt: skip
        s.commit()
    bus = EventBus()
    for i in range(3):
        bus.publish("t1", "log", {"text": str(i)})

    stream = bus.stream("t1", after=1)
    seen = [(await anext(stream))["seq"], (await anext(stream))["seq"]]
    pending = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0.05)
    bus.publish("t1", "log", {"text": "live"})
    bus.publish("t1", "log", {"text": "live 2"})
    seen.append((await asyncio.wait_for(pending, 2))["seq"])
    seen.append((await asyncio.wait_for(anext(stream), 2))["seq"])
    await stream.aclose()
    assert seen == [2, 3, 4, 5]
    assert bus._subscribers == {}


def test_credentials(app_client: TestClient) -> None:
    providers = {p["id"]: p for p in app_client.get("/api/providers").json()}
    assert providers["claude-code"]["configured"] is False
    secret = "sk-ant-oat-secret-value"
    assert (
        app_client.put("/api/providers/claude-code/credential", json={"value": secret}).status_code
        == 204
    )
    providers = {p["id"]: p for p in app_client.get("/api/providers").json()}
    assert providers["claude-code"]["configured"] is True
    assert secret not in json.dumps(providers)


def test_claude_parser() -> None:
    p = ClaudeParser()
    lines = [
        '{"type":"system","subtype":"init","session_id":"s1","model":"m"}',
        '{"type":"assistant","parent_tool_use_id":"toolu_parent","message":{"content":[{"type":"text","text":"from a subagent"}]}}',
        '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t","content":"'
        + "x" * 30000
        + '","is_error":true}]}}',
        '{"type":"result","subtype":"error_max_turns","is_error":true,"errors":["Reached max turns"],"total_cost_usd":0.5,"usage":{"input_tokens":1,"output_tokens":2}}',
        "not json",
        '{"type":"rate_limit_event"}',
    ]
    out = [e for line in lines for e in p.parse(line)]
    assert out[0] == ("assistant_text", {"text": "from a subagent", "subagent": True})
    assert out[1][0] == "tool_result" and out[1][1]["is_error"] is True
    assert len(out[1][1]["output"]) < 21000
    assert out[2][0] == "usage" and out[2][1]["cost_usd"] == 0.5
    assert out[3] == ("error", {"message": "Reached max turns"})
    assert out[4] == ("log", {"text": "not json"})
    assert len(out) == 5
    assert p.result.session_id == "s1"
    assert p.result.failed is True
