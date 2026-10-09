"""A small, stateful stand-in for the GitHub API, used by the web app's end-to-end tests.

Run: uv run uvicorn tests.fake_github:app --port 9001
POST /__reset restores the initial state; POST /__move/{branch} pushes an unrelated commit,
as if someone else (or an agent) pushed to the branch.
"""

import hashlib
import itertools
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, Response


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    reset()
    yield


app = FastAPI(lifespan=lifespan)

USER = {"id": 1, "login": "octo", "name": "Octo Cat", "avatar_url": None}
NOW = "2026-10-01T00:00:00Z"
_REPOS = [("shop", True, "Next.js storefront"), ("api", False, "FastAPI backend")]
REPOS = [
    {
        "owner": {"login": "octo"},
        "name": n,
        "full_name": f"octo/{n}",
        "private": private,
        "default_branch": "main",
        "description": desc,
        "pushed_at": NOW,
    }
    for n, private, desc in _REPOS
]
INITIAL = {
    "main": {
        "README.md": b"# Shop\n",
        "app/page.tsx": b"export default function Page() {\n  return <h1>Shop</h1>\n}\n",
        "app/layout.tsx": b"export default function Layout({ children }) {\n  return children\n}\n",
        "api/server.py": b"def handler():\n    return 'ok'\n",
        "public/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00",
    },
    "feature/checkout": {
        "README.md": b"# Shop (checkout branch)\n",
        "app/checkout.tsx": b"export const Checkout = () => null\n",
    },
}
LOG = (
    "2026-10-01T00:00:01.0000000Z ##[group]Run npm test\n"
    "2026-10-01T00:00:02.0000000Z \x1b[31mFAIL\x1b[0m app/page.test.tsx\n"
    "2026-10-01T00:00:03.0000000Z Expected: Shop\n"
    "2026-10-01T00:00:04.0000000Z ##[error]Process completed with exit code 1.\n"
)

_counter = itertools.count()
# sha -> {"files": {path: bytes}, "tree": tree sha}
commits: dict[str, dict[str, Any]] = {}
trees: dict[str, dict[str, bytes]] = {}
branches: dict[str, str] = {}
pulls: dict[int, dict[str, Any]] = {}
comments: dict[int, list[dict[str, Any]]] = {}


def _sha(prefix: str) -> str:
    return hashlib.sha1(f"{prefix}{next(_counter)}".encode()).hexdigest()


def _commit(files: dict[str, bytes]) -> str:
    tree = _sha("tree")
    trees[tree] = dict(files)
    sha = _sha("commit")
    commits[sha] = {"files": dict(files), "tree": tree}
    return sha


@app.post("/__reset")
def reset() -> dict[str, bool]:
    commits.clear()
    trees.clear()
    branches.clear()
    pulls.clear()
    comments.clear()
    for name, files in INITIAL.items():
        branches[name] = _commit(files)
    branches["feature/legacy"] = _commit(INITIAL["main"])
    _create_pull("Legacy cleanup", "feature/legacy", "main", "Removes *old* code.", False)
    return {"ok": True}


@app.post("/__move/{branch:path}")
def move(branch: str) -> dict[str, str]:
    files = dict(commits[branches[branch]]["files"])
    files["README.md"] = files.get("README.md", b"") + b"pushed by someone else\n"
    branches[branch] = _commit(files)
    return {"sha": branches[branch]}


def _resolve(ref: str) -> str:
    if ref in commits:
        return ref
    if ref in branches:
        return branches[ref]
    raise HTTPException(404, "No commit found for SHA: " + ref)


@app.get("/user")
def user() -> dict[str, Any]:
    return USER


@app.get("/user/repos")
def repos(page: int = 1) -> list[dict[str, Any]]:
    return REPOS if page == 1 else []


@app.get("/repos/{owner}/{name}")
def repo(owner: str, name: str) -> dict[str, Any]:
    for r in REPOS:
        if r["full_name"] == f"{owner}/{name}":
            return r
    raise HTTPException(404, "Not Found")


@app.get("/repos/{owner}/{name}/branches")
def list_branches(owner: str, name: str, page: int = 1) -> list[dict[str, Any]]:
    if page > 1:
        return []
    return [
        {"name": b, "commit": {"sha": sha}, "protected": b == "main"}
        for b, sha in sorted(branches.items())
    ]


@app.get("/repos/{owner}/{name}/commits/{ref:path}/check-runs")
def check_runs(owner: str, name: str, ref: str) -> dict[str, Any]:
    _resolve(ref)
    return {
        "check_runs": [
            {
                "id": 101,
                "name": "build",
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.com/run/101",
                "app": {"slug": "github-actions"},
            },
            {
                "id": 102,
                "name": "test",
                "status": "completed",
                "conclusion": "failure",
                "html_url": "https://github.com/run/102",
                "app": {"slug": "github-actions"},
            },
            {
                "id": 103,
                "name": "Vercel",
                "status": "in_progress",
                "conclusion": None,
                "details_url": "https://vercel.com/deploy",
                "app": {"slug": "vercel"},
            },
        ]
    }


