from functools import lru_cache
from pathlib import Path

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

    # Enables POST /api/auth/dev-login. Only for local development and end-to-end tests.
    dev_login: bool = False
    cookie_secure: bool = False
    session_max_age_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
