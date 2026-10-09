import asyncio
import contextlib
import json
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from sqlmodel import Session

from app.api.tasks import ManagerDep, _own_task, _workspace
from app.config import get_settings
from app.db import get_engine
from app.deps import SESSION_COOKIE, UserDep, user_for_token
from app.tasks.manager import TaskManager, repo_config
from app.tasks.terminal import Terminals

router = APIRouter(prefix="/api", tags=["terminal"])


def _origin_ok(ws: WebSocket) -> bool:
    """Browsers always send Origin on WebSockets, and cookies ride along cross-site, so
    only our own origins may connect."""
    origin = ws.headers.get("origin")
    if origin is None:
        return True
    allowed = {urlsplit(get_settings().public_url).netloc, ws.headers.get("host")}
    return urlsplit(origin).netloc in allowed


@router.websocket("/tasks/{task_id}/terminal")
async def terminal_socket(ws: WebSocket, task_id: str) -> None:
    manager: TaskManager = ws.app.state.tasks
    terminals: Terminals = ws.app.state.terminals
    token = ws.cookies.get(SESSION_COOKIE) or ws.query_params.get("token")
    with Session(get_engine()) as db:
        user = user_for_token(db, token, get_settings())
    if user is None or not _origin_ok(ws):
        await ws.close(code=4401)
        return
    try:
        task = _own_task(manager, task_id, user)
        _workspace(manager, task)
        if task.status == "stopped":
            raise HTTPException(status.HTTP_409_CONFLICT)
    except HTTPException:
        await ws.close(code=4404)
        return

    env, _ = repo_config(task.user_id, task.repo_owner, task.repo_name)
    terminal = await terminals.open(task_id, env)
    await ws.accept()

    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    # Snapshot and subscribe with no await in between, so output is neither lost nor doubled.
    replay = bytes(terminal.buffer)
    terminal.listeners.add(queue.put_nowait)

    async def send() -> None:
        if replay:
            await ws.send_bytes(replay)
        while True:
            data = await queue.get()
            if data is None:
                await ws.send_text(json.dumps({"type": "exit", "code": terminal.exit_code}))
                await ws.close()
                return
            await ws.send_bytes(data)

    sender = asyncio.create_task(send())
    try:
        while True:
            message = json.loads(await ws.receive_text())
            if message.get("type") == "input":
                terminal.write(str(message.get("data", "")).encode())
            elif message.get("type") == "resize":
                terminal.resize(int(message["cols"]), int(message["rows"]))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        terminal.listeners.discard(queue.put_nowait)
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender


@router.delete("/tasks/{task_id}/terminal", status_code=status.HTTP_204_NO_CONTENT)
def close_terminal(task_id: str, request: Request, user: UserDep, manager: ManagerDep) -> None:
    _own_task(manager, task_id, user)
    request.app.state.terminals.close(task_id)
