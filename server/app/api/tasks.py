import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.api.common import gh_call
from app.deps import DbDep, GitHubDep, UserDep
from app.models import ProviderCredential, Task, User
from app.preview import preview_link
from app.security import decrypt, encrypt
from app.tasks import attachments, git
from app.tasks.manager import TaskError, TaskManager, queued_message
from app.tasks.providers import PROVIDERS, ProviderInfo

router = APIRouter(prefix="/api", tags=["tasks"])

SSE_PING_SECONDS = 15


def get_manager(request: Request) -> TaskManager:
    manager: TaskManager = request.app.state.tasks
    return manager


ManagerDep = Annotated[TaskManager, Depends(get_manager)]


class Provider(ProviderInfo):
    configured: bool


class Credential(BaseModel):
    value: str = Field(min_length=1)


class TaskSummary(BaseModel):
    id: str
    provider: str
    model: str | None
    title: str
    repo_owner: str
    repo_name: str
    base_branch: str
    branch: str
    status: str
    status_detail: str | None
    pending: list[str]
    cost_usd: float
    input_tokens: int
    output_tokens: int
    pr_number: int | None
    created_at: datetime
    updated_at: datetime


# Base64 of the largest allowed image, so oversized bodies are refused before decoding.
MAX_IMAGE_B64 = attachments.MAX_IMAGE_BYTES * 4 // 3 + 4
# Pasted images: base64 PNG, JPEG, GIF or WebP data, without a data: prefix.
Images = Annotated[
    list[Annotated[str, Field(max_length=MAX_IMAGE_B64)]],
    Field(max_length=attachments.MAX_IMAGES),
]


class NewTask(BaseModel):
    provider: str
    owner: str
    name: str
    base_branch: str
    prompt: str = Field(min_length=1)
    model: str | None = None
    # Work directly on this open PR's branch (base_branch must be its head), e.g. to fix CI.
    pr_number: int | None = None
    images: Images = []


class Message(BaseModel):
    text: str = Field(min_length=1)
    images: Images = []


class TaskChange(BaseModel):
    path: str
    status: str


class TaskFile(BaseModel):
    path: str
    # None when the file doesn't exist on that side, is binary, or is too large.
    content: str | None
    exists: bool
    binary: bool = False
    too_large: bool = False


class Publish(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""
    draft: bool = False


class PublishResult(BaseModel):
    pr_number: int
    url: str
    created: bool


def _summary(task: Task) -> TaskSummary:
    fields = task.model_dump(include=set(TaskSummary.model_fields) - {"pending"})
    return TaskSummary(**fields, pending=[queued_message(item)[0] for item in task.pending])


def _own_task(manager: TaskManager, task_id: str, user: User) -> Task:
    try:
        task = manager.load(task_id)
    except KeyError:
        task = None
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


def _decode_images(images: list[str]) -> list[tuple[bytes, str]]:
    try:
        return attachments.decode(images)
    except attachments.AttachmentError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e


def _conflict(e: TaskError) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(e))


# Providers and their credentials


@router.get("/providers")
def list_providers(user: UserDep, db: DbDep) -> list[Provider]:
    configured = {
        c.provider
        for c in db.exec(select(ProviderCredential).where(ProviderCredential.user_id == user.id))
    }
    return [
        Provider(**p.info.model_dump(), configured=p.info.credential_key in configured)
        for p in PROVIDERS.values()
    ]


# {provider} is a provider's credential_key; providers sharing a login share one entry.
@router.put("/providers/{provider}/credential", status_code=status.HTTP_204_NO_CONTENT)
def set_credential(provider: str, body: Credential, user: UserDep, db: DbDep) -> None:
    if provider not in {p.info.credential_key for p in PROVIDERS.values()}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown provider")
    row = db.get(ProviderCredential, (user.id, provider)) or ProviderCredential(
        user_id=user.id or 0, provider=provider, value_enc=""
    )
    row.value_enc = encrypt(body.value.strip())
    row.updated_at = datetime.now(row.updated_at.tzinfo)
    db.add(row)
    db.commit()


