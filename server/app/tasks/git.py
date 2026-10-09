"""Git operations the server runs on a task's workspace.

The GitHub token is passed to git through environment variables for each command, so it
is never written into the workspace where the agent could read it.
"""

import asyncio
import base64
import os
from dataclasses import dataclass
from pathlib import Path

# Big enough for any source file; larger files are reported as too large.
MAX_SHOW_BYTES = 5 * 1024 * 1024


class GitError(Exception):
    pass


@dataclass
class ChangedFile:
    path: str
    # A (added), M (modified), D (deleted)
    status: str


def _auth_env(token: str | None) -> dict[str, str]:
    env = {"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env |= {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
        }
    return env


async def git(
    cwd: Path, *args: str, token: str | None = None, check: bool = True, max_bytes: int = 0
) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-c",
        "core.quotepath=off",
        *args,
        cwd=cwd,
        env={**os.environ, **_auth_env(token)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if check and proc.returncode != 0:
        message = err.decode(errors="replace").strip() or f"git {args[0]} failed"
        # Never echo credentials back, even in errors.
        raise GitError(message.replace(token, "***") if token else message)
    if max_bytes and len(out) > max_bytes:
        raise GitError("File too large")
    return out.decode(errors="replace")


async def clone(url: str, dest: Path, base: str, branch: str, token: str | None) -> str:
    """Clones `base` into dest and returns its commit SHA. Work happens on a new `branch`
    from it, or on `base` itself when they're the same (e.g. fixing a PR's branch)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    await git(
        dest.parent, "clone", "--filter=blob:none", "--branch", base, url, dest.name, token=token
    )
    if branch != base:
        await git(dest, "checkout", "-b", branch)
    return (await git(dest, "rev-parse", "HEAD")).strip()


async def changed_files(repo: Path, base_sha: str) -> list[ChangedFile]:
    """Everything that differs from the base commit: commits, staged, unstaged, untracked."""
    # Intent-to-add makes untracked files show up in the diff without staging content.
    await git(repo, "add", "--all", "--intent-to-add")
    out = await git(repo, "diff", "--name-status", "--no-renames", "-z", base_sha)
    parts = [p for p in out.split("\0") if p]
    return [ChangedFile(path=parts[i + 1], status=parts[i][0]) for i in range(0, len(parts) - 1, 2)]


async def show(repo: Path, sha: str, path: str) -> str | None:
    """A file's contents at a commit, or None if it didn't exist there."""
    try:
        return await git(repo, "show", f"{sha}:{path}", max_bytes=MAX_SHOW_BYTES)
    except GitError as e:
        if "too large" in str(e):
            raise
        return None


async def commit_all(repo: Path, message: str, author_name: str, author_email: str) -> bool:
    """Commits every change in the workspace. Returns False when there was nothing to commit."""
    await git(repo, "add", "--all")
    status = await git(repo, "status", "--porcelain")
    if not status.strip():
        return False
    await git(
        repo,
        "-c",
        f"user.name={author_name}",
        "-c",
        f"user.email={author_email}",
        "commit",
        "--quiet",
        "-m",
        message,
    )
    return True


async def push(repo: Path, branch: str, token: str | None) -> None:
    await git(repo, "push", "origin", f"HEAD:refs/heads/{branch}", token=token)


async def ahead_of(repo: Path, base_sha: str) -> int:
    """How many commits HEAD has on top of the base."""
    return int((await git(repo, "rev-list", "--count", f"{base_sha}..HEAD")).strip() or 0)
