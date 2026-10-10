"""Agent providers: how to run each CLI and how to read its output.

Adding a provider means writing one class with these methods and registering it in
PROVIDERS. The runner, event stream and UI work for it unchanged.
"""

import base64
import hashlib
import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from app.config import Settings
from app.tasks.attachments import MEDIA_TYPES

# Tool outputs and large tool inputs (e.g. a whole file being written) are clipped in the
# transcript; the workspace itself has the full content.
MAX_OUTPUT_CHARS = 20_000
MAX_INPUT_STRING_CHARS = 2_000

Event = tuple[str, dict[str, Any]]


class Capabilities(BaseModel):
    streaming: bool
    follow_ups: bool
    interrupt: bool
    live_files: bool
    # Whether pasted images reach the agent.
    images: bool
    # "self": runs on this server's runner. "vendor": hands off to the vendor's cloud.
    runs_on: str


class ProviderInfo(BaseModel):
    id: str
    name: str
    capabilities: Capabilities
    credential_help: str
    # Providers that share a login (e.g. Codex and Codex Cloud) share a key.
    credential_key: str
    # Shown in the UI for providers that rely on undocumented or unverified CLI behaviour.
    experimental: bool = False


def clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… ({len(text) - limit} more characters)"


def clip_input(value: Any) -> Any:
    if isinstance(value, str):
        return clip(value, MAX_INPUT_STRING_CHARS)
    if isinstance(value, dict):
        return {k: clip_input(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clip_input(v) for v in value]
    return value


@dataclass
class TurnResult:
    """What the runner learns from a turn's output, besides the events themselves."""

    session_id: str | None = None
    cost_usd: float = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failed: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class OutputParser(Protocol):
    result: TurnResult

    def parse(self, line: str) -> list[Event]: ...


@dataclass
class TurnContext:
    """Everything a provider needs to build one turn's command."""

    settings: Settings
    task: Any  # app.models.Task
    first_turn: bool
    # The user's effective settings.json values.
    user_settings: dict[str, Any]
    # The decrypted login for info.credential_key, if the user saved one.
    credential: str | None
    # The agent's HOME on the server's disk, for writing login files.
    home: Path
    # Pasted images for this message, on the server's disk.
    images: list[Path] = field(default_factory=list)


class AgentProvider(Protocol):
    info: ProviderInfo

    def command(self, ctx: TurnContext) -> list[str]:
        """argv for one turn. The prompt arrives on stdin."""
        ...

    def prompt(self, ctx: TurnContext, text: str) -> str:
        """The text sent on stdin for a user message."""
        ...

    def env(self, ctx: TurnContext) -> dict[str, str]: ...

    def setup_home(self, ctx: TurnContext) -> None:
        """Writes any files the CLI needs in its HOME (e.g. a login file). Runs before
        every turn, so it must be idempotent."""

    def parser(self) -> OutputParser: ...


def write_login_file(home: Path, relative: str, content: str) -> None:
    """Writes a CLI's login file, but only when the saved credential changed: CLIs refresh
    their tokens in place, and overwriting a refreshed file with the original would log
    them out."""
    marker = home / ".zimua" / (relative.replace("/", "_") + ".sha256")
    digest = hashlib.sha256(content.encode()).hexdigest()
    target = home / relative
    if target.exists() and marker.exists() and marker.read_text() == digest:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    target.chmod(0o600)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(digest)


def ide_rules(task: Any) -> str:
    """Standing instructions for the agent: where it runs and how its work reaches GitHub.

    Agents have no GitHub credentials; the IDE publishes for them. Without saying so plainly
    (and naming the button), agents tell users a pull request "can't be created".
    """
    branch = (
        f"`{task.branch}`"
        if getattr(task, "branch_named", True)
        else "a new local branch (it's named after the pull request title when published)"
    )
    lines = [
        f"You are running inside Zimua Code, a web IDE, in a workspace on {branch}.",
        "You can't push or open pull requests yourself: you have no GitHub credentials, and "
        "the IDE publishes your work. Don't run `git push` or `gh pr create`. You may commit "
        "if it helps, but it isn't required.",
    ]
    previous = list(getattr(task, "previous_prs", None) or [])
    pr = getattr(task, "pr_number", None)
    if pr:
        lines.append(
            f"This task's open pull request is #{pr}. When the user wants your "
            "latest changes on it, tell them to click **Push changes to PR** in this task's "
            "Pull request panel (on the right)."
        )
    else:
        lines.append(
            "When the user wants a pull request, tell them to type a title in this task's "
            "Pull request panel (on the right) and click **Create pull request**."
        )
    if previous:
        numbers = ", ".join(f"#{n}" for n in previous)
        lines.append(
            f"Earlier pull requests from this task ({numbers}) were merged or closed. "
            "Publishing opens a new pull request on a fresh branch, so a new pull request is "
            "always possible; never tell the user it can't be created."
        )
    return " ".join(lines)


def _tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, dict) and block.get("type") == "image":
                parts.append("[image]")
        return "\n".join(parts)
    return "" if content is None else json.dumps(content)


