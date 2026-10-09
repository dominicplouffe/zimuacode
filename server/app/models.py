from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    github_id: int = Field(unique=True, index=True)
    login: str
    name: str | None = None
    avatar_url: str | None = None
    # GitHub OAuth token, Fernet-encrypted.
    token_enc: str
    # Raw user settings.json text, kept verbatim so formatting survives round trips.
    settings_json: str = "{}"
    created_at: datetime = Field(default_factory=_now)


class ProviderCredential(SQLModel, table=True):
    """A login for an agent CLI (e.g. a `claude setup-token` token), Fernet-encrypted."""

    user_id: int = Field(foreign_key="user.id", primary_key=True)
    provider: str = Field(primary_key=True)
    value_enc: str
    updated_at: datetime = Field(default_factory=_now)


class RepoConfig(SQLModel, table=True):
    """Per-repository settings for agent tasks."""

    user_id: int = Field(foreign_key="user.id", primary_key=True)
    owner: str = Field(primary_key=True)
    name: str = Field(primary_key=True)
    # JSON object of environment variables, Fernet-encrypted. Values never leave the server.
    env_enc: str = ""
    # Runs in the workspace after cloning, before the agent starts (e.g. `npm ci`).
    setup_script: str = ""
    updated_at: datetime = Field(default_factory=_now)


class Task(SQLModel, table=True):
    """One agent conversation, working on its own branch in its own workspace."""

    id: str = Field(primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    provider: str
    model: str | None = None
    title: str
    repo_owner: str
    repo_name: str
    base_branch: str
    base_sha: str | None = None
    branch: str
    # preparing | running | idle | failed | interrupted | stopped
    status: str = "preparing"
    status_detail: str | None = None
    # The CLI's own conversation id, for resuming.
    session_id: str | None = None
    turn: int = 0
    # How far into the current turn's log the watcher has read.
    log_offset: int = 0
    interrupt_requested: bool = False
    # Follow-ups sent while the agent was working; they run after the current turn.
    # Each is {"text", "images": [attachment names]}. Older rows hold bare text.
    pending: list[Any] = Field(default_factory=list, sa_column=Column(JSON))
    cost_usd: float = 0
    input_tokens: int = 0
    output_tokens: int = 0
    pr_number: int | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class TaskEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(foreign_key="task.id", index=True)
    seq: int
    type: str
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class PushSubscription(SQLModel, table=True):
    """A browser's Web Push subscription, for notifications when the IDE isn't open."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    endpoint: str = Field(unique=True)
    p256dh: str
    auth: str
    created_at: datetime = Field(default_factory=_now)
