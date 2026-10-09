"""Helpers shared by the runner tests (fixtures live in conftest.py)."""

import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

FAKE_AGENT = Path(__file__).with_name("fake_agent.py")
FAKE_CODEX = Path(__file__).with_name("fake_codex.py")


# A 1x1 PNG.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cfc0f01f0005000201a5f645400000000049454e44ae426082"
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


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


def start(client: TestClient, prompt: str, provider: str = "claude-code") -> str:
    resp = client.post(
        "/api/tasks",
        json={"provider": provider, "owner": "octo", "name": "app",
              "base_branch": "main", "prompt": prompt},
    )  # fmt: skip
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])
