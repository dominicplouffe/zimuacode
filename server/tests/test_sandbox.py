import os
from pathlib import Path

import pytest

from app.config import Settings
from app.tasks.sandbox import DockerSandbox, write_turn_script


class RecordingDocker(DockerSandbox):
    def __init__(self, settings: Settings, inspect: str) -> None:
        super().__init__(settings)
        self.calls: list[tuple[str, ...]] = []
        self.inspect = inspect

    async def _docker(self, *args: str, check: bool = True) -> str:
        self.calls.append(args)
        return self.inspect if args[0] == "inspect" else ""


async def test_docker_creates_one_container_per_task(tmp_path: Path) -> None:
    sandbox = RecordingDocker(Settings(data_dir=tmp_path, runner_image="img"), inspect="")
    await sandbox.prepare("abc")
    run = sandbox.calls[-1]
    assert run[:4] == ("run", "--detach", "--name", "zimua-task-abc")
    assert ("--volume", f"{tmp_path.resolve()}/tasks/abc:/workspace") in zip(
        run, run[1:], strict=False
    )
    assert ("--user", f"{os.getuid()}:{os.getgid()}") in zip(run, run[1:], strict=False)
    assert run[-3:] == ("img", "sleep", "infinity")

    await sandbox.launch("abc", 2)
    assert sandbox.calls[-1] == (
        "exec",
        "--detach",
        "zimua-task-abc",
        "sh",
        "/workspace/turns/2.sh",
    )
    await sandbox.interrupt("abc", 42)
    assert sandbox.calls[-1] == ("exec", "zimua-task-abc", "kill", "-TERM", "42")
    await sandbox.destroy("abc")
    assert sandbox.calls[-1] == ("rm", "--force", "zimua-task-abc")


@pytest.mark.parametrize(("state", "expected"), [("true", None), ("false", "start")])
async def test_docker_reuses_existing_containers(
    tmp_path: Path, state: str, expected: str | None
) -> None:
    sandbox = RecordingDocker(Settings(data_dir=tmp_path), inspect=state)
    await sandbox.prepare("abc")
    commands = [c[0] for c in sandbox.calls]
    assert "run" not in commands
    assert commands[-1] == (expected or "inspect")


def test_turn_script_quotes_and_protects_secrets(tmp_path: Path) -> None:
    script = write_turn_script(
        tmp_path, 1, ["claude", "-p", "--append-system-prompt", "it's `quoted`"],
        {"CLAUDE_CODE_OAUTH_TOKEN": "s3cr3t"}, "prompt text", "/home/x",
    )  # fmt: skip
    text = script.read_text()
    assert "export CLAUDE_CODE_OAUTH_TOKEN=s3cr3t" in text
    assert "'it'\"'\"'s `quoted`'" in text
    assert script.stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "turns" / "1.prompt").read_text() == "prompt text"
