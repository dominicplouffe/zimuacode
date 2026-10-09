from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.common import PASSTHROUGH, gh_call
from app.deps import GitHubDep
from app.github.client import GitHubError

router = APIRouter(prefix="/api/repos", tags=["commits"])


class FileChange(BaseModel):
    path: str = Field(min_length=1)
    # New file contents, or None to delete the file.
    content: str | None


class CommitRequest(BaseModel):
    branch: str = Field(min_length=1)
    # The commit the edits were made against. The commit is refused if the branch has moved.
    expected_head: str = Field(min_length=1)
    message: str = Field(min_length=1)
    changes: list[FileChange] = Field(min_length=1)
    # Create `branch` at expected_head first, e.g. to commit to a new branch.
    create_branch: bool = False


class CommitResult(BaseModel):
    sha: str
    branch: str


@router.post("/{owner}/{name}/commits", status_code=status.HTTP_201_CREATED)
async def commit(owner: str, name: str, body: CommitRequest, gh: GitHubDep) -> CommitResult:
    """Commits a set of file changes atomically using the git data API."""
    base = await gh_call(gh.commit(owner, name, body.expected_head))
    if body.create_branch:
        await gh_call(gh.create_ref(owner, name, body.branch, body.expected_head))

    entries = [
        {"path": c.path, "mode": "100644", "type": "blob", "content": c.content}
        if c.content is not None
        else {"path": c.path, "mode": "100644", "type": "blob", "sha": None}
        for c in body.changes
    ]
    tree = await gh_call(gh.create_tree(owner, name, base["commit"]["tree"]["sha"], entries))
    new = await gh_call(
        gh.create_commit(owner, name, body.message, tree["sha"], [body.expected_head])
    )
    try:
        await gh.update_ref(owner, name, body.branch, new["sha"])
    except GitHubError as e:
        if e.status == 422 and "fast forward" in e.message.lower():
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Branch changed since you loaded it. Reload to get the latest, then commit again.",
            ) from e
        # Other refusals (e.g. a protected branch) keep GitHub's own message.
        raise HTTPException(e.status if e.status in PASSTHROUGH else 502, e.message) from e
    return CommitResult(sha=new["sha"], branch=body.branch)
