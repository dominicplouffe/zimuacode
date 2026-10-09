import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import select

from app.config import Settings
from app.deps import SESSION_COOKIE, SESSION_SALT, DbDep, HttpDep, SettingsDep, UserDep
from app.github.client import GitHub, GitHubError
from app.models import User
from app.security import encrypt, sign

router = APIRouter(prefix="/api/auth", tags=["auth"])

STATE_COOKIE = "zimua_oauth_state"
OAUTH_SCOPES = "repo read:org workflow"


class Me(BaseModel):
    login: str
    name: str | None
    avatar_url: str | None


def _set_session(response: Response, user: User, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        sign({"uid": user.id}, SESSION_SALT),
        max_age=settings.session_max_age_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def _check_allowed(gh_user: dict[str, object], settings: Settings) -> None:
    allowed = settings.allowed_github_login.lower()
    if not allowed or str(gh_user["login"]).lower() != allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This GitHub account is not allowed")


def _upsert_user(db: DbDep, gh_user: dict[str, object], token: str) -> User:
    github_id = int(str(gh_user["id"]))
    user = db.exec(select(User).where(User.github_id == github_id)).first()
    if user is None:
        user = User(github_id=github_id, login=str(gh_user["login"]), token_enc="")
    user.login = str(gh_user["login"])
    user.name = gh_user.get("name") or None  # type: ignore[assignment]
    user.avatar_url = gh_user.get("avatar_url") or None  # type: ignore[assignment]
    user.token_enc = encrypt(token)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/login")
def login(settings: SettingsDep) -> RedirectResponse:
    if not settings.github_client_id or not settings.allowed_github_login:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Set ZIMUA_GITHUB_CLIENT_ID and ZIMUA_ALLOWED_GITHUB_LOGIN",
        )
    state = secrets.token_urlsafe(24)
    query = urlencode(
        {
            "client_id": settings.github_client_id,
            "redirect_uri": f"{settings.public_url}/api/auth/callback",
            "scope": OAUTH_SCOPES,
            "state": state,
            "allow_signup": "false",
        }
    )
    response = RedirectResponse(f"{settings.github_oauth_url}/login/oauth/authorize?{query}")
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response


@router.get("/callback")
async def callback(
    request: Request, code: str, state: str, db: DbDep, http: HttpDep, settings: SettingsDep
) -> RedirectResponse:
    expected = request.cookies.get(STATE_COOKIE)
    if not expected or not secrets.compare_digest(expected, state):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OAuth state mismatch")

    resp = await http.post(
        f"{settings.github_oauth_url}/login/oauth/access_token",
        data={
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
            "redirect_uri": f"{settings.public_url}/api/auth/callback",
        },
        headers={"Accept": "application/json"},
    )
    token = resp.json().get("access_token") if resp.status_code == 200 else None
    if not token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "GitHub did not return a token")

    try:
        gh_user = await GitHub(http, token, settings.github_api_url).user()
    except GitHubError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, e.message) from e
    _check_allowed(gh_user, settings)
    user = _upsert_user(db, gh_user, token)
    response = RedirectResponse(settings.public_url + "/")
    response.delete_cookie(STATE_COOKIE)
    _set_session(response, user, settings)
    return response


class DevLogin(BaseModel):
    token: str


@router.post("/dev-login", include_in_schema=False)
async def dev_login(
    body: DevLogin, response: Response, db: DbDep, http: HttpDep, settings: SettingsDep
) -> Me:
    """Signs in with a GitHub token directly. Disabled unless ZIMUA_DEV_LOGIN=1."""
    if not settings.dev_login:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    gh_user = await GitHub(http, body.token, settings.github_api_url).user()
    _check_allowed(gh_user, settings)
    user = _upsert_user(db, gh_user, body.token)
    _set_session(response, user, settings)
    return Me(login=user.login, name=user.name, avatar_url=user.avatar_url)


@router.get("/me")
def me(user: UserDep) -> Me:
    return Me(login=user.login, name=user.name, avatar_url=user.avatar_url)


@router.post("/logout")
def logout(response: Response, _user: UserDep) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}
