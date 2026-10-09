from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.github.client import GitHub
from app.models import User
from app.security import decrypt, unsign

SESSION_COOKIE = "zimua_session"
SESSION_SALT = "session"
# Mutating requests must carry this header. Browsers can't add it cross-site without a
# CORS preflight, which this server never grants, so it blocks CSRF.
CSRF_HEADER = "x-zimua"

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_session)]


async def get_http(request: Request) -> AsyncIterator[httpx.AsyncClient]:
    yield request.app.state.http


HttpDep = Annotated[httpx.AsyncClient, Depends(get_http)]


def session_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return request.cookies.get(SESSION_COOKIE)


def user_for_token(db: Session, token: str | None, settings: Settings) -> User | None:
    data = unsign(token, SESSION_SALT, settings.session_max_age_days * 86400) if token else None
    return db.get(User, data.get("uid")) if isinstance(data, dict) else None


def current_user(request: Request, db: DbDep, settings: SettingsDep) -> User:
    user = user_for_token(db, session_token(request), settings)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    if request.method not in ("GET", "HEAD", "OPTIONS") and CSRF_HEADER not in request.headers:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing {CSRF_HEADER} header")
    return user


UserDep = Annotated[User, Depends(current_user)]


def get_github(user: UserDep, http: HttpDep, settings: SettingsDep) -> GitHub:
    return GitHub(http, decrypt(user.token_enc), settings.github_api_url)


GitHubDep = Annotated[GitHub, Depends(get_github)]
