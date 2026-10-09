from fastapi.testclient import TestClient

from tests.helpers import events, start, wait_for

URL = "/api/repos/octo/app/agent-config"


def texts(client: TestClient, task_id: str) -> list[str]:
    return [e["data"]["text"] for e in events(client, task_id) if e["type"] == "assistant_text"]


def test_env_values_are_write_only(app_client: TestClient) -> None:
    assert app_client.get(URL).json() == {"env_keys": [], "setup_script": ""}
    resp = app_client.put(URL, json={"env": {"API_TOKEN": "s3cret", "DEBUG": "1"}})
    assert resp.json() == {"env_keys": ["API_TOKEN", "DEBUG"], "setup_script": ""}
    assert "s3cret" not in resp.text
    resp = app_client.put(URL, json={"env": {"DEBUG": None}, "setup_script": "npm ci"})
    assert resp.json() == {"env_keys": ["API_TOKEN"], "setup_script": "npm ci"}
    assert app_client.put(URL, json={"env": {"1BAD": "x"}}).status_code == 422
    assert app_client.put(URL, json={"env": {"PATH": "x"}}).status_code == 422


def test_agent_sees_repo_env_but_not_server_secrets(app_client: TestClient) -> None:
    app_client.put(URL, json={"env": {"API_TOKEN": "s3cret"}})
    task_id = start(app_client, "env API_TOKEN")
    wait_for(app_client, task_id, "idle")
    assert texts(app_client, task_id)[-1] == "API_TOKEN=s3cret"

    app_client.post(f"/api/tasks/{task_id}/messages", json={"text": "env ZIMUA_SECRET_KEY"})
    wait_for(app_client, task_id, "idle")
    assert texts(app_client, task_id)[-1] == "ZIMUA_SECRET_KEY=None"


def test_setup_script_runs_before_the_agent(app_client: TestClient) -> None:
    app_client.put(
        URL,
        json={
            "env": {"GREETING": "hi"},
            "setup_script": 'echo "setting up $GREETING"\ntouch .ready',
        },
    )
    task_id = start(app_client, "Add notes")
    task = wait_for(app_client, task_id, "idle", "failed")
    assert task["status"] == "idle"
    setup = [
        e["data"]["text"] for e in events(app_client, task_id) if e["data"].get("source") == "setup"
    ]
    assert setup == ["setting up hi"]
    changes = {c["path"] for c in app_client.get(f"/api/tasks/{task_id}/changes").json()}
    assert ".ready" in changes


def test_failing_setup_script_fails_the_task(app_client: TestClient) -> None:
    app_client.put(URL, json={"setup_script": "echo broken\nfalse\necho never"})
    task_id = start(app_client, "Add notes")
    task = wait_for(app_client, task_id, "failed", "idle")
    assert task["status"] == "failed"
    logs = [e["data"]["text"] for e in events(app_client, task_id) if e["type"] == "log"]
    assert logs == ["broken"]
    errors = [e["data"]["message"] for e in events(app_client, task_id) if e["type"] == "error"]
    assert errors == ["The setup script exited with code 1."]
