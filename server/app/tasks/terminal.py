"""One interactive shell per task workspace, over a pseudo-terminal.

The shell outlives browser connections: reconnecting replays recent output, so a dev
server started in it keeps running (and stays previewable) while you're away.
"""

import asyncio
import contextlib
import fcntl
import os
import shutil
import signal
import struct
import termios
from collections.abc import Callable

from app.config import Settings
from app.tasks.sandbox import DockerSandbox, safe_env, task_dir

# Output kept for replay when a browser reconnects.
SCROLLBACK_BYTES = 256 * 1024

Listener = Callable[[bytes | None], None]  # None means the shell exited


def _controlling_tty(slave_name: str) -> Callable[[], None]:
    def setup() -> None:
        # Runs in the child: a new session with the pty as its controlling terminal, so
        # Ctrl-C and job control work as in a normal terminal. Opening the tty after
        # setsid() makes it the controlling one; TIOCSCTTY is the fallback.
        os.setsid()
        try:
            os.close(os.open(slave_name, os.O_RDWR))
        except OSError:
            with contextlib.suppress(OSError):
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    return setup


class Terminal:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.listeners: set[Listener] = set()
        self.exit_code: int | None = None
        self._master = -1
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self, argv: list[str], cwd: str | None, env: dict[str, str]) -> None:
        master, slave = os.openpty()
        self._master = master
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=cwd,
                env=env,
                preexec_fn=_controlling_tty(os.ttyname(slave)),
            )
        finally:
            os.close(slave)
        os.set_blocking(master, False)
        asyncio.get_running_loop().add_reader(master, self._on_readable)
        asyncio.create_task(self._wait())

    def _on_readable(self) -> None:
        try:
            data = os.read(self._master, 65536)
        except OSError:
            data = b""
        if not data:
            asyncio.get_running_loop().remove_reader(self._master)
            return
        self.buffer += data
        if len(self.buffer) > SCROLLBACK_BYTES:
            del self.buffer[: len(self.buffer) - SCROLLBACK_BYTES]
        for listener in list(self.listeners):
            listener(data)

    async def _wait(self) -> None:
        assert self._proc is not None
        self.exit_code = await self._proc.wait()
        # Let the last output drain before announcing the exit.
        await asyncio.sleep(0.05)
        with contextlib.suppress(Exception):
            asyncio.get_running_loop().remove_reader(self._master)
        with contextlib.suppress(OSError):
            os.close(self._master)
        for listener in list(self.listeners):
            listener(None)

    @property
    def alive(self) -> bool:
        return self.exit_code is None

    def write(self, data: bytes) -> None:
        if self.alive:
            os.write(self._master, data)

    def resize(self, cols: int, rows: int) -> None:
        if self.alive:
            fcntl.ioctl(self._master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def close(self) -> None:
        if self._proc and self.alive:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self._proc.pid, signal.SIGHUP)


class Terminals:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._terminals: dict[str, Terminal] = {}

    def get(self, task_id: str) -> Terminal | None:
        terminal = self._terminals.get(task_id)
        return terminal if terminal and terminal.alive else None

    async def open(self, task_id: str, env: dict[str, str]) -> Terminal:
        existing = self.get(task_id)
        if existing:
            return existing
        terminal = Terminal()
        root = task_dir(self.settings, task_id)
        base_env = {"TERM": "xterm-256color", "COLORTERM": "truecolor"}
        if self.settings.sandbox == "docker":
            flags = [x for k, v in (env | base_env).items() for x in ("--env", f"{k}={v}")]
            argv = [
                "docker", "exec", "--interactive", "--tty", *flags,
                DockerSandbox.container(task_id), "bash", "-l",
            ]  # fmt: skip
            await terminal.start(argv, None, safe_env(base_env))
        else:
            shell = shutil.which("bash") or "/bin/sh"
            await terminal.start(
                [shell, "-l"] if shell.endswith("bash") else [shell],
                str(root / "repo"),
                safe_env({"HOME": str(root / "home"), **env, **base_env}),
            )
        self._terminals[task_id] = terminal
        return terminal

    def close(self, task_id: str) -> None:
        terminal = self._terminals.pop(task_id, None)
        if terminal:
            terminal.close()

    def close_all(self) -> None:
        for task_id in list(self._terminals):
            self.close(task_id)
