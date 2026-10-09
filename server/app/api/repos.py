from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.common import gh_call
from app.deps import GitHubDep
from app.github.client import MAX_EDITOR_BYTES, decode_text

router = APIRouter(prefix="/api/repos", tags=["repos"])


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
    # The commit the ref pointed to. Reads and commits use it, so they see one snapshot.
    commit_sha: str
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


class CreateBranch(BaseModel):
    name: str = Field(min_length=1)
    from_sha: str = Field(min_length=1)


@router.get("")
async def list_repos(gh: GitHubDep, page: int = 1) -> list[Repo]:
    return [_repo(r) for r in await gh_call(gh.repos(page=page))]


@router.get("/{owner}/{name}")
async def get_repo(owner: str, name: str, gh: GitHubDep) -> Repo:
    return _repo(await gh_call(gh.repo(owner, name)))


@router.get("/{owner}/{name}/branches")
async def list_branches(owner: str, name: str, gh: GitHubDep) -> list[Branch]:
    return [
        Branch(name=b["name"], sha=b["commit"]["sha"], protected=b.get("protected", False))
        for b in await gh_call(gh.branches(owner, name))
    ]


@router.post("/{owner}/{name}/branches", status_code=status.HTTP_201_CREATED)
async def create_branch(owner: str, name: str, body: CreateBranch, gh: GitHubDep) -> Branch:
    await gh_call(gh.create_ref(owner, name, body.name, body.from_sha))
    return Branch(name=body.name, sha=body.from_sha, protected=False)


@router.delete("/{owner}/{name}/branches", status_code=status.HTTP_204_NO_CONTENT)
async def delete_branch(owner: str, name: str, gh: GitHubDep, branch: str = Query(...)) -> None:
    repo = await gh_call(gh.repo(owner, name))
    if branch == repo["default_branch"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Can't delete the default branch")
    await gh_call(gh.delete_ref(owner, name, branch))


@router.get("/{owner}/{name}/tree")
async def get_tree(owner: str, name: str, gh: GitHubDep, ref: str = Query(...)) -> Tree:
    commit = await gh_call(gh.commit(owner, name, ref))
    data = await gh_call(gh.tree(owner, name, commit["commit"]["tree"]["sha"]))
    return Tree(
        commit_sha=commit["sha"],
        truncated=data.get("truncated", False),
        entries=[
            TreeEntry(path=e["path"], type=e["type"], size=e.get("size")) for e in data["tree"]
        ],
    )


@router.get("/{owner}/{name}/file")
async def get_file(
    owner: str, name: str, gh: GitHubDep, path: str = Query(...), ref: str = Query(...)
) -> FileContent:
    data = await gh_call(gh.file(owner, name, path, ref))
    if len(data) > MAX_EDITOR_BYTES:
        return FileContent(
            path=path, ref=ref, size=len(data), content=None, binary=False, too_large=True
        )
    text = decode_text(data)
    return FileContent(
        path=path, ref=ref, size=len(data), content=text, binary=text is None, too_large=False
    )
