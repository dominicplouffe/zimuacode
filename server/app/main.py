from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp

from app.api import auth, commits, pulls, push, repo_config, repos, settings, tasks, terminal
from app.config import DEV_SECRET_KEY, get_settings
from app.db import init_db
from app.notify import Notifier
from app.preview import PreviewProxy
from app.tasks.events import EventBus
from app.tasks.manager import TaskManager
from app.tasks.sandbox import make_sandbox
from app.tasks.terminal import Terminals


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.cookie_secure and settings.secret_key == DEV_SECRET_KEY:
        raise RuntimeError("Set ZIMUA_SECRET_KEY before running in production")
    init_db()
    notifier = Notifier(settings)
    app.state.notifier = notifier
    manager = TaskManager(settings, EventBus(), make_sandbox(settings), notifier)
    app.state.tasks = manager
    app.state.terminals = Terminals(settings)
    await manager.recover()
    async with httpx.AsyncClient(timeout=30) as http:
        app.state.http = http
        try:
            yield
        finally:
            app.state.terminals.close_all()
            await manager.shutdown()
            await notifier.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Zimua Code", version="0.1.0", lifespan=lifespan)
    app.include_router(auth.router)
    app.include_router(repos.router)
    app.include_router(settings.router)
    app.include_router(commits.router)
    app.include_router(pulls.router)
    app.include_router(tasks.router)
    app.include_router(repo_config.router)
    app.include_router(terminal.router)
    app.include_router(push.router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    dist = get_settings().web_dist
    if dist is not None and dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404)
            file = (dist / path).resolve()
            if path and file.is_file() and file.is_relative_to(dist.resolve()):
                return FileResponse(file)
            return FileResponse(dist / "index.html")

    return app


def create_asgi() -> ASGIApp:
    """The IDE app, behind the preview proxy when previews are enabled."""
    settings = get_settings()
    app = create_app()
    return PreviewProxy(app, settings) if settings.preview_url else app


app = create_asgi()
