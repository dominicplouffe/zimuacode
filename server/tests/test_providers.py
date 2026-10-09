import json
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.tasks.providers import (
    PROVIDERS,
    ClaudeCode,
    Codex,
    CodexParser,
    DispatchParser,
    TurnContext,
)
from tests.helpers import events, start, wait_for


class FakeTask:
    branch = "zimua/x"
    base_branch = "main"
    model: str | None = "gpt-5"
    session_id: str | None = "thread-1"


def ctx(
    tmp_path: Path, first_turn: bool, credential: str | None = None, **settings: Any
) -> TurnContext:
    return TurnContext(
        settings=Settings(codex_bin="codex", claude_bin="claude"),
        task=FakeTask(),
        first_turn=first_turn,
        user_settings=settings,
        credential=credential,
        home=tmp_path,
    )


def test_codex_command_and_resume(tmp_path: Path) -> None:
    codex = Codex()
    first = codex.command(ctx(tmp_path, True))
    assert first[:2] == ["codex", "exec"]
    assert "--dangerously-bypass-approvals-and-sandbox" in first
    assert "resume" not in first
    assert first[-1] == "-"
    later = codex.command(ctx(tmp_path, False))
    assert later[-3:] == ["resume", "thread-1", "-"]
    assert later[later.index("--model") + 1] == "gpt-5"
    # The IDE's rules ride along with the first message only.
    assert "zimua/x" in codex.prompt(ctx(tmp_path, True), "do it")
    assert codex.prompt(ctx(tmp_path, False), "more") == "more"


def test_codex_credentials(tmp_path: Path) -> None:
    codex = Codex()
    assert codex.env(ctx(tmp_path, True, "sk-proj-123"))["OPENAI_API_KEY"] == "sk-proj-123"
    auth = json.dumps({"tokens": {"refresh_token": "r1"}})
    codex.setup_home(ctx(tmp_path, True, auth))
    login = tmp_path / ".codex" / "auth.json"
    assert login.read_text() == auth
    assert login.stat().st_mode & 0o777 == 0o600
    # Codex refreshes the file itself; the saved credential mustn't clobber that.
    login.write_text('{"refreshed": true}')
    codex.setup_home(ctx(tmp_path, False, auth))
    assert login.read_text() == '{"refreshed": true}'
    # A newly saved credential does replace it.
    codex.setup_home(ctx(tmp_path, False, json.dumps({"new": 1})))
    assert json.loads(login.read_text()) == {"new": 1}


def test_claude_api_key_vs_token(tmp_path: Path) -> None:
    assert ClaudeCode().env(ctx(tmp_path, True, "sk-ant-api03-x")) == {
        "ANTHROPIC_API_KEY": "sk-ant-api03-x"
    }
    assert ClaudeCode().env(ctx(tmp_path, True, "sk-ant-oat01-x")) == {
        "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-x"
    }


def test_codex_parser() -> None:
    p = CodexParser()
    lines = [
        '{"type":"thread.started","thread_id":"th1"}',
        '{"type":"turn.started"}',
        '{"type":"item.started","item":{"id":"i1","type":"command_execution","command":"ls","status":"in_progress"}}',
        '{"type":"item.completed","item":{"id":"i1","type":"command_execution","command":"ls","aggregated_output":"a\\n","exit_code":0,"status":"completed"}}',
        '{"type":"item.updated","item":{"id":"i2","type":"todo_list","items":[{"text":"x","completed":true}]}}',
        '{"type":"item.completed","item":{"id":"i3","type":"mcp_tool_call","server":"gh","tool":"search","arguments":{"q":"x"},"result":{"content":[{"type":"text","text":"found"}]},"error":null,"status":"completed"}}',
        '{"type":"item.completed","item":{"id":"i4","type":"agent_message","text":"Done."}}',
        '{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":5,"output_tokens":3}}',
        '{"type":"turn.failed","error":{"message":"stream disconnected"}}',
    ]
    out = [e for line in lines for e in p.parse(line)]
    assert [t for t, _ in out] == [
        "command", "todo", "tool_call", "tool_result", "assistant_text", "usage", "error",
    ]  # fmt: skip
    assert out[0][1] == {"id": "i1", "command": "ls", "output": "a\n", "exit_code": 0}
    assert out[2][1]["name"] == "gh.search"
    assert out[3][1] == {"id": "i3", "output": "found", "is_error": False}
    assert p.result.session_id == "th1"
    assert (p.result.input_tokens, p.result.output_tokens, p.result.failed) == (10, 3, True)