@app.get("/repos/{owner}/{name}/commits/{ref:path}/status")
def combined_status(owner: str, name: str, ref: str) -> dict[str, Any]:
    _resolve(ref)
    return {"statuses": []}


@app.get("/repos/{owner}/{name}/commits/{ref:path}")
def get_commit(owner: str, name: str, ref: str) -> dict[str, Any]:
    sha = _resolve(ref)
    return {"sha": sha, "commit": {"tree": {"sha": commits[sha]["tree"]}}}


@app.get("/repos/{owner}/{name}/compare/{spec}")
def compare(owner: str, name: str, spec: str) -> dict[str, Any]:
    base, _, _head = spec.partition("...")
    return {"merge_base_commit": {"sha": _resolve(base)}}


@app.get("/repos/{owner}/{name}/git/trees/{sha}")
def get_tree(owner: str, name: str, sha: str) -> dict[str, Any]:
    files = trees.get(sha)
    if files is None:
        raise HTTPException(404, "Not Found")
    dirs = sorted({"/".join(p.split("/")[:i]) for p in files for i in range(1, p.count("/") + 1)})
    entries = [{"path": d, "type": "tree"} for d in dirs]
    entries += [{"path": p, "type": "blob", "size": len(c)} for p, c in sorted(files.items())]
    return {"sha": sha, "truncated": False, "tree": entries}


