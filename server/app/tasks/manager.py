"""Runs agent tasks: one turn at a time, tailing each turn's output into task events."""

import asyncio
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
from app.models import ProviderCredential, Task, User
from app.security import decrypt
from app.tasks import git
from app.tasks.events import EventBus
from app.tasks.providers import PROVIDERS, AgentProvider, TurnContext
from app.tasks.sandbox import Sandbox, task_dir, write_turn_script

log = logging.getLogger(__name__)

POLL_SECONDS = 0.25
# How often a turn with no output is checked for a process that died without an exit file.
LIVENESS_SECONDS = 5.0
# A launched turn that hasn't written its pid file by then is treated as failed to start.
START_TIMEOUT_SECONDS = 60.0

ACTIVE = ("preparing", "running")


class TaskError(Exception):
    """A request the task can't accept in its current state."""


def slugify(text: str, limit: int = 32) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "task"


def title_from_prompt(prompt: str) -> str:
    first = prompt.strip().splitlines()[0] if prompt.strip() else "Task"
    return first if len(first) <= 80 else first[:79] + "…"


def user_settings(user_id: int) -> dict[str, Any]:
    from app.api.settings import effective

    with Session(get_engine()) as s:
        user = s.get(User, user_id)
        return effective(user.settings_json if user else "{}")


def credential_for(user_id: int, provider: str) -> str | None:
    with Session(get_engine()) as s:
        row = s.get(ProviderCredential, (user_id, provider))
        return decrypt(row.value_enc) if row else None


class TaskManager:
    def __init__(self, settings: Settings, bus: EventBus, sandbox: Sandbox) -> None:
        self.settings = settings
        self.bus = bus
        self.sandbox = sandbox
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
    ) -> Task:
        if provider not in PROVIDERS:
            raise TaskError(f"Unknown provider {provider}")
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
            branch=f"zimua/{slugify(prompt)}-{task_id[:6]}",
            # Claude Code accepts a preset session id, which makes resuming reliable.
            session_id=str(uuid.uuid4()) if provider == "claude-code" else None,
        )
        with Session(get_engine()) as s:
            s.add(task)
            s.commit()
            s.refresh(task)
        self.bus.publish(task_id, "user_message", {"text": prompt})
        self._spawn(task_id, self._prepare_and_run(task_id, prompt, github_token))
        return task

    async def _prepare_and_run(self, task_id: str, prompt: str, github_token: str) -> None:
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
        except Exception as e:
            log.exception("preparing task %s failed", task_id)
            self.bus.publish(task_id, "error", {"message": f"Couldn't prepare workspace: {e}"})
            self.set_status(task_id, "failed", "Workspace setup failed")
            return
        await self._start_turn(task_id, prompt)

    async def _start_turn(self, task_id: str, prompt: str) -> None:
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
        )
        try:
            provider.setup_home(ctx)
            write_turn_script(
                self.root(task_id),
                task.turn,
                provider.command(ctx),
                provider.env(ctx),
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
            next_prompt, *rest = task.pending
            self.update(task_id, pending=rest)
            await self._start_turn(task_id, next_prompt)

    # Requests from the UI

    def send(self, task_id: str, text: str) -> None:
        task = self.load(task_id)
        if task.status == "stopped":
            raise TaskError("This task is archived")
        if task.base_sha is None and task.status != "preparing":
            raise TaskError("The workspace was never set up; start a new task")
        if task.status in ACTIVE:
            self.update(task_id, pending=[*task.pending, text])
            self.bus.publish(task_id, "user_message", {"text": text, "queued": True})
            return
        self.bus.publish(task_id, "user_message", {"text": text})
        # Running from this moment, so nobody sees a stale "idle" before the turn starts.
        self.update(task_id, status="running", status_detail=None)
        self._spawn(task_id, self._start_turn(task_id, text))

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
