from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
