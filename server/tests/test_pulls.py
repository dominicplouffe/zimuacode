import json

import respx
from fastapi.testclient import TestClient


def _pr(number: int = 7, **overrides: object) -> dict[str, object]:
    return {
        "number": number,
        "title": "Add checkout",
        "state": "open",
        "draft": False,
        "merged_at": None,
        "user": {"login": "octo"},
        "head": {"ref": "feat/x", "sha": "h1", "repo": {"full_name": "octo/app"}},
        "base": {"ref": "main", "sha": "b1"},
        "updated_at": "2026-10-01T00:00:00Z",
        "html_url": "https://github.com/octo/app/pull/7",
        "body": "Adds **checkout**",
        "mergeable": True,
        "mergeable_state": "clean",
        "additions": 10,
        "deletions": 2,
        "changed_files": 1,
        **overrides,
    }


def test_list_pulls_filters_by_branch(authed: TestClient, gh: respx.MockRouter) -> None:
    route = gh.get("/repos/octo/app/pulls").respond(json=[_pr()])
    pulls = authed.get("/api/repos/octo/app/pulls", params={"head": "feat/x"}).json()
    assert pulls[0]["head_ref"] == "feat/x"
    assert pulls[0]["merged"] is False
    assert route.calls.last.request.url.params["head"] == "octo:feat/x"
    assert route.calls.last.request.url.params["state"] == "open"


def test_get_pull(authed: TestClient, gh: respx.MockRouter) -> None:
    gh.get("/repos/octo/app/pulls/7").respond(json=_pr())
    gh.get("/repos/octo/app/compare/b1...h1").respond(json={"merge_base_commit": {"sha": "mb"}})
    pull = authed.get("/api/repos/octo/app/pulls/7").json()
    assert pull["base_sha"] == "b1"
    assert pull["merge_base_sha"] == "mb"
    assert pull["mergeable"] is True
    assert pull["head_repo"] == "octo/app"


def test_pull_files(authed: TestClient, gh: respx.MockRouter) -> None:
    gh.get("/repos/octo/app/pulls/7/files").respond(
        json=[
            {"filename": "a.py", "status": "modified", "additions": 1, "deletions": 1},
            {"filename": "b.py", "status": "renamed", "previous_filename": "old.py"},
        ]
    )
    files = authed.get("/api/repos/octo/app/pulls/7/files").json()
    assert files[1] == {
        "filename": "b.py",
        "status": "renamed",
        "previous_filename": "old.py",
        "additions": 0,
        "deletions": 0,
    }


def test_timeline_merges_and_sorts(authed: TestClient, gh: respx.MockRouter) -> None:
    gh.get("/repos/octo/app/issues/7/comments").respond(
        json=[
            {
                "id": 1,
                "user": {"login": "a"},
                "body": "second",
                "created_at": "2026-10-02T00:00:00Z",
                "html_url": "u1",
            }
        ]
    )
    gh.get("/repos/octo/app/pulls/7/comments").respond(
        json=[
            {
                "id": 2,
                "user": {"login": "b"},
                "body": "third",
                "created_at": "2026-10-03T00:00:00Z",
                "html_url": "u2",
                "path": "a.py",
                "line": 4,
            }
        ]
    )
    gh.get("/repos/octo/app/pulls/7/reviews").respond(
        json=[
            {
                "id": 3,
                "user": {"login": "c"},
                "body": "",
                "state": "APPROVED",
                "submitted_at": "2026-10-01T00:00:00Z",
                "html_url": "u3",
            },
            {"id": 4, "user": {"login": "c"}, "state": "PENDING", "html_url": "u4"},
        ]
    )
    items = authed.get("/api/repos/octo/app/pulls/7/timeline").json()
    assert [(i["kind"], i["author"]) for i in items] == [
        ("review", "c"),
        ("comment", "a"),
        ("review_comment", "b"),
    ]
    assert items[0]["state"] == "APPROVED"
    assert items[2]["path"] == "a.py"
    assert items[2]["line"] == 4


def test_create_pull(authed: TestClient, gh: respx.MockRouter) -> None:
    route = gh.post("/repos/octo/app/pulls").respond(201, json=_pr())
    resp = authed.post(
        "/api/repos/octo/app/pulls",
        json={"title": "Add checkout", "head": "feat/x", "base": "main", "draft": True},
    )
    assert resp.status_code == 201
    assert json.loads(route.calls.last.request.content) == {
        "title": "Add checkout",
        "head": "feat/x",
        "base": "main",
        "body": "",
        "draft": True,
    }


def test_merge_and_merge_errors(authed: TestClient, gh: respx.MockRouter) -> None:
    route = gh.put("/repos/octo/app/pulls/7/merge").respond(
        json={"merged": True, "sha": "m1", "message": "Pull Request successfully merged"}
    )
    resp = authed.put("/api/repos/octo/app/pulls/7/merge", json={"method": "squash"})
    assert resp.json()["merged"] is True
    assert json.loads(route.calls.last.request.content) == {"merge_method": "squash"}

    route.respond(405, json={"message": "Pull Request is not mergeable"})
    resp = authed.put("/api/repos/octo/app/pulls/7/merge", json={"method": "merge"})
    assert resp.status_code == 405
    assert resp.json()["detail"] == "Pull Request is not mergeable"


def test_checks_normalize_runs_and_statuses(authed: TestClient, gh: respx.MockRouter) -> None:
    gh.get("/repos/octo/app/commits/h1/check-runs").respond(
        json={
            "check_runs": [
                {
                    "id": 11,
                    "name": "test",
                    "status": "completed",
                    "conclusion": "failure",
                    "html_url": "https://github.com/run/11",
                    "app": {"slug": "github-actions"},
                },
                {
                    "id": 12,
                    "name": "Vercel",
                    "status": "in_progress",
                    "conclusion": None,
                    "details_url": "https://vercel.com/x",
                    "app": {"slug": "vercel"},
                },
            ]
        }
    )
    gh.get("/repos/octo/app/commits/h1/status").respond(
        json={
            "statuses": [
                {"id": 21, "context": "ci/legacy", "state": "pending", "target_url": None},
                {"id": 22, "context": "coverage", "state": "error", "target_url": "https://c"},
            ]
        }
    )
    checks = authed.get("/api/repos/octo/app/checks", params={"ref": "h1"}).json()
    by_name = {c["name"]: c for c in checks}
    assert [c["name"] for c in checks] == ["ci/legacy", "coverage", "test", "Vercel"]
    assert by_name["test"]["has_logs"] is True
    assert by_name["Vercel"]["has_logs"] is False
    assert by_name["Vercel"]["url"] == "https://vercel.com/x"
    assert by_name["ci/legacy"]["status"] == "in_progress"
    assert by_name["ci/legacy"]["conclusion"] is None
    assert by_name["coverage"]["conclusion"] == "failure"


def test_logs_follow_redirect_without_leaking_token(
    authed: TestClient, gh: respx.MockRouter
) -> None:
    gh.get("/repos/octo/app/actions/jobs/11/logs").respond(
        302, headers={"location": "https://blob.test/logs/11"}
    )
    blob = gh.get("https://blob.test/logs/11").respond(text="line 1\nboom\n")
    resp = authed.get("/api/repos/octo/app/checks/11/logs")
    assert resp.status_code == 200
    assert resp.text == "line 1\nboom\n"
    assert "authorization" not in blob.calls.last.request.headers
