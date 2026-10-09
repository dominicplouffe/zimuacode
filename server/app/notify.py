"""Web Push notifications: an agent finished or failed, or CI failed on its pull request."""

import asyncio
import base64
import json
import logging
from functools import cached_property
from typing import Any

import httpx
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from sqlmodel import Session, select

from app.config import Settings
from app.db import get_engine
from app.models import PushSubscription, User

log = logging.getLogger(__name__)

CI_POLL_SECONDS = 30
CI_WATCH_SECONDS = 2 * 3600


class Notifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._background: set[asyncio.Task[None]] = set()

    @cached_property
    def _vapid(self) -> Vapid:
        # Generated once and kept with the server's data, so subscriptions stay valid.
        path = self.settings.data_dir / "vapid.pem"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            key = Vapid()
            key.generate_keys()
            key.save_key(str(path))
            path.chmod(0o600)
        return Vapid.from_file(str(path))

    @property
    def public_key(self) -> str:
        raw = self._vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    def _enabled_for(self, user_id: int) -> bool:
        from app.api.settings import effective

        with Session(get_engine()) as s:
            user = s.get(User, user_id)
        return bool(user and effective(user.settings_json).get("notifications.enabled", True))

    def _send_all(self, user_id: int, payload: dict[str, Any]) -> None:
        with Session(get_engine()) as s:
            subs = s.exec(select(PushSubscription).where(PushSubscription.user_id == user_id)).all()
            for sub in subs:
                try:
                    webpush(
                        {
                            "endpoint": sub.endpoint,
                            "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                        },
                        data=json.dumps(payload),
                        vapid_private_key=self._vapid,
                        vapid_claims={"sub": f"mailto:zimua@{_host(self.settings.public_url)}"},
                        ttl=24 * 3600,
                        timeout=10,
                    )
                except WebPushException as e:
                    status = getattr(e.response, "status_code", None)
                    if status in (404, 410):
                        # The browser dropped this subscription.
                        s.delete(sub)
                    else:
                        log.warning("push to %s failed: %s", sub.endpoint[:40], e)
                except Exception:
                    log.exception("push failed")
            s.commit()

    def notify(self, user_id: int, title: str, body: str, url: str, tag: str | None = None) -> None:
        """Sends in the background; notifications must never slow the runner down."""
        if not self._enabled_for(user_id):
            return
        payload = {"title": title, "body": body, "url": url, "tag": tag}
        self._spawn(asyncio.to_thread(self._send_all, user_id, payload))

    def task_link(self, task_id: str) -> str:
        return f"{self.settings.public_url.rstrip('/')}/#task={task_id}"

    def pr_link(self, owner: str, name: str, number: int) -> str:
        return f"{self.settings.public_url.rstrip('/')}/#pr={owner}/{name}/{number}"

    def watch_ci(
        self, user_id: int, http: httpx.AsyncClient, token: str, owner: str, name: str, number: int
    ) -> None:
        """Polls a PR's checks after a push and notifies if any fail."""
        self._spawn(self._watch_ci(user_id, http, token, owner, name, number))

    async def _watch_ci(
        self, user_id: int, http: httpx.AsyncClient, token: str, owner: str, name: str, number: int
    ) -> None:
        from app.github.client import GitHub

        gh = GitHub(http, token, self.settings.github_api_url)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + CI_WATCH_SECONDS
        try:
            head = (await gh.pull(owner, name, number))["head"]["sha"]
            while loop.time() < deadline:
                await asyncio.sleep(CI_POLL_SECONDS)
                runs = await gh.check_runs(owner, name, head)
                if not runs or any(r["status"] != "completed" for r in runs):
                    continue
                failed = [
                    r["name"]
                    for r in runs
                    if r.get("conclusion") not in ("success", "neutral", "skipped")
                ]
                if failed:
                    self.notify(
                        user_id,
                        f"CI failed on PR #{number}",
                        f"{owner}/{name}: {', '.join(failed[:3])}",
                        self.pr_link(owner, name, number),
                        tag=f"ci-{owner}-{name}-{number}",
                    )
                return
        except Exception:
            log.exception("watching CI for %s/%s#%s failed", owner, name, number)

    def _spawn(self, coro: Any) -> None:
        job = asyncio.ensure_future(coro)
        self._background.add(job)
        job.add_done_callback(self._background.discard)

    async def aclose(self) -> None:
        for job in list(self._background):
            job.cancel()
        await asyncio.gather(*self._background, return_exceptions=True)


def _host(url: str) -> str:
    return httpx.URL(url).host or "localhost"
