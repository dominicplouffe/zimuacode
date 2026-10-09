import base64
import json
import time
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings
from app.tasks.providers import ClaudeParser
from tests.helpers import PNG, _git, events, start, wait_for


def test_task_runs_and_streams_normalized_events(app_client: TestClient) -> None:
    task_id = start(app_client, "Add notes")
    task = wait_for(app_client, task_id, "idle", "failed")
    assert task["status"] == "idle"
    # A local placeholder until publishing names it after the PR title.
    assert task["branch"] == f"zimua/task-{task_id[:6]}"
    assert task["branch_named"] is False
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


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_pasted_images_reach_the_agent_and_the_transcript(app_client: TestClient) -> None:
    resp = app_client.post(
        "/api/tasks",
        json={"provider": "claude-code", "owner": "octo", "name": "app",
              "base_branch": "main", "prompt": "see", "images": [b64(PNG)]},
    )  # fmt: skip
    assert resp.status_code == 201, resp.text
    task_id = resp.json()["id"]
    wait_for(app_client, task_id, "idle")
    app_client.post(
        f"/api/tasks/{task_id}/messages", json={"text": "again", "images": [b64(PNG), b64(PNG)]}
    )
    wait_for(app_client, task_id, "running")
    wait_for(app_client, task_id, "idle")

    log = events(app_client, task_id)
    texts = [e["data"]["text"] for e in log if e["type"] == "assistant_text"]
    assert texts == ["Started: see [image/png]", "Resumed: again [image/png,image/png]"]
    sent = [e["data"] for e in log if e["type"] == "user_message"]
    assert [len(m["images"]) for m in sent] == [1, 2]
    served = app_client.get(f"/api/tasks/{task_id}/attachments/{sent[0]['images'][0]}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == PNG


def test_queued_follow_ups_keep_their_images(app_client: TestClient) -> None:
    task_id = start(app_client, "sleep 1.5")
    wait_for(app_client, task_id, "running")
    resp = app_client.post(
        f"/api/tasks/{task_id}/messages", json={"text": "after", "images": [b64(PNG)]}
    )
    assert resp.json()["pending"] == ["after"]
    wait_for(app_client, task_id, "idle")
    deadline = time.monotonic() + 10
    while "Resumed: after [image/png]" not in [
        e["data"].get("text") for e in events(app_client, task_id)
    ]:
        assert time.monotonic() < deadline
        time.sleep(0.1)


def test_bad_images_are_rejected(app_client: TestClient) -> None:
    task_id = start(app_client, "first")
    wait_for(app_client, task_id, "idle")
    url = f"/api/tasks/{task_id}/messages"
    for images in (["not base64!"], [b64(b"plain text")], [b64(PNG)] * 6):
        assert app_client.post(url, json={"text": "x", "images": images}).status_code == 422
    huge = b64(PNG + bytes(5 * 1024 * 1024))
    assert app_client.post(url, json={"text": "x", "images": [huge]}).status_code == 422
    assert app_client.get(f"/api/tasks/{task_id}/attachments/../../etc/passwd").status_code == 404
    assert app_client.get(f"/api/tasks/{task_id}/attachments/{'0' * 32}.png").status_code == 404


def test_hand_off_agents_refuse_images(app_client: TestClient) -> None:
    resp = app_client.post(
        "/api/tasks",
        json={"provider": "codex-cloud", "owner": "octo", "name": "app",
              "base_branch": "main", "prompt": "x", "images": [b64(PNG)]},
    )  # fmt: skip
    assert resp.status_code == 422
    assert "can't take images" in resp.json()["detail"]


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
    # Named from the PR title, not the task's placeholder.
    task = app_client.get(f"/api/tasks/{task_id}").json()
    assert task["branch"] == body["head"] == "zimua/add-notes"
    assert body["base"] == "main"
    # The branch landed on the remote with the agent's file.
    assert _git(remote, "show", "zimua/add-notes:AGENT.md") == "Add notes\n"
    log = _git(remote, "log", "-1", "--format=%an <%ae>|%s", "zimua/add-notes")
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


def test_task_on_an_existing_pr_branch(
    app_client: TestClient, gh: respx.MockRouter, remote: Path
) -> None:
    # The PR's branch exists on the remote.
    src = remote.parent / "fix-src"
    _git(remote.parent, "clone", "-q", str(remote), str(src))
    _git(src, "checkout", "-q", "-b", "feat/x")
    (src / "app.py").write_text("broken\n")
    _git(src, "add", ".")
    _git(src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "feat")
    _git(src, "push", "-q", "origin", "feat/x")

    pull = {
        "number": 9, "state": "open", "html_url": "https://github.com/octo/app/pull/9",
        "head": {"ref": "feat/x", "repo": {"full_name": "octo/app"}}, "base": {"ref": "main"},
    }  # fmt: skip
    gh.get("/repos/octo/app/pulls/9").respond(json=pull)
    resp = app_client.post(
        "/api/tasks",
        json={"provider": "claude-code", "owner": "octo", "name": "app",
              "base_branch": "feat/x", "prompt": "Fix CI", "pr_number": 9},
    )  # fmt: skip
    assert resp.status_code == 201, resp.text
    task = wait_for(app_client, resp.json()["id"], "idle")
    assert task["branch"] == "feat/x"
    assert task["pr_number"] == 9

    published = app_client.post(f"/api/tasks/{task['id']}/publish", json={"title": "Fix CI"}).json()
    assert published == {"pr_number": 9, "url": pull["html_url"], "created": False}
    assert _git(remote, "show", "feat/x:AGENT.md") == "Fix CI\n"
    assert _git(remote, "show", "feat/x:app.py") == "broken\n"


def test_pr_task_must_match_the_pr(app_client: TestClient, gh: respx.MockRouter) -> None:
    gh.get("/repos/octo/app/pulls/9").respond(
        json={
            "number": 9,
            "state": "open",
            "head": {"ref": "feat/x", "repo": {"full_name": "fork/app"}},
            "base": {"ref": "main"},
        }
    )
    body = {
        "provider": "claude-code",
        "owner": "octo",
        "name": "app",
        "prompt": "x",
        "pr_number": 9,
    }
    assert app_client.post("/api/tasks", json={**body, "base_branch": "main"}).status_code == 409
    assert app_client.post("/api/tasks", json={**body, "base_branch": "feat/x"}).status_code == 409


def test_usage(app_client: TestClient) -> None:
    empty = app_client.get("/api/usage").json()
    assert empty["total"]["tasks"] == 0
    for prompt in ("one", "two"):
        wait_for(app_client, start(app_client, prompt), "idle")
    usage = app_client.get("/api/usage").json()
    assert usage["total"] == {
        "key": "all", "tasks": 2, "cost_usd": pytest.approx(0.02), "input_tokens": 300, "output_tokens": 40,
    }  # fmt: skip
    assert [r["key"] for r in usage["by_provider"]] == ["claude-code"]
    assert [r["key"] for r in usage["by_repo"]] == ["octo/app"]
