import json
import re
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.deps import DbDep, UserDep
from app.models import RepoConfig
from app.security import decrypt, encrypt

router = APIRouter(prefix="/api/repos", tags=["agent config"])

ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Set by the runner itself; a repo variable must not override them.
RESERVED = {"HOME", "PATH"}


class AgentConfig(BaseModel):
    # Names only: values are write-only.
    env_keys: list[str]
    setup_script: str


class AgentConfigUpdate(BaseModel):
    # name -> value to set, or None to delete. Names not listed are left as they are.
    env: dict[str, str | None] = Field(default_factory=dict)
    setup_script: str | None = None


def _load(db: DbDep, user_id: int, owner: str, name: str) -> tuple[RepoConfig, dict[str, str]]:
    row = db.get(RepoConfig, (user_id, owner, name)) or RepoConfig(
        user_id=user_id, owner=owner, name=name
    )
    env: dict[str, str] = json.loads(decrypt(row.env_enc)) if row.env_enc else {}
    return row, env


@router.get("/{owner}/{name}/agent-config")
def get_agent_config(owner: str, name: str, user: UserDep, db: DbDep) -> AgentConfig:
    row, env = _load(db, user.id or 0, owner, name)
    return AgentConfig(env_keys=sorted(env), setup_script=row.setup_script)


@router.put("/{owner}/{name}/agent-config")
def update_agent_config(
    owner: str, name: str, body: AgentConfigUpdate, user: UserDep, db: DbDep
) -> AgentConfig:
    row, env = _load(db, user.id or 0, owner, name)
    for key, value in body.env.items():
        if not ENV_NAME.match(key) or key in RESERVED:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"Invalid variable name {key}"
            )
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    row.env_enc = encrypt(json.dumps(env)) if env else ""
    if body.setup_script is not None:
        row.setup_script = body.setup_script
    row.updated_at = datetime.now(UTC)
    db.add(row)
    db.commit()
    return AgentConfig(env_keys=sorted(env), setup_script=row.setup_script)
