from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_SECRET_KEY = "dev-insecure-change-me"


class Settings(BaseSettings):
    """Server configuration, read from ZIMUA_* environment variables (or a .env file)."""

    model_config = SettingsConfigDict(env_prefix="ZIMUA_", env_file=".env", extra="ignore")

    # Public origin the browser uses. The OAuth callback and post-login redirect are built from it.
    public_url: str = "http://localhost:5173"
    secret_key: str = DEV_SECRET_KEY
    database_url: str = "sqlite:///./data/zimua.db"

    github_client_id: str = ""
    github_client_secret: str = ""
    # Single-user lock: only this GitHub login may sign in.
    allowed_github_login: str = ""
    github_api_url: str = "https://api.github.com"
    github_oauth_url: str = "https://github.com"

    shared_dir: Path = REPO_ROOT / "shared"
    # Built web app to serve at "/". Unset in development, where Vite serves it.
    web_dist: Path | None = None

    # Where task workspaces and agent logs live. With the docker sandbox it must be the same
    # path on the host and inside the server container (bind-mounted at the same location).
    data_dir: Path = Path("./data")
    # "docker": one container per task (isolated). "local": plain processes on this machine,
    # with no isolation; for development, or a VM dedicated to the agents.
    sandbox: Literal["local", "docker"] = "local"
    runner_image: str = "zimua-runner:latest"
    # Agent CLI commands. Overridable for tests (a fake agent) or custom installs.
    claude_bin: str = "claude"
    codex_bin: str = "codex"
    # Where task workspaces clone from. {owner} and {name} are filled in.
    git_url_template: str = "https://github.com/{owner}/{name}.git"

    # Enables POST /api/auth/dev-login. Only for local development and end-to-end tests.
    dev_login: bool = False
    cookie_secure: bool = False
    session_max_age_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