class ClaudeParser:
    """Reads `claude -p --output-format stream-json --verbose`."""

    def __init__(self) -> None:
        self.result = TurnResult()

    def parse(self, line: str) -> list[Event]:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return [("log", {"text": line})] if line.strip() else []
        if not isinstance(msg, dict):
            return []
        if msg.get("session_id"):
            self.result.session_id = msg["session_id"]
        kind = msg.get("type")
        # Messages from subagents (Task tool) are marked so the UI can nest or dim them.
        sub = {"subagent": True} if msg.get("parent_tool_use_id") else {}

        if kind == "assistant":
            events: list[Event] = []
            for block in (msg.get("message") or {}).get("content") or []:
                t = block.get("type")
                if t == "text" and block.get("text"):
                    events.append(("assistant_text", {"text": block["text"], **sub}))
                elif t == "thinking" and block.get("thinking"):
                    events.append(("thinking", {"text": block["thinking"], **sub}))
                elif t == "tool_use":
                    events.append((
                        "tool_call",
                        {"id": block.get("id"), "name": block.get("name"),
                         "input": clip_input(block.get("input")), **sub},
                    ))  # fmt: skip
            return events

        if kind == "user":
            content = (msg.get("message") or {}).get("content")
            if not isinstance(content, list):
                return []
            return [
                (
                    "tool_result",
                    {
                        "id": block.get("tool_use_id"),
                        "output": clip(_tool_result_text(block.get("content"))),
                        "is_error": bool(block.get("is_error")),
                        **sub,
                    },
                )
                for block in content
                if isinstance(block, dict) and block.get("type") == "tool_result"
            ]

        if kind == "result":
            usage = msg.get("usage") or {}
            r = self.result
            r.cost_usd = float(msg.get("total_cost_usd") or 0)
            r.input_tokens = (
                int(usage.get("input_tokens") or 0)
                + int(usage.get("cache_read_input_tokens") or 0)
                + int(usage.get("cache_creation_input_tokens") or 0)
            )
            r.output_tokens = int(usage.get("output_tokens") or 0)
            events = [
                (
                    "usage",
                    {
                        "cost_usd": r.cost_usd,
                        "input_tokens": r.input_tokens,
                        "output_tokens": r.output_tokens,
                        "num_turns": msg.get("num_turns"),
                        "duration_ms": msg.get("duration_ms"),
                    },
                )
            ]
            if msg.get("is_error") or msg.get("subtype") != "success":
                r.failed = True
                errors = msg.get("errors") or []
                text = msg.get("result") or "; ".join(map(str, errors)) or msg.get("subtype")
                events.append(("error", {"message": str(text)}))
            return events

        return []


class ClaudeCode:
    info = ProviderInfo(
        id="claude-code",
        name="Claude Code",
        capabilities=Capabilities(
            streaming=True,
            follow_ups=True,
            interrupt=True,
            live_files=True,
            images=True,
            runs_on="self",
        ),
        credential_help=(
            "Run `claude setup-token` on your computer (it uses your Claude Pro/Max "
            "subscription) and paste the token. An Anthropic API key (sk-ant-api…) also works."
        ),
        credential_key="claude-code",
    )

    def command(self, ctx: TurnContext) -> list[str]:
        task = ctx.task
        argv = [
            *shlex.split(ctx.settings.claude_bin),
            "-p",
            "--output-format", "stream-json",
            "--verbose",
            # The sandbox is the safety boundary; there is nobody to approve prompts.
            "--dangerously-skip-permissions",
            "--append-system-prompt", ide_rules(task),
        ]  # fmt: skip
        if task.model:
            argv += ["--model", task.model]
        if task.session_id:
            argv += ["--session-id" if ctx.first_turn else "--resume", task.session_id]
        if ctx.images:
            # Plain-text stdin can't carry images; this takes the message as a JSON line.
            argv += ["--input-format", "stream-json"]
        return argv

    def prompt(self, ctx: TurnContext, text: str) -> str:
        if not ctx.images:
            return text
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": MEDIA_TYPES[path.suffix[1:]],
                    "data": base64.b64encode(path.read_bytes()).decode(),
                },
            }
            for path in ctx.images
        ]
        content.append({"type": "text", "text": text})
        message = {"type": "user", "message": {"role": "user", "content": content}}
        return json.dumps(message) + "\n"

    def env(self, ctx: TurnContext) -> dict[str, str]:
        if not ctx.credential:
            return {}
        if ctx.credential.startswith("sk-ant-api"):
            return {"ANTHROPIC_API_KEY": ctx.credential}
        return {"CLAUDE_CODE_OAUTH_TOKEN": ctx.credential}

    def setup_home(self, ctx: TurnContext) -> None:
        pass

    def parser(self) -> OutputParser:
        return ClaudeParser()


