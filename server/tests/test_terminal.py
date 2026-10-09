import json
import time

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.helpers import start, wait_for


def read_until(ws, needle: bytes, limit: int = 200) -> bytes:  # type: ignore[no-untyped-def]
    seen = b""
    for _ in range(limit):
        message = ws.receive()
        if message.get("bytes"):
            seen += message["bytes"]
            if needle in seen:
                return seen
        elif message.get("text"):
            seen += message["text"].encode()
            if needle in seen:
                return seen
    raise AssertionError(f"never saw {needle!r} in {seen[-500:]!r}")


def auth(client: TestClient, **extra: str) -> dict[str, str]:
    # websocket_connect ignores base_url, so the session cookie must be passed by hand.
    return {"cookie": f"zimua_session={client.cookies['zimua_session']}", **extra}


def test_terminal_runs_in_the_workspace_and_replays(app_client: TestClient) -> None:
    task_id = start(app_client, "Add notes")
    wait_for(app_client, task_id, "idle")
    url = f"/api/tasks/{task_id}/terminal"
    with app_client.websocket_connect(url, headers=auth(app_client)) as ws:
        ws.send_text(json.dumps({"type": "resize", "cols": 100, "rows": 30}))
        ws.send_text(json.dumps({"type": "input", "data": "cat AGENT.md; echo MARK$((40+2))\n"}))
        out = read_until(ws, b"MARK42")
        assert b"Add notes" in out
        ws.send_text(json.dumps({"type": "input", "data": "export KEEP=still-here\n"}))
        time.sleep(0.2)

    # The shell lives on; a new connection replays its output and keeps its state.
    with app_client.websocket_connect(url, headers=auth(app_client)) as ws:
        assert b"MARK42" in read_until(ws, b"MARK42")
        ws.send_text(json.dumps({"type": "input", "data": "echo $KEEP; exit\n"}))
        out = read_until(ws, b'"type": "exit"')
        assert b"still-here" in out


def test_terminal_secrets_and_auth(app_client: TestClient) -> None:
    task_id = start(app_client, "Add notes")
    wait_for(app_client, task_id, "idle")
    url = f"/api/tasks/{task_id}/terminal"
    with app_client.websocket_connect(url, headers=auth(app_client)) as ws:
        # $((1+1)) makes the output differ from the echoed command line.
        ws.send_text(
            json.dumps({"type": "input", "data": 'echo "S=[$ZIMUA_SECRET_KEY]$((1+1))"\n'})
        )
        assert b"S=[]2" in read_until(ws, b"]2")
    app_client.delete(url)

    for headers in (auth(app_client, origin="https://evil.example"),):
        try:
            with app_client.websocket_connect(url, headers=headers) as ws:
                ws.receive()
            raise AssertionError("connected")
        except WebSocketDisconnect as e:
            assert e.code == 4401
    try:
        with app_client.websocket_connect(url) as ws:
            ws.receive()
        raise AssertionError("connected")
    except WebSocketDisconnect as e:
        assert e.code == 4401
