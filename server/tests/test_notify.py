from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pywebpush import WebPushException

import app.notify as notify
from tests.helpers import start, wait_for

SUB = {
    "endpoint": "https://push.example.com/abc",
    "keys": {"p256dh": "BPkey", "auth": "authsecret"},
}


@pytest.fixture
def pushes(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def fake_webpush(subscription_info: dict[str, Any], data: str, **kwargs: Any) -> None:
        sent.append({"to": subscription_info["endpoint"], **__import__("json").loads(data)})

    monkeypatch.setattr(notify, "webpush", fake_webpush)
    return sent


def wait_pushes(pushes: list[dict[str, Any]], n: int) -> None:
    import time

    deadline = time.monotonic() + 5
    while len(pushes) < n and time.monotonic() < deadline:
        time.sleep(0.05)


def test_subscribe_and_get_notified_when_a_task_finishes(
    app_client: TestClient, pushes: list[dict[str, Any]]
) -> None:
    key = app_client.get("/api/push/key").json()["public_key"]
    assert len(key) == 87  # an uncompressed P-256 point, base64url without padding
    assert app_client.post("/api/push/subscriptions", json=SUB).status_code == 204
    assert (
        app_client.post(
            "/api/push/subscriptions", json={**SUB, "endpoint": "http://insecure"}
        ).status_code
        == 422
    )

    task_id = start(app_client, "Add notes")
    wait_for(app_client, task_id, "idle")
    wait_pushes(pushes, 1)
    assert pushes == [
        {
            "to": SUB["endpoint"],
            "title": "Agent finished",
            "body": "Add notes · octo/app",
            "url": f"http://ide.test/#task={task_id}",
            "tag": f"task-{task_id}",
        }
    ]

    failed = start(app_client, "fail")
    wait_for(app_client, failed, "failed")
    wait_pushes(pushes, 2)
    assert pushes[1]["title"] == "Agent failed"


def test_no_notifications_when_disabled(
    app_client: TestClient, pushes: list[dict[str, Any]]
) -> None:
    app_client.post("/api/push/subscriptions", json=SUB)
    app_client.put("/api/settings", json={"raw": '{"notifications.enabled": false}'})
    app_client.post("/api/push/test")
    wait_for(app_client, start(app_client, "Add notes"), "idle")
    wait_pushes(pushes, 1)
    assert pushes == []


def test_gone_subscriptions_are_removed(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def gone(subscription_info: dict[str, Any], **kwargs: Any) -> None:
        calls.append(subscription_info["endpoint"])
        raise WebPushException("gone", response=MagicMock(status_code=410))

    monkeypatch.setattr(notify, "webpush", gone)
    app_client.post("/api/push/subscriptions", json=SUB)
    app_client.post("/api/push/test")
    import time

    time.sleep(0.5)
    app_client.post("/api/push/test")
    time.sleep(0.5)
    assert calls == [SUB["endpoint"]]


async def test_ci_watch_notifies_on_failure(
    env: None, monkeypatch: pytest.MonkeyPatch, gh: Any
) -> None:
    import httpx

    from app.config import get_settings
    from app.db import init_db

    init_db()
    monkeypatch.setattr(notify, "CI_POLL_SECONDS", 0)
    notifier = notify.Notifier(get_settings())
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        notifier, "notify", lambda uid, title, body, url, tag=None: sent.append((title, body))
    )
    gh.get("/repos/octo/app/pulls/5").respond(json={"head": {"sha": "h1"}})
    runs = gh.get("/repos/octo/app/commits/h1/check-runs")
    runs.side_effect = [
        httpx.Response(200, json={"check_runs": [{"name": "test", "status": "in_progress"}]}),
        httpx.Response(200, json={"check_runs": [
            {"name": "test", "status": "completed", "conclusion": "failure"},
            {"name": "lint", "status": "completed", "conclusion": "success"},
        ]}),
    ]  # fmt: skip
    async with httpx.AsyncClient() as http:
        await notifier._watch_ci(1, http, "tok", "octo", "app", 5)
    assert sent == [("CI failed on PR #5", "octo/app: test")]