@router.delete("/providers/{provider}/credential", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(provider: str, user: UserDep, db: DbDep) -> None:
    row = db.get(ProviderCredential, (user.id, provider))
    if row:
        db.delete(row)
        db.commit()


# Tasks


@router.get("/tasks")
def list_tasks(
    user: UserDep,
    db: DbDep,
    owner: str | None = None,
    name: str | None = None,
    include_archived: bool = False,
) -> list[TaskSummary]:
    query = select(Task).where(Task.user_id == user.id)
    if owner and name:
        query = query.where(Task.repo_owner == owner, Task.repo_name == name)
    if not include_archived:
        query = query.where(Task.status != "stopped")
    return [_summary(t) for t in db.exec(query.order_by(col(Task.updated_at).desc())).all()]


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(
    body: NewTask, user: UserDep, manager: ManagerDep, gh: GitHubDep
) -> TaskSummary:
    if body.pr_number is not None:
        pull = await gh_call(gh.pull(body.owner, body.name, body.pr_number))
        head = pull["head"]
        if pull["state"] != "open" or head["ref"] != body.base_branch:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "That pull request isn't open on this branch"
            )
        if (head.get("repo") or {}).get("full_name") != f"{body.owner}/{body.name}":
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Pull requests from forks can't be worked on"
            )
        if head["ref"] == pull["base"]["ref"]:
            raise HTTPException(status.HTTP_409_CONFLICT, "Refusing to work on the base branch")
    images = _decode_images(body.images)
    try:
        task = manager.create(
            user_id=user.id or 0,
            provider=body.provider,
            owner=body.owner,
            name=body.name,
            base_branch=body.base_branch,
            prompt=body.prompt,
            model=body.model,
            github_token=decrypt(user.token_enc),
            pr_number=body.pr_number,
            images=images,
        )
    except TaskError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return _summary(task)


@router.get("/tasks/{task_id}")
def get_task(task_id: str, user: UserDep, manager: ManagerDep) -> TaskSummary:
    return _summary(_own_task(manager, task_id, user))


