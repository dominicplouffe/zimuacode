import json

import respx
from fastapi.testclient import TestClient

BASE = {"sha": "c1", "commit": {"tree": {"sha": "t1"}}}


def _mock_git(gh: respx.MockRouter) -> dict[str, respx.Route]:
    return {
        "base": gh.get("/repos/octo/app/commits/c1").respond(json=BASE),
        "tree": gh.post("/repos/octo/app/git/trees").respond(201, json={"sha": "t2"}),
        "commit": gh.post("/repos/octo/app/git/commits").respond(201, json={"sha": "c2"}),
        "create_ref": gh.post("/repos/octo/app/git/refs").respond(201, json={}),
        "update_ref": gh.patch("/repos/octo/app/git/refs/heads/feat/x").respond(200, json={}),
    }


def _body(**overrides: object) -> dict[str, object]:
    return {
        "branch": "feat/x",
        "expected_head": "c1",
        "message": "Fix bug",
        "changes": [
            {"path": "src/a.py", "content": "print(1)\n"},
            {"path": "old.txt", "content": None},
        ],
        **overrides,
    }


def test_commit_builds_tree_commit_and_fast_forwards(
    authed: TestClient, gh: respx.MockRouter
) -> None:
    routes = _mock_git(gh)
    resp = authed.post("/api/repos/octo/app/commits", json=_body())
    assert resp.status_code == 201
    assert resp.json() == {"sha": "c2", "branch": "feat/x"}

    tree = json.loads(routes["tree"].calls.last.request.content)
    assert tree["base_tree"] == "t1"
    assert tree["tree"] == [
        {"path": "src/a.py", "mode": "100644", "type": "blob", "content": "print(1)\n"},
        {"path": "old.txt", "mode": "100644", "type": "blob", "sha": None},
    ]
    commit = json.loads(routes["commit"].calls.last.request.content)
    assert commit == {"message": "Fix bug", "tree": "t2", "parents": ["c1"]}
    update = json.loads(routes["update_ref"].calls.last.request.content)
    assert update == {"sha": "c2", "force": False}
    assert not routes["create_ref"].called


def test_commit_to_new_branch_creates_it_first(authed: TestClient, gh: respx.MockRouter) -> None:
    routes = _mock_git(gh)
    resp = authed.post("/api/repos/octo/app/commits", json=_body(create_branch=True))
    assert resp.status_code == 201
    created = json.loads(routes["create_ref"].calls.last.request.content)
    assert created == {"ref": "refs/heads/feat/x", "sha": "c1"}


def test_moved_branch_is_a_conflict(authed: TestClient, gh: respx.MockRouter) -> None:
    routes = _mock_git(gh)
    routes["update_ref"].respond(422, json={"message": "Update is not a fast forward"})
    resp = authed.post("/api/repos/octo/app/commits", json=_body())
    assert resp.status_code == 409
    assert "Branch changed" in resp.json()["detail"]


def test_protected_branch_keeps_github_message(authed: TestClient, gh: respx.MockRouter) -> None:
    routes = _mock_git(gh)
    routes["update_ref"].respond(
        422,
        json={"message": "Protected branch update failed", "errors": [{"message": "Reviews"}]},
    )
    resp = authed.post("/api/repos/octo/app/commits", json=_body())
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Protected branch update failed: Reviews"


def test_rejects_empty_changes(authed: TestClient) -> None:
    resp = authed.post("/api/repos/octo/app/commits", json=_body(changes=[]))
    assert resp.status_code == 422