class CodexParser:
    """Reads `codex exec --json` (thread/turn/item events)."""

    def __init__(self) -> None:
        self.result = TurnResult()

    def parse(self, line: str) -> list[Event]:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return [("log", {"text": line})] if line.strip() else []
        if not isinstance(msg, dict):
            return []
        kind = msg.get("type")
        if kind == "thread.started":
            self.result.session_id = msg.get("thread_id")
            return []
        if kind == "turn.completed":
            usage = msg.get("usage") or {}
            self.result.input_tokens += int(usage.get("input_tokens") or 0)
            self.result.output_tokens += int(usage.get("output_tokens") or 0)
            return [
                (
                    "usage",
                    {
                        "input_tokens": int(usage.get("input_tokens") or 0),
                        "cached_input_tokens": int(usage.get("cached_input_tokens") or 0),
                        "output_tokens": int(usage.get("output_tokens") or 0),
                    },
                )
            ]
        if kind == "turn.failed":
            self.result.failed = True
            return [
                ("error", {"message": str((msg.get("error") or {}).get("message", "Turn failed"))})
            ]
        if kind == "error":
            return [("error", {"message": str(msg.get("message", "Error"))})]
        if kind in ("item.completed", "item.updated"):
            return self._item(msg.get("item") or {}, completed=kind == "item.completed")
        return []

    def _item(self, item: dict[str, Any], completed: bool) -> list[Event]:
        t = item.get("type")
        item_id = item.get("id")
        if t == "todo_list":
            return [("todo", {"id": item_id, "items": item.get("items") or []})]
        if not completed:
            return []
        if t == "agent_message":
            return [("assistant_text", {"text": item.get("text", "")})]
        if t == "reasoning":
            return [("thinking", {"text": item.get("text", "")})]
        if t == "command_execution":
            return [
                (
                    "command",
                    {
                        "id": item_id,
                        "command": item.get("command", ""),
                        "output": clip(str(item.get("aggregated_output") or "")),
                        "exit_code": item.get("exit_code"),
                    },
                )
            ]
        if t == "file_change":
            return [("file_change", {"changes": item.get("changes") or []})]
        if t == "mcp_tool_call":
            name = f"{item.get('server')}.{item.get('tool')}"
            error = item.get("error") or None
            output = (
                str(error.get("message"))
                if isinstance(error, dict)
                else _tool_result_text((item.get("result") or {}).get("content"))
            )
            return [
                (
                    "tool_call",
                    {"id": item_id, "name": name, "input": clip_input(item.get("arguments"))},
                ),
                ("tool_result", {"id": item_id, "output": clip(output), "is_error": bool(error)}),
            ]
        if t == "web_search":
            return [
                (
                    "tool_call",
                    {"id": item_id, "name": "WebSearch", "input": {"query": item.get("query")}},
                )
            ]
        if t == "error":
            return [("error", {"message": str(item.get("message", "Error"))})]
        return []


class Codex:
    info = ProviderInfo(
        id="codex",
        name="Codex",
        capabilities=Capabilities(
            streaming=True,
            follow_ups=True,
            interrupt=True,
            live_files=True,
            images=True,
            runs_on="self",
        ),
        credential_help=(
            "Run `codex login` on your computer (it uses your ChatGPT plan) and paste the "
            "contents of ~/.codex/auth.json. An OpenAI API key (sk-…) also works."
        ),
        credential_key="codex",
    )

    def command(self, ctx: TurnContext) -> list[str]:
        task = ctx.task
        argv = [
            *shlex.split(ctx.settings.codex_bin),
            "exec",
            "--json",
            "--skip-git-repo-check",
            # The sandbox is the safety boundary; there is nobody to approve prompts.
            "--dangerously-bypass-approvals-and-sandbox",
        ]
        if task.model:
            argv += ["--model", task.model]
        if task.session_id and not ctx.first_turn:
            argv += ["resume", task.session_id]
        # "-": read the prompt from stdin.
        return [*argv, "-"]

    def prompt(self, ctx: TurnContext, text: str) -> str:
        # Codex has no flag for extra instructions; the first message carries them.
        if ctx.images:
            # Relative to the workspace, which is where the agent runs.
            paths = "\n".join(f"../attachments/{path.name}" for path in ctx.images)
            text = f"{text}\n\nImages attached to this message (view them):\n{paths}"
        if ctx.first_turn:
            return f"{ide_rules(ctx.task)}\n\n{text}"
        return text

    def env(self, ctx: TurnContext) -> dict[str, str]:
        cred = (ctx.credential or "").strip()
        if cred.startswith("sk-"):
            return {"OPENAI_API_KEY": cred, "CODEX_API_KEY": cred}
        return {}

    def setup_home(self, ctx: TurnContext) -> None:
        cred = (ctx.credential or "").strip()
        if cred.startswith("{"):
            write_login_file(ctx.home, ".codex/auth.json", cred)

    def parser(self) -> OutputParser:
        return CodexParser()


