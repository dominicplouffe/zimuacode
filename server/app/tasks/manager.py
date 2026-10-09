"""Runs agent tasks: one turn at a time, tailing each turn's output into task events."""

import asyncio
import json
import logging
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.config import Settings
from app.db import get_engine
from app.models import ProviderCredential, RepoConfig, Task, User
from app.notify import Notifier
from app.security import decrypt
from app.tasks import attachments, git
from app.tasks.events import EventBus
from app.tasks.providers import PROVIDERS, AgentProvider, TurnContext
from app.tasks.sandbox import Sandbox, task_dir, write_turn_script

log = logging.getLogger(__name__)

POLL_SECONDS = 0.25
# How often a turn with no output is checked for a process that died without an exit file.
LIVENESS_SECONDS = 5.0
# A launched turn that hasn't written its pid file by then is treated as failed to start.
START_TIMEOUT_SECONDS = 60.0
SETUP_TIMEOUT_SECONDS = 30 * 60

ACTIVE = ("preparing", "running")


class TaskError(Exception):
    """A request the task can't accept in its current state."""


def slugify(text: str, limit: int = 32) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "task"


# Words that say how something was asked, not what changes: dropped from branch names.
FILLER = set(
    """
    a an the i we you me us our my your it its this that these those there here
    is are am was were be been do does did can could would should will shall may might must
    please pls just also so then now really actually maybe kind sort of some any
    need needs want wants like let lets make sure try help
    to for in on at by with from into about as and or but if when how what why which
    able going get got have has had
    """.split()  # noqa: SIM905  (a word list reads better as text)
)


def branch_slug(text: str, max_words: int = 5, max_length: int = 40) -> str:
    """A short branch name about the change: "Do we support themes in this code?" →
    "support-themes-code". Falls back to "change" when nothing meaningful is left."""
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower().replace("'", "")) if w not in FILLER]
    slug = ""
    for word in words[:max_words]:
        candidate = f"{slug}-{word}" if slug else word
        if len(candidate) > max_length:
            break
        slug = candidate
    return slug or "change"


def unique_branch(slug: str, taken: set[str]) -> str:
    """zimua/<slug>, or zimua/<slug>-2, -3… when the name is already used."""
    name = f"zimua/{slug}"
    n = 2
    while name in taken:
        name = f"zimua/{slug}-{n}"
        n += 1
    return name


def placeholder_branch(task_id: str, round: int = 1) -> str:
    # Local only: renamed after the PR title when the work is published.
    return f"zimua/task-{task_id[:6]}" + (f"-r{round}" if round > 1 else "")


def title_from_prompt(prompt: str) -> str:
    first = prompt.strip().splitlines()[0] if prompt.strip() else "Task"
    return first if len(first) <= 80 else first[:79] + "…"


def queued_message(item: str | dict[str, Any]) -> tuple[str, list[str]]:
    """The text and attachment names of a queued follow-up."""
    if isinstance(item, str):
        return item, []
    return item["text"], item["images"]


def _images_field(names: list[str]) -> dict[str, list[str]]:
    return {"images": names} if names else {}


def user_settings(user_id: int) -> dict[str, Any]:
    from app.api.settings import effective

    with Session(get_engine()) as s:
        user = s.get(User, user_id)
        return effective(user.settings_json if user else "{}")


def repo_config(user_id: int, owner: str, name: str) -> tuple[dict[str, str], str]:
    """A repository's agent environment variables and setup script."""
    with Session(get_engine()) as s:
        row = s.get(RepoConfig, (user_id, owner, name))
    if row is None:
        return {}, ""
    env = json.loads(decrypt(row.env_enc)) if row.env_enc else {}
    return env, row.setup_script


def credential_for(user_id: int, provider: str) -> str | None:
    with Session(get_engine()) as s:
        row = s.get(ProviderCredential, (user_id, provider))
        return decrypt(row.value_enc) if row else None