@router.get("/tasks/{task_id}/events", response_class=StreamingResponse)
async def task_events(
    task_id: str,
    request: Request,
    user: UserDep,
    db: DbDep,
    manager: ManagerDep,
    after: int = Query(0, ge=0),
) -> StreamingResponse:
    """Server-sent events: the transcript so far, then live updates. EventSource resumes
    from Last-Event-ID after a reconnect, so nothing is missed or repeated."""
    _own_task(manager, task_id, user)
    # The request's session would otherwise keep its pooled connection until the stream
    # ends, and a few open streams would starve every other request.
    db.close()
    last_id = request.headers.get("last-event-id", "")
    start = int(last_id) if last_id.isdigit() else after

    async def body() -> AsyncIterator[str]:
        events = manager.bus.stream(task_id, start)
        next_event = asyncio.ensure_future(anext(events))
        try:
            while True:
                done, _ = await asyncio.wait({next_event}, timeout=SSE_PING_SECONDS)
                if not done:
                    yield ": ping\n\n"
                    continue
                event = next_event.result()
                yield f"id: {event['seq']}\ndata: {json.dumps(event)}\n\n"
                next_event = asyncio.ensure_future(anext(events))
        finally:
            next_event.cancel()
            await events.aclose()

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/tasks/{task_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_message(
    task_id: str, body: Message, user: UserDep, manager: ManagerDep
) -> TaskSummary:
    _own_task(manager, task_id, user)
    images = _decode_images(body.images)
    try:
        manager.send(task_id, body.text, images)
    except TaskError as e:
        raise _conflict(e) from e
    return _summary(manager.load(task_id))


@router.get("/tasks/{task_id}/attachments/{name}", response_class=FileResponse)
def task_attachment(task_id: str, name: str, user: UserDep, manager: ManagerDep) -> FileResponse:
    _own_task(manager, task_id, user)
    path = manager.attachments_dir(task_id) / name
    if not attachments.NAME.match(name) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    return FileResponse(
        path,
        media_type=attachments.MEDIA_TYPES[path.suffix[1:]],
        # The file name is a random id and never changes.
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.post("/tasks/{task_id}/interrupt", status_code=status.HTTP_202_ACCEPTED)
async def interrupt_task(task_id: str, user: UserDep, manager: ManagerDep) -> TaskSummary:
    _own_task(manager, task_id, user)
    try:
        await manager.interrupt(task_id)
    except TaskError as e:
        raise _conflict(e) from e
    return _summary(manager.load(task_id))


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_task(task_id: str, request: Request, user: UserDep, manager: ManagerDep) -> None:
    _own_task(manager, task_id, user)
    request.app.state.terminals.close(task_id)
    await manager.stop(task_id)


def _workspace(manager: TaskManager, task: Task) -> Any:
    repo = manager.repo_dir(task.id)
    if task.base_sha is None or not repo.is_dir():
        raise HTTPException(status.HTTP_409_CONFLICT, "This task has no workspace")
    return repo


@router.get("/tasks/{task_id}/changes")
async def task_changes(task_id: str, user: UserDep, manager: ManagerDep) -> list[TaskChange]:
    task = _own_task(manager, task_id, user)
    repo = _workspace(manager, task)
    files = await git.changed_files(repo, task.base_sha or "")
    return [TaskChange(path=f.path, status=f.status) for f in files]


@router.get("/tasks/{task_id}/file")
async def task_file(
    task_id: str,
    user: UserDep,
    manager: ManagerDep,
    path: str = Query(...),
    side: Literal["base", "working"] = "working",
) -> TaskFile:
    task = _own_task(manager, task_id, user)
    repo = _workspace(manager, task)
    if side == "base":
        try:
            text = await git.show(repo, task.base_sha or "", path)
        except git.GitError:
            return TaskFile(path=path, content=None, exists=True, too_large=True)
        return TaskFile(path=path, content=text, exists=text is not None)

    target = (repo / path).resolve()
    if (
        not target.is_relative_to(repo.resolve())
        or ".git" in target.relative_to(repo.resolve()).parts
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Path is outside the workspace")
    if not target.is_file():
        return TaskFile(path=path, content=None, exists=False)
    if target.stat().st_size > git.MAX_SHOW_BYTES:
        return TaskFile(path=path, content=None, exists=True, too_large=True)
    data = target.read_bytes()
    if b"\x00" in data[:8192]:
        return TaskFile(path=path, content=None, exists=True, binary=True)
    return TaskFile(path=path, content=data.decode(errors="replace"), exists=True)


@router.post("/tasks/{task_id}/publish")
async def publish_task(
    task_id: str,
    body: Publish,
    request: Request,
    user: UserDep,
    manager: ManagerDep,
    gh: GitHubDep,
) -> PublishResult:
    """Commits the workspace, pushes the task's branch and opens (or updates) its PR."""
    task = _own_task(manager, task_id, user)
    if task.status in ("preparing", "running"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Wait for the agent to finish first")
    repo = _workspace(manager, task)
    try:
        await git.commit_all(
            repo,
            body.title,
            user.name or user.login,
            f"{user.github_id}+{user.login}@users.noreply.github.com",
        )
        if await git.ahead_of(repo, task.base_sha or "") == 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "There are no changes to publish")
        await git.push(repo, task.branch, decrypt(user.token_enc))
    except git.GitError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"git: {e}") from e

    owner, name = task.repo_owner, task.repo_name
    if task.pr_number:
        pull = await gh_call(gh.pull(owner, name, task.pr_number))
        created = False
    else:
        pull = await gh_call(
            gh.create_pull(
                owner,
                name,
                {"title": body.title, "head": task.branch, "base": task.base_branch,
                 "body": body.body, "draft": body.draft},
            )
        )  # fmt: skip
        manager.update(task_id, pr_number=pull["number"])
        created = True
    manager.bus.publish(
        task_id, "pr", {"number": pull["number"], "url": pull["html_url"], "created": created}
    )
    request.app.state.notifier.watch_ci(
        user.id or 0, request.app.state.http, decrypt(user.token_enc), owner, name, pull["number"]
    )
    return PublishResult(pr_number=pull["number"], url=pull["html_url"], created=created)


class UsageRow(BaseModel):
    key: str
    tasks: int
    cost_usd: float
    input_tokens: int
    output_tokens: int


class Usage(BaseModel):
    by_provider: list[UsageRow]
    by_repo: list[UsageRow]
    # Subscription logins (setup tokens, ChatGPT plans) report no cost; tokens still count.
    total: UsageRow


@router.get("/usage")
def usage(user: UserDep, db: DbDep) -> Usage:
    tasks = db.exec(select(Task).where(Task.user_id == user.id)).all()

    def rows(key: Any) -> list[UsageRow]:
        groups: dict[str, UsageRow] = {}
        for t in tasks:
            k = key(t)
            row = groups.setdefault(
                k, UsageRow(key=k, tasks=0, cost_usd=0, input_tokens=0, output_tokens=0)
            )
            row.tasks += 1
            row.cost_usd += t.cost_usd
            row.input_tokens += t.input_tokens
            row.output_tokens += t.output_tokens
        return sorted(groups.values(), key=lambda r: r.input_tokens + r.output_tokens, reverse=True)

    total = rows(lambda t: "all")
    return Usage(
        by_provider=rows(lambda t: t.provider),
        by_repo=rows(lambda t: f"{t.repo_owner}/{t.repo_name}"),
        total=total[0]
        if total
        else UsageRow(key="all", tasks=0, cost_usd=0, input_tokens=0, output_tokens=0),
    )


class PreviewRequest(BaseModel):
    port: int = Field(ge=1, le=65535)


class PreviewLink(BaseModel):
    url: str


@router.post("/tasks/{task_id}/preview")
def preview(task_id: str, body: PreviewRequest, user: UserDep, manager: ManagerDep) -> PreviewLink:
    """A short-lived link that opens the task's dev server on the preview origin."""
    task = _own_task(manager, task_id, user)
    if not manager.settings.preview_url:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Previews are off. Set ZIMUA_PREVIEW_URL on the server."
        )
    _workspace(manager, task)
    return PreviewLink(url=preview_link(manager.settings, user.id or 0, task_id, body.port))
