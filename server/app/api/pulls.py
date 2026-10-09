import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.api.common import gh_call
from app.deps import GitHubDep

router = APIRouter(prefix="/api/repos", tags=["pulls"])


class PullSummary(BaseModel):
    number: int
    title: str
    state: Literal["open", "closed"]
    draft: bool
    merged: bool
    author: str
    head_ref: str
    head_sha: str
    base_ref: str
    updated_at: str
    html_url: str


class Pull(PullSummary):
    body: str | None
    base_sha: str
    # What the PR's diff is against (GitHub's "files changed" uses it too).
    merge_base_sha: str
    # None while GitHub is still computing it.
    mergeable: bool | None
    mergeable_state: str
    additions: int
    deletions: int
    changed_files: int
    head_repo: str | None


class PullFile(BaseModel):
    filename: str
    status: str
    previous_filename: str | None
    additions: int
    deletions: int


class TimelineItem(BaseModel):
    id: str
    kind: Literal["comment", "review", "review_comment"]
    author: str
    body: str
    created_at: str
    html_url: str
    # Reviews: APPROVED, CHANGES_REQUESTED, COMMENTED. Review comments: the file and line.
    state: str | None = None
    path: str | None = None
    line: int | None = None


class Check(BaseModel):
    id: int
    name: str
    kind: Literal["check_run", "status"]
    # queued | in_progress | completed
    status: str
    # success | failure | neutral | cancelled | skipped | timed_out | action_required | None
    conclusion: str | None
    url: str | None
    # True for GitHub Actions jobs, whose logs the IDE can show.
    has_logs: bool


class CreatePull(BaseModel):
    title: str = Field(min_length=1)
    head: str = Field(min_length=1)
    base: str = Field(min_length=1)
    body: str = ""
    draft: bool = False


class NewComment(BaseModel):
    body: str = Field(min_length=1)


class MergeRequest(BaseModel):
    method: Literal["merge", "squash", "rebase"] = "merge"


class MergeResult(BaseModel):
    merged: bool
    sha: str | None
    message: str


def _summary(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": p["number"],
        "title": p["title"],
        "state": p["state"],
        "draft": p.get("draft", False),
        "merged": bool(p.get("merged_at")),
        "author": p["user"]["login"],
        "head_ref": p["head"]["ref"],
        "head_sha": p["head"]["sha"],
        "base_ref": p["base"]["ref"],
        "updated_at": p["updated_at"],
        "html_url": p["html_url"],
    }


def _login(item: dict[str, Any]) -> str:
    return str((item.get("user") or {}).get("login", "ghost"))


@router.get("/{owner}/{name}/pulls")
async def list_pulls(
    owner: str,
    name: str,
    gh: GitHubDep,
    state: Literal["open", "closed", "all"] = "open",
    head: str | None = Query(None, description="Branch name in this repo"),
) -> list[PullSummary]:
    pulls = await gh_call(gh.pulls(owner, name, state, f"{owner}:{head}" if head else None))
    return [PullSummary(**_summary(p)) for p in pulls]


@router.post("/{owner}/{name}/pulls", status_code=status.HTTP_201_CREATED)
async def create_pull(owner: str, name: str, body: CreatePull, gh: GitHubDep) -> PullSummary:
    p = await gh_call(gh.create_pull(owner, name, body.model_dump()))
    return PullSummary(**_summary(p))


@router.get("/{owner}/{name}/pulls/{number}")
async def get_pull(owner: str, name: str, number: int, gh: GitHubDep) -> Pull:
    p = await gh_call(gh.pull(owner, name, number))
    head_repo = p["head"].get("repo")
    merge_base = await gh_call(gh.merge_base(owner, name, p["base"]["sha"], p["head"]["sha"]))
    return Pull(
        **_summary(p),
        body=p.get("body"),
        base_sha=p["base"]["sha"],
        merge_base_sha=merge_base,
        mergeable=p.get("mergeable"),
        mergeable_state=p.get("mergeable_state", "unknown"),
        additions=p.get("additions", 0),
        deletions=p.get("deletions", 0),
        changed_files=p.get("changed_files", 0),
        head_repo=head_repo["full_name"] if head_repo else None,
    )