class DispatchParser:
    """Reads the plain output of a hand-off CLI: finds the vendor's task URL and any
    status markers our scripts print; everything else is shown as CLI output."""

    def __init__(self, url_pattern: str, vendor: str, messages: dict[str, str]) -> None:
        self.result = TurnResult()
        self._url = re.compile(url_pattern)
        self._vendor = vendor
        self._messages = messages
        self._announced = False

    def parse(self, line: str) -> list[Event]:
        stripped = line.strip()
        if not stripped:
            return []
        if stripped in self._messages:
            return [("assistant_text", {"text": self._messages[stripped]})]
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and "ok" in data:
            if data.get("session_id"):
                self.result.session_id = str(data["session_id"])
            if not data.get("ok"):
                self.result.failed = True
                return [("error", {"message": str(data.get("error") or "The hand-off failed")})]
            url = data.get("url")
            link = f" [Open it]({url})" if url else ""
            return [("assistant_text", {"text": f"Sent to {self._vendor}.{link}"})]
        match = self._url.search(stripped)
        if match and not self._announced:
            self._announced = True
            self.result.session_id = match.group(1)
            text = (
                f"{self._vendor} is working on this in its own cloud. "
                f"[Follow it there]({match.group(0)})."
            )
            return [("assistant_text", {"text": text}), ("link", {"url": match.group(0)})]
        return [("log", {"text": line})]


class CodexCloud:
    info = ProviderInfo(
        id="codex-cloud",
        name="Codex Cloud (hand-off)",
        capabilities=Capabilities(
            streaming=False,
            follow_ups=True,
            interrupt=False,
            live_files=False,
            images=False,
            runs_on="vendor",
        ),
        credential_help=(
            "Uses your Codex login (the same auth.json as Codex) and the environment set in "
            "settings.json as ai.codexCloudEnvironment. The task runs on OpenAI's servers; "
            "send any message to fetch its result into the workspace."
        ),
        credential_key="codex",
        experimental=True,
    )

    def command(self, ctx: TurnContext) -> list[str]:
        codex = shlex.join(shlex.split(ctx.settings.codex_bin))
        if ctx.first_turn:
            env_id = str(ctx.user_settings.get("ai.codexCloudEnvironment") or "")
            if not env_id:
                return ["sh", "-c", "echo ZIMUA_NO_ENVIRONMENT; exit 2"]
            script = f'{codex} cloud exec --env "$1" --branch "$2" "$(cat)"'
            return ["sh", "-c", script, "sh", env_id, ctx.task.base_branch]
        # Follow-ups fetch the result: Codex Cloud can't take more instructions from a CLI.
        script = f"""
id="$1"
if ! {codex} cloud status "$id"; then echo ZIMUA_NOT_READY; exit 0; fi
{codex} cloud diff "$id" > ../turns/codex-cloud.diff || exit 1
diff=../turns/codex-cloud.diff
if git apply -R --check "$diff" 2>/dev/null; then echo ZIMUA_ALREADY_APPLIED; exit 0; fi
git apply --whitespace=nowarn "$diff" && echo ZIMUA_APPLIED
"""
        return ["sh", "-c", script, "sh", ctx.task.session_id or ""]

    def prompt(self, ctx: TurnContext, text: str) -> str:
        return text

    def env(self, ctx: TurnContext) -> dict[str, str]:
        return Codex().env(ctx)

    def setup_home(self, ctx: TurnContext) -> None:
        Codex().setup_home(ctx)

    def parser(self) -> OutputParser:
        return DispatchParser(
            r"https://chatgpt\.com/codex/tasks/([A-Za-z0-9_-]+)",
            "Codex Cloud",
            {
                "ZIMUA_NOT_READY": "Codex Cloud hasn't finished yet. Send another message later "
                "to check again.",
                "ZIMUA_APPLIED": "Applied Codex Cloud's changes to this workspace. Review them "
                "under Changes, then create a pull request.",
                "ZIMUA_ALREADY_APPLIED": "Codex Cloud's changes are already in this workspace.",
                "ZIMUA_NO_ENVIRONMENT": "Set ai.codexCloudEnvironment in settings.json to your "
                "Codex Cloud environment id first.",
            },
        )


_ALL: list[AgentProvider] = [ClaudeCode(), Codex(), CodexCloud()]
PROVIDERS: dict[str, AgentProvider] = {p.info.id: p for p in _ALL}