def test_dispatch_parser() -> None:
    p = DispatchParser(
        r"https://claude\.ai/code/((?:session|cse)_[A-Za-z0-9]+)", "Claude", {"MARK": "Marked"}
    )
    assert p.parse("noise") == [("log", {"text": "noise"})]
    started = p.parse("see https://claude.ai/code/session_ABC now")
    assert started[1] == ("link", {"url": "https://claude.ai/code/session_ABC"})
    assert p.result.session_id == "session_ABC"
    assert p.parse("MARK") == [("assistant_text", {"text": "Marked"})]
    assert p.parse('{"ok": false, "error": "not enabled"}') == [
        ("error", {"message": "not enabled"})
    ]
    assert p.result.failed


def test_every_provider_is_listed(app_client: TestClient) -> None:
    listed = {p["id"]: p for p in app_client.get("/api/providers").json()}
    assert set(listed) == set(PROVIDERS)
    assert listed["codex-cloud"]["experimental"] is True
    assert listed["codex"]["capabilities"]["runs_on"] == "self"


def test_codex_task_end_to_end(app_client: TestClient) -> None:
    task_id = start(app_client, "Add codex notes", provider="codex")
    task = wait_for(app_client, task_id, "idle", "failed")
    assert task["status"] == "idle", [
        e for e in events(app_client, task_id) if e["type"] in ("error", "log")
    ]
    assert task["input_tokens"] == 1000 and task["output_tokens"] == 50
    texts = [
        e["data"]["text"] for e in events(app_client, task_id) if e["type"] == "assistant_text"
    ]
    assert texts == ["Started: Add codex notes"]

    app_client.post(f"/api/tasks/{task_id}/messages", json={"text": "More"})
    wait_for(app_client, task_id, "idle")
    texts = [
        e["data"]["text"] for e in events(app_client, task_id) if e["type"] == "assistant_text"
    ]
    assert texts[-1] == "Resumed: More"
    changes = app_client.get(f"/api/tasks/{task_id}/changes").json()
    assert changes == [{"path": "CODEX.md", "status": "A"}]


def test_codex_cloud_hand_off_and_fetch(app_client: TestClient) -> None:
    app_client.put("/api/settings", json={"raw": '{"ai.codexCloudEnvironment": "env_1"}'})
    task_id = start(app_client, "Do it in the cloud", provider="codex-cloud")
    wait_for(app_client, task_id, "idle", "failed")
    links = [e["data"]["url"] for e in events(app_client, task_id) if e["type"] == "link"]
    assert links == ["https://chatgpt.com/codex/tasks/task_e_fake123"]
    assert app_client.get(f"/api/tasks/{task_id}/changes").json() == []

    app_client.post(f"/api/tasks/{task_id}/messages", json={"text": "fetch"})
    deadline = time.monotonic() + 10
    while (
        app_client.get(f"/api/tasks/{task_id}/changes").json() == [] and time.monotonic() < deadline
    ):
        time.sleep(0.1)
    wait_for(app_client, task_id, "idle")
    assert app_client.get(f"/api/tasks/{task_id}/changes").json() == [
        {"path": "CLOUD.md", "status": "A"}
    ]

    app_client.post(f"/api/tasks/{task_id}/messages", json={"text": "again"})
    time.sleep(0.5)
    wait_for(app_client, task_id, "idle")
    texts = [
        e["data"]["text"] for e in events(app_client, task_id) if e["type"] == "assistant_text"
    ]
    assert "already in this workspace" in texts[-1]


def test_codex_cloud_needs_an_environment(app_client: TestClient) -> None:
    task_id = start(app_client, "x", provider="codex-cloud")
    wait_for(app_client, task_id, "failed", "idle")
    texts = [
        e["data"]["text"] for e in events(app_client, task_id) if e["type"] == "assistant_text"
    ]
    assert "ai.codexCloudEnvironment" in texts[0]


def test_claude_cloud_hand_off(app_client: TestClient) -> None:
    task_id = start(app_client, "Do it on the web", provider="claude-cloud")
    task = wait_for(app_client, task_id, "idle", "failed")
    assert task["status"] == "idle"
    links = [e["data"]["url"] for e in events(app_client, task_id) if e["type"] == "link"]
    assert links == ["https://claude.ai/code/session_FAKE42"]
    app_client.post(f"/api/tasks/{task_id}/messages", json={"text": "and tests"})
    time.sleep(0.5)
    wait_for(app_client, task_id, "idle")
    texts = [
        e["data"]["text"] for e in events(app_client, task_id) if e["type"] == "assistant_text"
    ]
    assert (
        texts[-1]
        == "Sent to Claude Code on the web. [Open it](https://claude.ai/code/session_FAKE42)"
    )
