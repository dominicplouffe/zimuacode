"""Agent providers: how to run each CLI and how to read its output.

Adding a provider means writing one class with these methods and registering it in
PROVIDERS. The runner, event stream and UI work for it unchanged.
"""

import json
import shlex
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from app.config import Settings

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
    # "self": runs on this server's runner. "vendor": hands off to the vendor's cloud.
    runs_on: str


class ProviderInfo(BaseModel):
    id: str
    name: str
    capabilities: Capabilities
    credential_help: str


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


class AgentProvider(Protocol):
    info: ProviderInfo

    def command(
        self,
        settings: Settings,
        *,
        model: str | None,
        session_id: str | None,
        first_turn: bool,
        branch: str,
    ) -> list[str]: ...

    def env(self, credential: str | None) -> dict[str, str]: ...

    def setup_home(self, home: Any, credential: str | None) -> None:
        """Writes any files the CLI needs in its HOME (e.g. a login file)."""

    def parser(self) -> OutputParser: ...


def ide_rules(branch: str) -> str:
    return (
        "You are running inside Zimua Code, a web IDE, in a workspace checked out on branch "
        f"`{branch}`. The user reviews your changes in the IDE and pushes and opens pull "
        "requests from there, so do not run `git push` or create pull requests yourself. "
        "You may commit if it helps, but it isn't required."
    )


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
            streaming=True, follow_ups=True, interrupt=True, live_files=True, runs_on="self"
        ),
        credential_help=(
            "Run `claude setup-token` on your computer (it uses your Claude Pro/Max "
            "subscription) and paste the token. An Anthropic API key (sk-ant-api…) also works."
        ),
    )

    def command(
        self,
        settings: Settings,
        *,
        model: str | None,
        session_id: str | None,
        first_turn: bool,
        branch: str,
    ) -> list[str]:
        argv = [
            *shlex.split(settings.claude_bin),
            "-p",
            "--output-format", "stream-json",
            "--verbose",
            # The sandbox is the safety boundary; there is nobody to approve prompts.
            "--dangerously-skip-permissions",
            "--append-system-prompt", ide_rules(branch),
        ]  # fmt: skip
        if model:
            argv += ["--model", model]
        if session_id:
            argv += ["--session-id" if first_turn else "--resume", session_id]
        return argv

    def env(self, credential: str | None) -> dict[str, str]:
        if not credential:
            return {}
        if credential.startswith("sk-ant-api"):
            return {"ANTHROPIC_API_KEY": credential}
        return {"CLAUDE_CODE_OAUTH_TOKEN": credential}

    def setup_home(self, home: Any, credential: str | None) -> None:
        pass

    def parser(self) -> OutputParser:
        return ClaudeParser()


PROVIDERS: dict[str, AgentProvider] = {p.info.id: p for p in [ClaudeCode()]}
