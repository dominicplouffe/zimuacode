import json
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from app.config import get_settings
from app.deps import DbDep, UserDep

router = APIRouter(prefix="/api", tags=["settings"])


@lru_cache
def _schema() -> dict[str, Any]:
    result: dict[str, Any] = json.loads(
        (get_settings().shared_dir / "settings.schema.json").read_text()
    )
    return result


def defaults() -> dict[str, Any]:
    return {key: prop["default"] for key, prop in _schema()["properties"].items()}


class UserSettings(BaseModel):
    # The user's settings.json text, exactly as saved.
    raw: str
    # Defaults overlaid with the user's values.
    effective: dict[str, Any]
    json_schema: dict[str, Any]


class SaveSettings(BaseModel):
    raw: str


def effective(raw: str) -> dict[str, Any]:
    try:
        user = json.loads(raw)
    except json.JSONDecodeError:
        user = {}
    return defaults() | (user if isinstance(user, dict) else {})


def _response(raw: str) -> UserSettings:
    return UserSettings(raw=raw, effective=effective(raw), json_schema=_schema())


@router.get("/settings")
def get_user_settings(user: UserDep) -> UserSettings:
    return _response(user.settings_json)


@router.put("/settings")
def save_user_settings(body: SaveSettings, user: UserDep, db: DbDep) -> UserSettings:
    try:
        value = json.loads(body.raw)
    except json.JSONDecodeError as e:
        raise HTTPException(422, f"settings.json is not valid JSON: {e}") from e
    errors = sorted(Draft202012Validator(_schema()).iter_errors(value), key=lambda e: e.path)
    if errors:
        first = errors[0]
        where = ".".join(str(p) for p in first.path) or "settings"
        raise HTTPException(422, f"{where}: {first.message}")
    user.settings_json = body.raw
    db.add(user)
    db.commit()
    return _response(body.raw)


class Theme(BaseModel):
    id: str
    name: str
    type: str
    colors: dict[str, str]
    tokenColors: list[dict[str, Any]]


@router.get("/themes")
def list_themes() -> list[Theme]:
    themes = []
    for path in sorted((get_settings().shared_dir / "themes").glob("*.json")):
        data = json.loads(path.read_text())
        themes.append(
            Theme(
                id=path.stem,
                name=data.get("name", path.stem),
                type=data.get("type", "dark"),
                colors=data.get("colors", {}),
                tokenColors=data.get("tokenColors", []),
            )
        )
    return themes