class TaskManager:
    def __init__(
        self, settings: Settings, bus: EventBus, sandbox: Sandbox, notifier: Notifier | None = None
    ) -> None:
        self.settings = settings
        self.bus = bus
        self.sandbox = sandbox
        self.notifier = notifier
        self._jobs: dict[str, asyncio.Task[None]] = {}

    # Persistence helpers

    def load(self, task_id: str) -> Task:
        with Session(get_engine()) as s:
            task = s.get(Task, task_id)
            if task is None:
                raise KeyError(task_id)
            return task

    def update(self, task_id: str, **fields: Any) -> Task:
        with Session(get_engine()) as s:
            task = s.get(Task, task_id)
            if task is None:
                raise KeyError(task_id)
            for key, value in fields.items():
                setattr(task, key, value)
            task.updated_at = datetime.now(UTC)
            s.add(task)
            s.commit()
            s.refresh(task)
            return task

    def set_status(self, task_id: str, status: str, detail: str | None = None) -> None:
        self.update(task_id, status=status, status_detail=detail)
        self.bus.publish(task_id, "status", {"status": status, "detail": detail})

    def root(self, task_id: str) -> Path:
        return task_dir(self.settings, task_id)

    def repo_dir(self, task_id: str) -> Path:
        return self.root(task_id) / "repo"

    def attachments_dir(self, task_id: str) -> Path:
        return self.root(task_id) / "attachments"

    def provider(self, task: Task) -> AgentProvider:
        return PROVIDERS[task.provider]

    def _spawn(self, task_id: str, coro: Any) -> None:
        job = asyncio.create_task(coro)
        self._jobs[task_id] = job
        job.add_done_callback(lambda j: self._finished(task_id, j))

    def _finished(self, task_id: str, job: asyncio.Task[None]) -> None:
        if self._jobs.get(task_id) is job:
            del self._jobs[task_id]
        if not job.cancelled() and job.exception():
            log.error("task %s job failed", task_id, exc_info=job.exception())

    # Lifecycle

    def create(
        self,
        *,
        user_id: int,
        provider: str,
        owner: str,
        name: str,
        base_branch: str,
        prompt: str,
        model: str | None,
        github_token: str,
        pr_number: int | None = None,
        images: list[tuple[bytes, str]] | None = None,
    ) -> Task:
        """Starts a task on a new branch from base_branch, or, with pr_number, directly on
        that PR's branch (base_branch is then the PR's head branch)."""
        if provider not in PROVIDERS:
            raise TaskError(f"Unknown provider {provider}")
        if images and not PROVIDERS[provider].info.capabilities.images:
            raise TaskError(f"{PROVIDERS[provider].info.name} can't take images")
        task_id = uuid.uuid4().hex[:12]
        task = Task(
            id=task_id,
            user_id=user_id,
            provider=provider,
            model=model or None,
            title=title_from_prompt(prompt),
            repo_owner=owner,
            repo_name=name,
            base_branch=base_branch,
            branch=base_branch if pr_number else placeholder_branch(task_id),
            branch_named=pr_number is not None,
            pr_number=pr_number,
            # Claude Code accepts a preset session id, which makes resuming reliable.
            session_id=str(uuid.uuid4()) if provider == "claude-code" else None,
        )
        with Session(get_engine()) as s:
            s.add(task)
            s.commit()
            s.refresh(task)
        names = self._save_images(task_id, images)
        self.bus.publish(task_id, "user_message", {"text": prompt, **_images_field(names)})
        self._spawn(task_id, self._prepare_and_run(task_id, prompt, names, github_token))
        return task

    def _save_images(self, task_id: str, images: list[tuple[bytes, str]] | None) -> list[str]:
        return attachments.save(self.attachments_dir(task_id), images) if images else []

    async def _prepare_and_run(
        self, task_id: str, prompt: str, images: list[str], github_token: str
    ) -> None:
        task = self.load(task_id)
        self.set_status(task_id, "preparing", "Cloning repository")
        try:
            url = self.settings.git_url_template.format(owner=task.repo_owner, name=task.repo_name)
            base_sha = await git.clone(
                url, self.repo_dir(task_id), task.base_branch, task.branch, github_token
            )
            self.update(task_id, base_sha=base_sha)
            self.set_status(task_id, "preparing", "Starting agent")
            await self.sandbox.prepare(task_id)
            (self.root(task_id) / "home").mkdir(parents=True, exist_ok=True)
            env, setup = repo_config(task.user_id, task.repo_owner, task.repo_name)
            if setup.strip() and not await self._run_setup(task_id, setup, env):
                return
        except Exception as e:
            log.exception("preparing task %s failed", task_id)
            self.bus.publish(task_id, "error", {"message": f"Couldn't prepare workspace: {e}"})
            self.set_status(task_id, "failed", "Workspace setup failed")
            self._notify_turn_end(self.load(task_id))
            return
        await self._start_turn(task_id, prompt, images)

    async def _run_setup(self, task_id: str, script: str, env: dict[str, str]) -> bool:
        self.set_status(task_id, "preparing", "Running setup script")
        path = self.root(task_id) / "turns" / "setup.sh"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(script)

        def on_line(line: str) -> None:
            self.bus.publish(task_id, "log", {"text": line, "source": "setup"})

        try:
            code = await asyncio.wait_for(
                self.sandbox.run(task_id, ["sh", "-e", "../turns/setup.sh"], env, on_line),
                SETUP_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            code = None
        if code == 0:
            return True
        reason = "timed out" if code is None else f"exited with code {code}"
        self.bus.publish(task_id, "error", {"message": f"The setup script {reason}."})
        self.set_status(task_id, "failed", "Setup script failed")
        return False

    async def _start_turn(self, task_id: str, prompt: str, images: list[str]) -> None:
        task = self.update(
            task_id,
            turn=self.load(task_id).turn + 1,
            log_offset=0,
            interrupt_requested=False,
            status="running",
            status_detail=None,
        )
        self.bus.publish(task_id, "status", {"status": "running", "detail": None})
        provider = self.provider(task)
        ctx = TurnContext(
            settings=self.settings,
            task=task,
            first_turn=task.turn == 1,
            user_settings=user_settings(task.user_id),
            credential=credential_for(task.user_id, provider.info.credential_key),
            home=self.root(task_id) / "home",
            images=[self.attachments_dir(task_id) / name for name in images],
        )
        try:
            provider.setup_home(ctx)
            repo_env, _ = repo_config(task.user_id, task.repo_owner, task.repo_name)
            write_turn_script(
                self.root(task_id),
                task.turn,
                provider.command(ctx),
                # The agent's own login wins over a same-named repo variable.
                repo_env | provider.env(ctx),
                provider.prompt(ctx, prompt),
                self.sandbox.home(task_id),
            )
            await self.sandbox.launch(task_id, task.turn)
        except Exception as e:
            log.exception("launching task %s failed", task_id)
            self.bus.publish(task_id, "error", {"message": f"Couldn't start the agent: {e}"})
            self.set_status(task_id, "failed", "Agent failed to start")
            return
        await self._watch_turn(task_id)

    async def _watch_turn(self, task_id: str) -> None:
        task = self.load(task_id)
        provider = self.provider(task)
        turns = self.root(task_id) / "turns"
        log_path, exit_path, pid_path = (
            turns / f"{task.turn}.{ext}" for ext in ("jsonl", "exit", "pid")
        )
        parser = provider.parser()
        offset = task.log_offset
        pending = b""
        started = asyncio.get_running_loop().time()
        last_check = started
        lost = False
        session_id = task.session_id

        def drain() -> bool:
            nonlocal offset, pending, session_id
            if not log_path.exists():
                return False
            with log_path.open("rb") as f:
                f.seek(offset)
                chunk = f.read()
            if not chunk:
                return False
            offset += len(chunk)
            pending += chunk
            *lines, pending = pending.split(b"\n")
            for raw in lines:
                for type_, data in parser.parse(raw.decode(errors="replace")):
                    self.bus.publish(task_id, type_, data)
            fields: dict[str, Any] = {"log_offset": offset - len(pending)}
            if parser.result.session_id and parser.result.session_id != session_id:
                session_id = parser.result.session_id
                fields["session_id"] = session_id
            self.update(task_id, **fields)
            return True

        while True:
            if drain():
                continue
            if exit_path.exists():
                drain()
                break
            now = asyncio.get_running_loop().time()
            if now - last_check >= LIVENESS_SECONDS:
                last_check = now
                if pid_path.exists():
                    pid = int(pid_path.read_text().strip() or 0)
                    if (
                        pid
                        and not await self.sandbox.is_alive(task_id, pid)
                        and not exit_path.exists()
                    ):
                        drain()
                        lost = True
                        break
                elif now - started > START_TIMEOUT_SECONDS:
                    lost = True
                    break
            await asyncio.sleep(POLL_SECONDS)

        if pending.strip():
            for type_, data in parser.parse(pending.decode(errors="replace")):
                self.bus.publish(task_id, type_, data)
        await self._finish_turn(task_id, parser.result, exit_path, lost)

    async def _finish_turn(self, task_id: str, result: Any, exit_path: Path, lost: bool) -> None:
        task = self.load(task_id)
        code = int(exit_path.read_text().strip() or 1) if exit_path.exists() else None
        self.update(
            task_id,
            cost_usd=task.cost_usd + result.cost_usd,
            input_tokens=task.input_tokens + result.input_tokens,
            output_tokens=task.output_tokens + result.output_tokens,
            session_id=result.session_id or task.session_id,
        )
        if task.interrupt_requested:
            self.set_status(task_id, "interrupted", "Stopped by you")
        elif lost:
            self.bus.publish(
                task_id, "error", {"message": "The agent process stopped unexpectedly."}
            )
            self.set_status(task_id, "failed", "Agent process lost")
        elif code != 0 or result.failed:
            self.set_status(task_id, "failed", f"Agent exited with code {code}")
        else:
            self.set_status(task_id, "idle")

        task = self.load(task_id)
        if task.pending and not task.interrupt_requested and task.status in ("idle", "failed"):
            queued, *rest = task.pending
            self.update(task_id, pending=rest)
            text, images = queued_message(queued)
            await self._start_turn(task_id, text, images)
            return
        self._notify_turn_end(task)

    def _notify_turn_end(self, task: Task) -> None:
        # Interruptions are the user's own doing; everything else is worth a ping.
        if self.notifier is None or task.status not in ("idle", "failed"):
            return
        title = "Agent finished" if task.status == "idle" else "Agent failed"
        self.notifier.notify(
            task.user_id,
            title,
            f"{task.title} · {task.repo_owner}/{task.repo_name}",
            self.notifier.task_link(task.id),
            tag=f"task-{task.id}",
        )

    # Requests from the UI

    def send(self, task_id: str, text: str, images: list[tuple[bytes, str]] | None = None) -> None:
        task = self.load(task_id)
        if task.status == "stopped":
            raise TaskError("This task is archived")
        if task.base_sha is None and task.status != "preparing":
            raise TaskError("The workspace was never set up; start a new task")
        if images and not self.provider(task).info.capabilities.images:
            raise TaskError(f"{self.provider(task).info.name} can't take images")
        names = self._save_images(task_id, images)
        if task.status in ACTIVE:
            queued = {"text": text, "images": names}
            self.update(task_id, pending=[*task.pending, queued])
            self.bus.publish(
                task_id, "user_message", {"text": text, **_images_field(names), "queued": True}
            )
            return
        self.bus.publish(task_id, "user_message", {"text": text, **_images_field(names)})
        # Running from this moment, so nobody sees a stale "idle" before the turn starts.
        self.update(task_id, status="running", status_detail=None)
        self._spawn(task_id, self._start_turn(task_id, text, names))

    async def new_round(
        self, task_id: str, merged_pr: int, after_sha: str, base: str, token: str
    ) -> Task:
        """Ends a round whose PR was merged: the workspace moves to a new branch from the
        latest `base`, carrying over only work done after the merged PR's head."""
        task = self.load(task_id)
        repo = self.repo_dir(task_id)
        await git.fetch_branch(repo, base, token)
        # The PR may have gained commits from elsewhere before merging; fetch them so the
        # "after" point exists here. Its branch may already be deleted, which is fine.
        if await git.rev_parse(repo, after_sha) is None:
            await git.fetch_branch(repo, task.branch, token)
        if await git.rev_parse(repo, after_sha) is None:
            after_sha = task.published_sha or after_sha
        round = task.round + 1
        new_branch = placeholder_branch(task_id, round)
        await git.start_round(repo, f"origin/{base}", after_sha, new_branch)
        new_base = await git.rev_parse(repo, f"origin/{base}")
        task = self.update(
            task_id,
            branch=new_branch,
            branch_named=False,
            base_branch=base,
            base_sha=new_base,
            pr_number=None,
            previous_prs=[*(task.previous_prs or []), merged_pr],
            round=round,
        )
        self.bus.publish(task_id, "round", {"previous_pr": merged_pr, "base": base, "round": round})
        return task

    def retire_pr(self, task_id: str) -> Task:
        """The PR was closed without merging: keep the branch, open a new PR next time."""
        task = self.load(task_id)
        if task.pr_number is None:
            return task
        return self.update(
            task_id,
            pr_number=None,
            previous_prs=[*(task.previous_prs or []), task.pr_number],
        )

    async def name_branch(self, task_id: str, title: str, token: str) -> Task:
        """Gives a placeholder branch its real name, from the PR title, before the first push."""
        task = self.load(task_id)
        if task.branch_named:
            return task
        repo = self.repo_dir(task_id)
        slug = branch_slug(title)
        taken = await git.remote_branches(repo, f"zimua/{slug}", token)
        name = unique_branch(slug, taken)
        await git.rename_branch(repo, name)
        return self.update(task_id, branch=name, branch_named=True)

    async def interrupt(self, task_id: str) -> None:
        task = self.load(task_id)
        if task.status != "running":
            raise TaskError("The agent isn't running")
        # Queued follow-ups are dropped too: interrupting means "stop and let me redirect".
        self.update(task_id, interrupt_requested=True, pending=[])
        pid_path = self.root(task_id) / "turns" / f"{task.turn}.pid"
        if pid_path.exists():
            await self.sandbox.interrupt(task_id, int(pid_path.read_text().strip()))

    async def stop(self, task_id: str) -> None:
        """Archives a task: stops the agent, removes the workspace, keeps the transcript."""
        task = self.load(task_id)
        if task.status == "running":
            await self.interrupt(task_id)
        job = self._jobs.get(task_id)
        if job:
            job.cancel()
        await self.sandbox.destroy(task_id)
        await asyncio.to_thread(shutil.rmtree, self.root(task_id), True)
        self.set_status(task_id, "stopped", "Archived")

    async def recover(self) -> None:
        """After a restart: resume watching running turns; fail interrupted setups."""
        with Session(get_engine()) as s:
            tasks = s.exec(select(Task).where(Task.status.in_(ACTIVE))).all()  # type: ignore[attr-defined]
        for task in tasks:
            if task.status == "running":
                self._spawn(task.id, self._watch_turn(task.id))
            else:
                self.bus.publish(
                    task.id, "error", {"message": "The server restarted during setup."}
                )
                self.set_status(task.id, "failed", "Setup interrupted")

    async def shutdown(self) -> None:
        # Agent processes keep running; only the watchers stop. recover() picks them up.
        for job in list(self._jobs.values()):
            job.cancel()
        await asyncio.gather(*self._jobs.values(), return_exceptions=True)
