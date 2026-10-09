from collections.abc import Awaitable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.deps import GitHubDep
from app.github.client import MAX_EDITOR_BYTES, GitHubError, decode_text

router = APIRouter(prefix="/api/repos", tags=["repos"])


async def _gh[T](call: Awaitable[T]) -> T:
    try:
        return await call
    except GitHubError as e:
        status = e.status if e.status in (401, 403, 404, 409, 422) else 502
        raise HTTPException(status, e.message) from e


class Repo(BaseModel):
    owner: str
    name: str
    full_name: str
    private: bool
    default_branch: str
    description: str | None
    pushed_at: str | None


def _repo(r: dict[str, Any]) -> Repo:
    return Repo(
        owner=r["owner"]["login"],
        name=r["name"],
        full_name=r["full_name"],
        private=r["private"],
        default_branch=r["default_branch"],
        description=r.get("description"),
        pushed_at=r.get("pushed_at"),
    )


class Branch(BaseModel):
    name: str
    sha: str
    protected: bool


class TreeEntry(BaseModel):
    path: str
    type: Literal["blob", "tree", "commit"]
    size: int | None = None


class Tree(BaseModel):
    sha: str
    truncated: bool
    entries: list[TreeEntry]


class FileContent(BaseModel):
    path: str
    ref: str
    size: int
    # None when the file is binary or too large to open in the editor.
    content: str | None
    binary: bool
    too_large: bool


@router.get("")
async def list_repos(gh: GitHubDep, page: int = 1) -> list[Repo]:
    return [_repo(r) for r in await _gh(gh.repos(page=page))]


@router.get("/{owner}/{name}")
async def get_repo(owner: str, name: str, gh: GitHubDep) -> Repo:
    return _repo(await _gh(gh.repo(owner, name)))


@router.get("/{owner}/{name}/branches")
async def list_branches(owner: str, name: str, gh: GitHubDep) -> list[Branch]:
    branches: list[Branch] = []
    page = 1
    while True:
        batch = await _gh(gh.branches(owner, name, page=page))
        branches += [
            Branch(name=b["name"], sha=b["commit"]["sha"], protected=b.get("protected", False))
            for b in batch
        ]
        if len(batch) < 100 or page >= 10:
            return branches
        page += 1


@router.get("/{owner}/{name}/tree")
async def get_tree(owner: str, name: str, gh: GitHubDep, ref: str = Query(...)) -> Tree:
    data = await _gh(gh.tree(owner, name, ref))
    return Tree(
        sha=data["sha"],
        truncated=data.get("truncated", False),
        entries=[
            TreeEntry(path=e["path"], type=e["type"], size=e.get("size")) for e in data["tree"]
        ],
    )


@router.get("/{owner}/{name}/file")
async def get_file(
    owner: str, name: str, gh: GitHubDep, path: str = Query(...), ref: str = Query(...)
) -> FileContent:
    data = await _gh(gh.file(owner, name, path, ref))
    if len(data) > MAX_EDITOR_BYTES:
        return FileContent(
            path=path, ref=ref, size=len(data), content=None, binary=False, too_large=True
        )
    text = decode_text(data)
    return FileContent(
        path=path, ref=ref, size=len(data), content=text, binary=text is None, too_large=False
    )
