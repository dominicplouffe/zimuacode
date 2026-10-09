"""A task outlives its PR: after a merge, follow-ups go to a new branch and a new PR."""

import json
from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient

from app.config import get_settings
from tests.helpers import _git, events, start, wait_for

URL = "https://github.com/octo/app/pull/"


def workspace(task_id: str) -> Path:
    return Path(get_settings().data_dir) / "tasks" / task_id / "repo"


def squash_merge(remote: Path, branch: str, tmp: Path, extra: dict[str, str] | None = None) -> str:
    """Squash-merges `branch` into main on the remote, like GitHub's button, then adds other
    people's work on top. Returns the new main SHA."""
    clone = tmp / f"merge-{branch.replace('/', '-')}"
    _git(tmp, "clone", "-q", str(remote), str(clone))
    who = ("-c", "user.name=m", "-c", "user.email=m@m")
    _git(clone, "merge", "--squash", f"origin/{branch}")
    _git(clone, *who, "commit", "-qm", f"Merge {branch} (squashed)")
    for path, content in (extra or {}).items():
        (clone / path).write_text(content)
        _git(clone, "add", path)
        _git(clone, *who, "commit", "-qm", f"Someone else changed {path}")
    _git(clone, "push", "-q", "origin", "main")
    return _git(remote, "rev-parse", "main").strip()


def pr(number: int, head_sha: str, state: str = "open", merged: bool = False) -> dict[str, Any]:
    return {
        "number": number,
        "state": state,
        "merged": merged,
        "merged_at": "2026-10-09T00:00:00Z" if merged else None,
        "html_url": f"{URL}{number}",
        "head": {"ref": "zimua/add-notes", "sha": head_sha},
        "base": {"ref": "main"},
    }


def publish(client: TestClient, task_id: str, title: str) -> dict[str, Any]:
    resp = client.post(f"/api/tasks/{task_id}/publish", json={"title": title})
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


def first_round(client: TestClient, gh: respx.MockRouter) -> tuple[str, str]:
    """A task whose work is published as PR 5. Returns (task id, pushed SHA)."""
    task_id = start(client, "Add notes")
    wait_for(client, task_id, "idle")
    gh.post("/repos/octo/app/pulls").respond(201, json={"number": 5, "html_url": f"{URL}5"})
    publish(client, task_id, "Add notes")
    return task_id, _git(workspace(task_id), "rev-parse", "HEAD").strip()


def test_follow_up_after_merge_starts_a_new_round(
    app_client: TestClient, gh: respx.MockRouter, remote: Path, tmp_path: Path
) -> None:
    task_id, pushed = first_round(app_client, gh)
    main = squash_merge(remote, "zimua/add-notes", tmp_path, {"OTHER.md": "theirs\n"})
    gh.get("/repos/octo/app/pulls/5").respond(json=pr(5, pushed, "closed", merged=True))

    app_client.post(f"/api/tasks/{task_id}/messages", json={"text": "Fix typo"})
    task = wait_for(app_client, task_id, "idle")
    assert task["round"] == 2
    assert task["previous_prs"] == [5]
    assert task["pr_number"] is None
    assert task["branch"] == f"zimua/task-{task_id[:6]}-r2"
    rounds = [e["data"] for e in events(app_client, task_id) if e["type"] == "round"]
    assert rounds == [{"previous_pr": 5, "base": "main", "round": 2}]

    # The agent worked on top of the latest main, other people's changes included, and
    # only its new change counts as this round's work.
    repo = workspace(task_id)
    assert (repo / "OTHER.md").read_text() == "theirs\n"
    assert (repo / "AGENT.md").read_text() == "Add notes\nFix typo\n"
    assert app_client.get(f"/api/tasks/{task_id}/changes").json() == [
        {"path": "AGENT.md", "status": "M"}
    ]

    route = gh.post("/repos/octo/app/pulls").respond(201, json={"number": 6, "html_url": f"{URL}6"})
    result = publish(app_client, task_id, "Fix typo in the notes")
    assert result == {"pr_number": 6, "url": f"{URL}6", "created": True}
    body = json.loads(route.calls.last.request.content)
    assert body["head"] == "zimua/fix-typo-notes"
    assert body["base"] == "main"
    # The new branch is main plus the fix, without replaying the merged commits.
    assert _git(remote, "merge-base", "main", "zimua/fix-typo-notes").strip() == main
    assert _git(remote, "log", "--format=%s", "main..zimua/fix-typo-notes").splitlines() == [
        "Fix typo in the notes"
    ]


def test_merge_found_at_publish_carries_newer_work(
    app_client: TestClient, gh: respx.MockRouter, remote: Path, tmp_path: Path
) -> None:
    task_id, pushed = first_round(app_client, gh)
    pull = gh.get("/repos/octo/app/pulls/5").respond(json=pr(5, pushed))
    # A follow-up while the PR is still open stays in this round...
    app_client.post(f"/api/tasks/{task_id}/messages", json={"text": "More notes"})
    wait_for(app_client, task_id, "idle")
    assert app_client.get(f"/api/tasks/{task_id}").json()["round"] == 1

    # ...then the PR is merged before that work is published.
    main = squash_merge(remote, "zimua/add-notes", tmp_path)
    pull.respond(json=pr(5, pushed, "closed", merged=True))
    gh.post("/repos/octo/app/pulls").respond(201, json={"number": 6, "html_url": f"{URL}6"})
    result = publish(app_client, task_id, "More notes")
    assert result["pr_number"] == 6 and result["created"] is True
    task = app_client.get(f"/api/tasks/{task_id}").json()
    assert task["branch"] == "zimua/more-notes"
    assert task["previous_prs"] == [5]
    assert _git(remote, "merge-base", "main", "zimua/more-notes").strip() == main
    assert _git(remote, "show", "zimua/more-notes:AGENT.md") == "Add notes\nMore notes\n"


