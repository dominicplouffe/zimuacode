"""A tiny stand-in for the GitHub API, used by the web app's end-to-end tests.

Run: uv run uvicorn tests.fake_github:app --port 9001
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

app = FastAPI()

USER = {"id": 1, "login": "octo", "name": "Octo Cat", "avatar_url": None}
REPOS = [
    {
        "owner": {"login": "octo"},
        "name": "shop",
        "full_name": "octo/shop",
        "private": True,
        "default_branch": "main",
        "description": "Next.js storefront",
        "pushed_at": "2026-10-01T00:00:00Z",
    },
    {
        "owner": {"login": "octo"},
        "name": "api",
        "full_name": "octo/api",
        "private": False,
        "default_branch": "main",
        "description": "FastAPI backend",
        "pushed_at": "2026-09-01T00:00:00Z",
    },
]
FILES = {
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


@app.get("/user")
def user() -> dict[str, object]:
    return USER


@app.get("/user/repos")
def repos(page: int = 1) -> list[dict[str, object]]:
    return REPOS if page == 1 else []


@app.get("/repos/{owner}/{name}")
def repo(owner: str, name: str) -> dict[str, object]:
    for r in REPOS:
        if r["full_name"] == f"{owner}/{name}":
            return r
    raise HTTPException(404, "Not Found")


@app.get("/repos/{owner}/{name}/branches")
def branches(owner: str, name: str, page: int = 1) -> list[dict[str, object]]:
    if page > 1:
        return []
    return [{"name": b, "commit": {"sha": "0" * 40}, "protected": b == "main"} for b in FILES]


@app.get("/repos/{owner}/{name}/git/trees/{ref:path}")
def tree(owner: str, name: str, ref: str) -> dict[str, object]:
    files = FILES.get(ref)
    if files is None:
        raise HTTPException(404, "Not Found")
    dirs = sorted({"/".join(p.split("/")[:i]) for p in files for i in range(1, p.count("/") + 1)})
    entries = [{"path": d, "type": "tree"} for d in dirs]
    entries += [{"path": p, "type": "blob", "size": len(c)} for p, c in files.items()]
    return {"sha": "t" * 40, "truncated": False, "tree": entries}


@app.get("/repos/{owner}/{name}/contents/{path:path}")
def contents(owner: str, name: str, path: str, request: Request) -> Response:
    content = FILES.get(request.query_params.get("ref", "main"), {}).get(path)
    if content is None:
        raise HTTPException(404, "Not Found")
    return Response(content, media_type="application/octet-stream")
