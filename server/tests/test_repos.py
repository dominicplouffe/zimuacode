import json

import respx
from fastapi.testclient import TestClient

REPO = {
    "owner": {"login": "octo"},
    "name": "app",
    "full_name": "octo/app",
    "private": True,
    "default_branch": "main",
    "description": None,
    "pushed_at": "2026-01-01T00:00:00Z",
}


def test_list_repos(authed: TestClient, gh: respx.MockRouter) -> None:
    route = gh.get("/user/repos").respond(json=[REPO])
    assert authed.get("/api/repos").json()[0]["full_name"] == "octo/app"
    assert route.calls.last.request.headers["authorization"] == "Bearer ghtok"


def test_tree_resolves_ref_to_commit(authed: TestClient, gh: respx.MockRouter) -> None:
    gh.get("/repos/octo/app/commits/feature%2Fx").respond(
        json={"sha": "c1", "commit": {"tree": {"sha": "t1"}}}
    )
    gh.get("/repos/octo/app/git/trees/t1").respond(
        json={
            "sha": "t1",
            "truncated": False,
            "tree": [
                {"path": "src", "type": "tree"},
                {"path": "src/main.py", "type": "blob", "size": 12},
            ],
        }
    )
    tree = authed.get("/api/repos/octo/app/tree", params={"ref": "feature/x"}).json()
    assert tree["commit_sha"] == "c1"
    assert [e["path"] for e in tree["entries"]] == ["src", "src/main.py"]


def test_create_branch(authed: TestClient, gh: respx.MockRouter) -> None:
    route = gh.post("/repos/octo/app/git/refs").respond(201, json={})
    resp = authed.post("/api/repos/octo/app/branches", json={"name": "feat/x", "from_sha": "c1"})
    assert resp.status_code == 201
    assert json.loads(route.calls.last.request.content) == {
        "ref": "refs/heads/feat/x",
        "sha": "c1",
    }


def test_delete_branch(authed: TestClient, gh: respx.MockRouter) -> None:
    gh.get("/repos/octo/app").respond(json=REPO)
    route = gh.delete("/repos/octo/app/git/refs/heads/feat/x").respond(204)
    resp = authed.delete("/api/repos/octo/app/branches", params={"branch": "feat/x"})
    assert resp.status_code == 204
    assert route.called


def test_refuses_to_delete_default_branch(authed: TestClient, gh: respx.MockRouter) -> None:
    gh.get("/repos/octo/app").respond(json=REPO)
    resp = authed.delete("/api/repos/octo/app/branches", params={"branch": "main"})
    assert resp.status_code == 409


def test_file_text_and_binary(authed: TestClient, gh: respx.MockRouter) -> None:
    gh.get("/repos/octo/app/contents/src/main.py").respond(content=b"print('hi')\n")
    gh.get("/repos/octo/app/contents/logo.png").respond(content=b"\x89PNG\x00\x00")
    text = authed.get("/api/repos/octo/app/file", params={"path": "src/main.py", "ref": "main"})
    assert text.json()["content"] == "print('hi')\n"
    binary = authed.get("/api/repos/octo/app/file", params={"path": "logo.png", "ref": "main"})
    assert binary.json()["binary"] is True
    assert binary.json()["content"] is None


def test_branches_paginate(authed: TestClient, gh: respx.MockRouter) -> None:
    page1 = [{"name": f"b{i}", "commit": {"sha": "s"}, "protected": False} for i in range(100)]
    page2 = [{"name": "last", "commit": {"sha": "s"}, "protected": True}]
    gh.get("/repos/octo/app/branches", params={"page": "1"}).respond(json=page1)
    gh.get("/repos/octo/app/branches", params={"page": "2"}).respond(json=page2)
    branches = authed.get("/api/repos/octo/app/branches").json()
    assert len(branches) == 101
    assert branches[-1] == {"name": "last", "sha": "s", "protected": True}


def test_github_404(authed: TestClient, gh: respx.MockRouter) -> None:
    gh.get("/repos/octo/nope").respond(404, json={"message": "Not Found"})
    assert authed.get("/api/repos/octo/nope").status_code == 404