def test_closed_without_merge_gets_a_new_pr_from_the_same_branch(
    app_client: TestClient, gh: respx.MockRouter
) -> None:
    task_id, pushed = first_round(app_client, gh)
    gh.get("/repos/octo/app/pulls/5").respond(json=pr(5, pushed, "closed"))
    app_client.post(f"/api/tasks/{task_id}/messages", json={"text": "Try again"})
    wait_for(app_client, task_id, "idle")
    route = gh.post("/repos/octo/app/pulls").respond(201, json={"number": 7, "html_url": f"{URL}7"})
    result = publish(app_client, task_id, "Try again")
    assert result["pr_number"] == 7
    assert json.loads(route.calls.last.request.content)["head"] == "zimua/add-notes"
    task = app_client.get(f"/api/tasks/{task_id}").json()
    assert (task["round"], task["previous_prs"]) == (1, [5])


def test_conflict_with_the_new_base_changes_nothing(
    app_client: TestClient, gh: respx.MockRouter, remote: Path, tmp_path: Path
) -> None:
    task_id, pushed = first_round(app_client, gh)
    pull = gh.get("/repos/octo/app/pulls/5").respond(json=pr(5, pushed))
    app_client.post(f"/api/tasks/{task_id}/messages", json={"text": "More notes"})
    wait_for(app_client, task_id, "idle")
    # Someone else rewrites the same lines in main after the merge.
    squash_merge(remote, "zimua/add-notes", tmp_path, {"AGENT.md": "Rewritten\n"})
    pull.respond(json=pr(5, pushed, "closed", merged=True))

    resp = app_client.post(f"/api/tasks/{task_id}/publish", json={"title": "More notes"})
    assert resp.status_code == 409
    assert "conflict with main in AGENT.md" in resp.json()["detail"]
    task = app_client.get(f"/api/tasks/{task_id}").json()
    assert (task["branch"], task["pr_number"], task["round"]) == ("zimua/add-notes", 5, 1)
    repo = workspace(task_id)
    assert (repo / "AGENT.md").read_text() == "Add notes\nMore notes\n"
    assert _git(repo, "status", "--porcelain").strip() == "M AGENT.md"


def test_branch_names_skip_filler_and_taken_names() -> None:
    from app.tasks.manager import branch_slug, unique_branch

    assert branch_slug("Do we support themes in this code?") == "support-themes-code"
    assert branch_slug("I need to support pasting images") == "support-pasting-images"
    assert branch_slug("Please make the header sticky on mobile") == "header-sticky-mobile"
    assert branch_slug("???") == "change"
    assert len(branch_slug("word " * 40)) <= 40
    assert unique_branch("x", set()) == "zimua/x"
    assert unique_branch("x", {"zimua/x", "zimua/x-2"}) == "zimua/x-3"


def test_published_names_avoid_existing_branches(
    app_client: TestClient, gh: respx.MockRouter, remote: Path, tmp_path: Path
) -> None:
    clone = tmp_path / "taken"
    _git(tmp_path, "clone", "-q", str(remote), str(clone))
    _git(clone, "push", "-q", "origin", "main:zimua/add-notes")
    task_id = start(app_client, "Add notes")
    wait_for(app_client, task_id, "idle")
    gh.post("/repos/octo/app/pulls").respond(201, json={"number": 5, "html_url": f"{URL}5"})
    publish(app_client, task_id, "Add notes")
    assert app_client.get(f"/api/tasks/{task_id}").json()["branch"] == "zimua/add-notes-2"


def test_existing_databases_get_the_new_columns(
    env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    from app import db

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE task (id VARCHAR PRIMARY KEY, user_id INTEGER, provider VARCHAR, "
            "title VARCHAR, repo_owner VARCHAR, repo_name VARCHAR, base_branch VARCHAR, "
            "branch VARCHAR, status VARCHAR, turn INTEGER, log_offset INTEGER, "
            "interrupt_requested BOOLEAN, pending JSON, cost_usd FLOAT, input_tokens INTEGER, "
            "output_tokens INTEGER, pr_number INTEGER, created_at DATETIME, updated_at DATETIME)"
        )
        conn.execute(
            "INSERT INTO task VALUES ('t1', 1, 'claude-code', 't', 'o', 'n', 'main', "
            "'zimua/old', 'idle', 1, 0, 0, '[]', 0, 0, 0, 3, '2026-01-01', '2026-01-01')"
        )
    monkeypatch.setenv("ZIMUA_DATABASE_URL", f"sqlite:///{path}")
    get_settings.cache_clear()
    db._engine = None
    db.init_db()
    from sqlmodel import Session

    from app.models import Task

    with Session(db.get_engine()) as s:
        task = s.get(Task, "t1")
        assert task is not None
        assert (task.previous_prs, task.round, task.branch_named, task.published_sha) == (
            [], 1, True, None,
        )  # fmt: skip