@app.post("/repos/{owner}/{name}/git/trees", status_code=201)
async def create_tree(owner: str, name: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    files = dict(trees[body["base_tree"]])
    for entry in body["tree"]:
        if entry.get("content") is not None:
            files[entry["path"]] = entry["content"].encode()
        elif entry["path"] in files:
            del files[entry["path"]]
        else:
            raise HTTPException(422, "GitRPC::BadObjectState")
    sha = _sha("tree")
    trees[sha] = files
    return {"sha": sha}


@app.post("/repos/{owner}/{name}/git/commits", status_code=201)
async def create_commit(owner: str, name: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    sha = _sha("commit")
    commits[sha] = {"files": dict(trees[body["tree"]]), "tree": body["tree"], **body}
    return {"sha": sha}


@app.post("/repos/{owner}/{name}/git/refs", status_code=201)
async def create_ref(owner: str, name: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    branch = body["ref"].removeprefix("refs/heads/")
    if branch in branches:
        raise HTTPException(422, "Reference already exists")
    branches[branch] = _resolve(body["sha"])
    return {"ref": body["ref"]}


@app.patch("/repos/{owner}/{name}/git/refs/heads/{branch:path}")
async def update_ref(owner: str, name: str, branch: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    new = commits[body["sha"]]
    if branches.get(branch) not in new.get("parents", []):
        raise HTTPException(422, "Update is not a fast forward")
    branches[branch] = body["sha"]
    return {"ref": f"refs/heads/{branch}"}


@app.delete("/repos/{owner}/{name}/git/refs/heads/{branch:path}", status_code=204)
def delete_ref(owner: str, name: str, branch: str) -> Response:
    if branches.pop(branch, None) is None:
        raise HTTPException(422, "Reference does not exist")
    return Response(status_code=204)


@app.get("/repos/{owner}/{name}/contents/{path:path}")
def contents(owner: str, name: str, path: str, request: Request) -> Response:
    sha = _resolve(request.query_params.get("ref", "main"))
    content = commits[sha]["files"].get(path)
    if content is None:
        raise HTTPException(404, "Not Found")
    return Response(content, media_type="application/octet-stream")


def _create_pull(title: str, head: str, base: str, body: str, draft: bool) -> dict[str, Any]:
    number = max(pulls, default=0) + 1
    pulls[number] = {
        "number": number,
        "title": title,
        "state": "open",
        "draft": draft,
        "merged_at": None,
        "user": {"login": "octo"},
        "head": {"ref": head, "repo": {"full_name": "octo/shop"}},
        "base": {"ref": base},
        "updated_at": NOW,
        "html_url": f"https://github.com/octo/shop/pull/{number}",
        "body": body,
        "mergeable": True,
        "mergeable_state": "clean",
    }
    comments[number] = []
    return _pull_view(number)


def _pull_view(number: int) -> dict[str, Any]:
    p = pulls[number]
    head_sha = branches.get(p["head"]["ref"], p.get("merged_head", ""))
    base_sha = branches[p["base"]["ref"]]
    changed = _changed_files(base_sha, head_sha) if head_sha else []
    return {
        **p,
        "head": {**p["head"], "sha": head_sha},
        "base": {**p["base"], "sha": base_sha},
        "additions": len(changed),
        "deletions": 0,
        "changed_files": len(changed),
    }


def _changed_files(base: str, head: str) -> list[dict[str, Any]]:
    a, b = commits[base]["files"], commits[head]["files"]
    files = []
    for path in sorted(set(a) | set(b)):
        if path not in a:
            files.append({"filename": path, "status": "added", "additions": 1, "deletions": 0})
        elif path not in b:
            files.append({"filename": path, "status": "removed", "additions": 0, "deletions": 1})
        elif a[path] != b[path]:
            files.append({"filename": path, "status": "modified", "additions": 1, "deletions": 1})
    return files


@app.get("/repos/{owner}/{name}/pulls")
def list_pulls(owner: str, name: str, state: str = "open", head: str | None = None) -> list[Any]:
    result = []
    for number in sorted(pulls, reverse=True):
        p = pulls[number]
        if state != "all" and p["state"] != state:
            continue
        if head and head != f"octo:{p['head']['ref']}":
            continue
        result.append(_pull_view(number))
    return result


@app.post("/repos/{owner}/{name}/pulls", status_code=201)
async def create_pull(owner: str, name: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    if body["head"] not in branches:
        raise HTTPException(422, "Validation Failed")
    return _create_pull(
        body["title"], body["head"], body["base"], body.get("body", ""), body.get("draft", False)
    )


@app.get("/repos/{owner}/{name}/pulls/{number}")
def get_pull(owner: str, name: str, number: int) -> dict[str, Any]:
    if number not in pulls:
        raise HTTPException(404, "Not Found")
    return _pull_view(number)


@app.get("/repos/{owner}/{name}/pulls/{number}/files")
def pull_files(owner: str, name: str, number: int, page: int = 1) -> list[Any]:
    view = _pull_view(number)
    return _changed_files(view["base"]["sha"], view["head"]["sha"]) if page == 1 else []


@app.get("/repos/{owner}/{name}/issues/{number}/comments")
def issue_comments(owner: str, name: str, number: int, page: int = 1) -> list[Any]:
    return comments.get(number, []) if page == 1 else []


@app.post("/repos/{owner}/{name}/issues/{number}/comments", status_code=201)
async def add_comment(owner: str, name: str, number: int, request: Request) -> dict[str, Any]:
    body = await request.json()
    comment = {
        "id": next(_counter),
        "user": {"login": "octo"},
        "body": body["body"],
        "created_at": "2026-10-02T00:00:00Z",
        "html_url": f"https://github.com/octo/shop/pull/{number}#comment",
    }
    comments[number].append(comment)
    return comment


@app.get("/repos/{owner}/{name}/pulls/{number}/comments")
def review_comments(owner: str, name: str, number: int, page: int = 1) -> list[Any]:
    return []


@app.get("/repos/{owner}/{name}/pulls/{number}/reviews")
def reviews(owner: str, name: str, number: int, page: int = 1) -> list[Any]:
    if page > 1:
        return []
    return [
        {
            "id": 9000 + number,
            "user": {"login": "reviewer"},
            "body": "Looks good",
            "state": "APPROVED",
            "submitted_at": "2026-10-01T12:00:00Z",
            "html_url": "https://github.com/review",
        }
    ]


@app.put("/repos/{owner}/{name}/pulls/{number}/merge")
async def merge(owner: str, name: str, number: int, request: Request) -> dict[str, Any]:
    p = pulls[number]
    if p["state"] != "open":
        raise HTTPException(405, "Pull Request is not mergeable")
    head_sha = branches[p["head"]["ref"]]
    branches[p["base"]["ref"]] = _commit(commits[head_sha]["files"])
    p.update(state="closed", merged_at=NOW, merged_head=head_sha)
    return {"merged": True, "sha": branches[p["base"]["ref"]], "message": "Merged"}


@app.get("/repos/{owner}/{name}/actions/jobs/{job_id}/logs")
def job_logs(owner: str, name: str, job_id: int, request: Request) -> RedirectResponse:
    # Redirect to a different origin (localhost <-> 127.0.0.1), like GitHub's blob storage,
    # so the "token must not follow the redirect" check below means something.
    url = request.url_for("blob_logs", job_id=job_id)
    other = "127.0.0.1" if url.hostname == "localhost" else "localhost"
    return RedirectResponse(str(url.replace(hostname=other)), status_code=302)


@app.get("/__blob/logs/{job_id}", name="blob_logs")
def blob_logs(job_id: int, request: Request) -> Response:
    if "authorization" in request.headers:
        raise HTTPException(400, "Token leaked to blob storage")
    return Response(LOG, media_type="text/plain")
