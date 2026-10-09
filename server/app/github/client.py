"""Thin async wrapper over the GitHub REST API, scoped to what the IDE needs."""

from typing import Any
from urllib.parse import quote

import httpx

# Files larger than this open as "too large" rather than being loaded into the editor.
MAX_EDITOR_BYTES = 5 * 1024 * 1024


class GitHubError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class GitHub:
    def __init__(self, http: httpx.AsyncClient, token: str, base_url: str) -> None:
        self._http = http
        self._base = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str | None = None,
    ) -> httpx.Response:
        headers = dict(self._headers)
        if accept:
            headers["Accept"] = accept
        resp = await self._http.request(method, self._base + path, params=params, headers=headers)
        if resp.status_code >= 400:
            try:
                message = resp.json().get("message", resp.text)
            except ValueError:
                message = resp.text
            raise GitHubError(resp.status_code, message)
        return resp

    async def _json(self, path: str, **params: Any) -> Any:
        return (await self._request("GET", path, params=params or None)).json()

    async def user(self) -> dict[str, Any]:
        result: dict[str, Any] = await self._json("/user")
        return result

    async def repos(self, page: int = 1, per_page: int = 100) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = await self._json(
            "/user/repos",
            affiliation="owner,collaborator,organization_member",
            sort="pushed",
            per_page=per_page,
            page=page,
        )
        return result

    async def repo(self, owner: str, name: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._json(f"/repos/{owner}/{name}")
        return result

    async def branches(self, owner: str, name: str, page: int = 1) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = await self._json(
            f"/repos/{owner}/{name}/branches", per_page=100, page=page
        )
        return result

    async def tree(self, owner: str, name: str, ref: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._json(
            f"/repos/{owner}/{name}/git/trees/{quote(ref, safe='')}", recursive="1"
        )
        return result

    async def file(self, owner: str, name: str, path: str, ref: str) -> bytes:
        resp = await self._request(
            "GET",
            f"/repos/{owner}/{name}/contents/{quote(path)}",
            params={"ref": ref},
            accept="application/vnd.github.raw+json",
        )
        return resp.content


def decode_text(data: bytes) -> str | None:
    """Returns the file as text, or None when it looks binary."""
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None
