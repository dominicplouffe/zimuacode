"""App previews: a reverse proxy, on its own origin, to a port in a task's workspace.

Opening a preview goes through a short-lived signed link, which sets a cookie on the
preview origin naming the task and port. Every request to the preview origin is then
forwarded there, WebSockets included (for dev servers' hot reload). Being a different
origin from the IDE, the previewed app can't read or use the IDE's session.
"""

import asyncio
import contextlib
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import websockets
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings
from app.security import sign, unsign
from app.tasks.sandbox import DockerSandbox

COOKIE = "zimua_preview"
LINK_SALT = "preview-link"
COOKIE_SALT = "preview-cookie"
LINK_MAX_AGE = 120
COOKIE_MAX_AGE = 7 * 86400
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
    "transfer-encoding", "upgrade", "host", "content-length",
}  # fmt: skip


def preview_link(settings: Settings, user_id: int, task_id: str, port: int) -> str:
    token = sign({"uid": user_id, "task": task_id, "port": port}, LINK_SALT)
    return f"{settings.preview_url.rstrip('/')}/__zimua/open?token={token}"


def _cookie(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"cookie":
            for part in value.decode(errors="replace").split(";"):
                key, _, val = part.strip().partition("=")
                if key == COOKIE:
                    return str(val)
    return None


def _headers(scope: Scope) -> list[tuple[str, str]]:
    out = []
    for name, value in scope.get("headers", []):
        key = name.decode().lower()
        if key in HOP_BY_HOP or key.startswith("sec-websocket"):
            continue
        if key == "cookie":
            # Don't hand our own cookie to the previewed app.
            kept = [
                p
                for p in value.decode(errors="replace").split(";")
                if not p.strip().startswith(COOKIE + "=")
            ]
            if not kept:
                continue
            out.append((key, ";".join(kept).strip()))
            continue
        out.append((key, value.decode(errors="replace")))
    return out


class PreviewProxy:
    """ASGI middleware: requests for the preview host are proxied; others pass through."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self.host = urlsplit(settings.preview_url).netloc if settings.preview_url else None
        self._http: httpx.AsyncClient | None = None

    def _is_preview(self, scope: Scope) -> bool:
        if not self.host or scope["type"] not in ("http", "websocket"):
            return False
        host = dict(scope.get("headers", [])).get(b"host", b"").decode()
        return bool(host == self.host)

    def target(self, task_id: str, port: int) -> str:
        if self.settings.sandbox == "docker":
            return f"{DockerSandbox.container(task_id)}:{port}"
        return f"127.0.0.1:{port}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_preview(scope):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http" and scope["path"] == "/__zimua/open":
            await self._open(scope, send)
            return
        cookie = _cookie(scope)
        data = unsign(cookie, COOKIE_SALT, COOKIE_MAX_AGE) if cookie else None
        if not isinstance(data, dict):
            await _text(send, 401, "Open this preview from the IDE.") if scope[
                "type"
            ] == "http" else None
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 4401})
            return
        target = self.target(str(data["task"]), int(data["port"]))
        if scope["type"] == "http":
            await self._proxy_http(scope, receive, send, target)
        else:
            await self._proxy_ws(scope, receive, send, target)

    async def _open(self, scope: Scope, send: Send) -> None:
        token = parse_qs(scope.get("query_string", b"").decode()).get("token", [""])[0]
        data = unsign(token, LINK_SALT, LINK_MAX_AGE) if token else None
        if not isinstance(data, dict):
            await _text(send, 401, "This preview link has expired. Open it again from the IDE.")
            return
        cookie = sign({"task": data["task"], "port": data["port"], "uid": data["uid"]}, COOKIE_SALT)
        secure = "; Secure" if self.settings.preview_url.startswith("https") else ""
        await send(
            {
                "type": "http.response.start",
                "status": 302,
                "headers": [
                    (b"location", b"/"),
                    (
                        b"set-cookie",
                        (
                            f"{COOKIE}={cookie}; Path=/; HttpOnly; SameSite=Lax; "
                            f"Max-Age={COOKIE_MAX_AGE}{secure}"
                        ).encode(),
                    ),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    async def _proxy_http(self, scope: Scope, receive: Receive, send: Send, target: str) -> None:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5))
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        url = f"http://{target}{scope.get('raw_path', scope['path'].encode()).decode()}"
        if scope.get("query_string"):
            url += "?" + scope["query_string"].decode()
        request = self._http.build_request(
            scope["method"], url, headers=_headers(scope) + [("host", target)], content=body
        )
        try:
            upstream = await self._http.send(request, stream=True, follow_redirects=False)
        except httpx.HTTPError:
            port = target.rsplit(":", 1)[1]
            await _text(
                send,
                502,
                f"Nothing is answering on port {port} in this task's workspace. Start the dev "
                "server (bound to 0.0.0.0), e.g. from the task's terminal.",
            )
            return
        try:
            headers = [
                (k.encode(), v.encode())
                for k, v in upstream.headers.multi_items()
                if k.lower() not in HOP_BY_HOP and k.lower() != "content-encoding"
            ]
            await send(
                {"type": "http.response.start", "status": upstream.status_code, "headers": headers}
            )
            # aiter_bytes decodes compression, which is why content-encoding is dropped above.
            async for chunk in upstream.aiter_bytes():
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b""})
        finally:
            await upstream.aclose()

    async def _proxy_ws(self, scope: Scope, receive: Receive, send: Send, target: str) -> None:
        message = await receive()
        if message["type"] != "websocket.connect":
            return
        path = scope.get("raw_path", scope["path"].encode()).decode()
        if scope.get("query_string"):
            path += "?" + scope["query_string"].decode()
        protocols = scope.get("subprotocols") or None
        try:
            upstream = await websockets.connect(
                f"ws://{target}{path}",
                subprotocols=protocols,
                additional_headers=[h for h in _headers(scope) if h[0] != "origin"],
                open_timeout=5,
            )
        except Exception:
            await send({"type": "websocket.close", "code": 1011})
            return
        await send({"type": "websocket.accept", "subprotocol": upstream.subprotocol})

        async def downstream_to_upstream() -> None:
            while True:
                msg = await receive()
                if msg["type"] == "websocket.disconnect":
                    await upstream.close()
                    return
                data: Any = msg.get("bytes") if msg.get("bytes") is not None else msg.get("text")
                await upstream.send(data)

        async def upstream_to_downstream() -> None:
            async for data in upstream:
                if isinstance(data, bytes):
                    await send({"type": "websocket.send", "bytes": data})
                else:
                    await send({"type": "websocket.send", "text": data})
            await send({"type": "websocket.close", "code": 1000})

        tasks = [
            asyncio.create_task(downstream_to_upstream()),
            asyncio.create_task(upstream_to_downstream()),
        ]
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await t
        with contextlib.suppress(Exception):
            await upstream.close()

    async def aclose(self) -> None:
        if self._http:
            await self._http.aclose()


async def _text(send: Send, status: int, text: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"text/plain; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": text.encode()})
