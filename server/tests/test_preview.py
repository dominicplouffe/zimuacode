import asyncio
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
import websockets
from fastapi.testclient import TestClient

from app.config import get_settings
from app.preview import _headers
from tests.helpers import start, wait_for

PREVIEW = "http://testserver"  # TestClient's websocket host, so both protocols can be tested


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def ide(
    runner_env: None, gh: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("ZIMUA_PREVIEW_URL", PREVIEW)
    # The proxy's own requests go to real local servers.
    gh.route(host="127.0.0.1").pass_through()
    get_settings.cache_clear()
    from app.main import create_asgi

    with TestClient(create_asgi(), base_url="http://ide.test") as c:
        c.post("/api/auth/dev-login", json={"token": "ghtok"})
        c.headers["x-zimua"] = "1"
        yield c


@pytest.fixture
def task_id(ide: TestClient) -> str:
    task_id = start(ide, "Add notes")
    wait_for(ide, task_id, "idle")
    return task_id


def open_preview(ide: TestClient, task_id: str, port: int) -> TestClient:
    link = ide.post(f"/api/tasks/{task_id}/preview", json={"port": port}).json()["url"]
    assert link.startswith(f"{PREVIEW}/__zimua/open?token=")
    browser = TestClient(ide.app, base_url=PREVIEW)
    resp = browser.get(link.removeprefix(PREVIEW), follow_redirects=False)
    assert resp.status_code == 302
    assert "zimua_preview=" in resp.headers["set-cookie"]
    assert "HttpOnly" in resp.headers["set-cookie"]
    return browser


def test_http_preview(ide: TestClient, task_id: str) -> None:
    port = free_port()
    workspace = Path(get_settings().data_dir) / "tasks" / task_id / "repo"
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=workspace, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        browser = open_preview(ide, task_id, port)
        deadline = time.monotonic() + 10
        while True:
            resp = browser.get("/AGENT.md")
            if resp.status_code == 200 or time.monotonic() > deadline:
                break
            time.sleep(0.1)
        assert resp.text == "Add notes\n"
        # The preview origin never serves the IDE.
        assert browser.get("/api/auth/me").status_code == 404
    finally:
        server.terminate()
        server.wait()
    resp = browser.get("/AGENT.md")
    assert resp.status_code == 502
    assert "Nothing is answering on port" in resp.text


def test_preview_needs_the_link(ide: TestClient, task_id: str) -> None:
    browser = TestClient(ide.app, base_url=PREVIEW)
    assert browser.get("/").status_code == 401
    assert browser.get("/__zimua/open?token=forged").status_code == 401


def test_websocket_preview(ide: TestClient, task_id: str) -> None:
    port = free_port()
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    stop = asyncio.Event()

    async def echo(conn: websockets.ServerConnection) -> None:
        async for message in conn:
            await conn.send(f"echo:{message}")

    async def serve() -> None:
        async with websockets.serve(echo, "127.0.0.1", port, subprotocols=["vite-hmr"]):
            ready.set()
            await stop.wait()

    thread = threading.Thread(target=loop.run_until_complete, args=(serve(),), daemon=True)
    thread.start()
    ready.wait(5)
    try:
        browser = open_preview(ide, task_id, port)
        cookie = f"zimua_preview={browser.cookies['zimua_preview']}"
        with browser.websocket_connect(
            "/hmr", headers={"cookie": cookie}, subprotocols=["vite-hmr"]
        ) as ws:
            assert ws.accepted_subprotocol == "vite-hmr"
            ws.send_text("hello")
            assert ws.receive_text() == "echo:hello"
    finally:
        loop.call_soon_threadsafe(stop.set)
        thread.join(5)


def test_proxy_strips_its_own_cookie_and_hop_headers() -> None:
    scope = {
        "headers": [
            (b"cookie", b"zimua_preview=abc; theme=dark"),
            (b"connection", b"keep-alive"),
            (b"accept", b"text/html"),
        ]
    }
    assert _headers(scope) == [("cookie", "theme=dark"), ("accept", "text/html")]
    assert _headers({"headers": [(b"cookie", b"zimua_preview=abc")]}) == []