@router.get("/{owner}/{name}/pulls/{number}/files")
async def list_pull_files(owner: str, name: str, number: int, gh: GitHubDep) -> list[PullFile]:
    return [
        PullFile(
            filename=f["filename"],
            status=f["status"],
            previous_filename=f.get("previous_filename"),
            additions=f.get("additions", 0),
            deletions=f.get("deletions", 0),
        )
        for f in await gh_call(gh.pull_files(owner, name, number))
    ]


@router.get("/{owner}/{name}/pulls/{number}/timeline")
async def pull_timeline(owner: str, name: str, number: int, gh: GitHubDep) -> list[TimelineItem]:
    comments, review_comments, reviews = await gh_call(
        asyncio.gather(
            gh.issue_comments(owner, name, number),
            gh.review_comments(owner, name, number),
            gh.reviews(owner, name, number),
        )
    )
    items = [
        TimelineItem(
            id=f"c{c['id']}",
            kind="comment",
            author=_login(c),
            body=c.get("body") or "",
            created_at=c["created_at"],
            html_url=c["html_url"],
        )
        for c in comments
    ]
    items += [
        TimelineItem(
            id=f"rc{c['id']}",
            kind="review_comment",
            author=_login(c),
            body=c.get("body") or "",
            created_at=c["created_at"],
            html_url=c["html_url"],
            path=c.get("path"),
            line=c.get("line") or c.get("original_line"),
        )
        for c in review_comments
    ]
    items += [
        TimelineItem(
            id=f"r{r['id']}",
            kind="review",
            author=_login(r),
            body=r.get("body") or "",
            # Pending reviews have no submitted_at and are only visible to their author.
            created_at=r["submitted_at"],
            html_url=r["html_url"],
            state=r["state"],
        )
        for r in reviews
        if r.get("submitted_at")
    ]
    return sorted(items, key=lambda i: i.created_at)


@router.post("/{owner}/{name}/pulls/{number}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(
    owner: str, name: str, number: int, body: NewComment, gh: GitHubDep
) -> TimelineItem:
    c = await gh_call(gh.create_issue_comment(owner, name, number, body.body))
    return TimelineItem(
        id=f"c{c['id']}",
        kind="comment",
        author=_login(c),
        body=c.get("body") or "",
        created_at=c["created_at"],
        html_url=c["html_url"],
    )


@router.put("/{owner}/{name}/pulls/{number}/merge")
async def merge_pull(
    owner: str, name: str, number: int, body: MergeRequest, gh: GitHubDep
) -> MergeResult:
    r = await gh_call(gh.merge_pull(owner, name, number, body.method))
    return MergeResult(
        merged=r.get("merged", False), sha=r.get("sha"), message=r.get("message", "")
    )


@router.get("/{owner}/{name}/checks")
async def list_checks(owner: str, name: str, gh: GitHubDep, ref: str = Query(...)) -> list[Check]:
    runs, statuses = await gh_call(
        asyncio.gather(gh.check_runs(owner, name, ref), gh.combined_status(owner, name, ref))
    )
    checks = [
        Check(
            id=r["id"],
            name=r["name"],
            kind="check_run",
            status=r["status"],
            conclusion=r.get("conclusion"),
            url=r.get("html_url") or r.get("details_url"),
            has_logs=(r.get("app") or {}).get("slug") == "github-actions",
        )
        for r in runs
    ]
    # Commit statuses (older CI integrations) map onto the check run vocabulary.
    for s in statuses:
        state = s["state"]
        conclusion = {"pending": None, "success": "success"}.get(state, "failure")
        checks.append(
            Check(
                id=s["id"],
                name=s["context"],
                kind="status",
                status="in_progress" if state == "pending" else "completed",
                conclusion=conclusion,
                url=s.get("target_url"),
                has_logs=False,
            )
        )
    return sorted(checks, key=lambda c: c.name.lower())


@router.get("/{owner}/{name}/checks/{job_id}/logs", response_class=PlainTextResponse)
async def check_logs(owner: str, name: str, job_id: int, gh: GitHubDep) -> str:
    return await gh_call(gh.job_logs(owner, name, job_id))
