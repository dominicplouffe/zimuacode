"""Thin async wrapper over the GitHub REST API, scoped to what the IDE needs."""

from typing import Any, cast
from urllib.parse import quote

import httpx

# Files larger than this open as "too large" rather than being loaded into the editor.
MAX_EDITOR_BYTES = 5 * 1024 * 1024
# CI logs can be huge; the IDE keeps the tail, where failures are.
MAX_LOG_BYTES = 2 * 1024 * 1024

JSON = dict[str, Any]


class GitHubError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _error_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text or resp.reason_phrase
    message = str(data.get("message", resp.text))
    errors = [e for e in data.get("errors", []) if isinstance(e, dict)]
    details = [
        str(e.get("message") or e.get("code")) for e in errors if e.get("message") or e.get("code")
    ]
    return f"{message}: {'; '.join(details)}" if details else message


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
        json: Any = None,
        accept: str | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        headers = dict(self._headers)
        if accept:
            headers["Accept"] = accept
        resp = await self._http.request(
            method,
            self._base + path,
            params=params,
            json=json,
            headers=headers,
            follow_redirects=follow_redirects,
        )
        if resp.status_code >= 400:
            raise GitHubError(resp.status_code, _error_message(resp))
        return resp

    async def _json(self, path: str, **params: Any) -> Any:
        return (await self._request("GET", path, params=params or None)).json()

    async def _send(self, method: str, path: str, body: Any = None) -> Any:
        resp = await self._request(method, path, json=body)
        return resp.json() if resp.content else None

    async def _pages(self, path: str, max_pages: int = 10, **params: Any) -> list[JSON]:
        items: list[JSON] = []
        for page in range(1, max_pages + 1):
            batch = await self._json(path, per_page=100, page=page, **params)
            items += batch
            if len(batch) < 100:
                break
        return items

    # Account and repos

    async def user(self) -> JSON:
        return cast(JSON, await self._json("/user"))

    async def repos(self, page: int = 1, per_page: int = 100) -> list[JSON]:
        return cast(
            list[JSON],
            await self._json(
                "/user/repos",
                affiliation="owner,collaborator,organization_member",
                sort="pushed",
                per_page=per_page,
                page=page,
            ),
        )

    async def repo(self, owner: str, name: str) -> JSON:
        return cast(JSON, await self._json(f"/repos/{owner}/{name}"))

    # Branches, commits and files

    async def branches(self, owner: str, name: str) -> list[JSON]:
        return await self._pages(f"/repos/{owner}/{name}/branches")

    async def commit(self, owner: str, name: str, ref: str) -> JSON:
        return cast(JSON, await self._json(f"/repos/{owner}/{name}/commits/{quote(ref, safe='')}"))

    async def merge_base(self, owner: str, name: str, base: str, head: str) -> str:
        data = await self._json(f"/repos/{owner}/{name}/compare/{base}...{head}", per_page=1)
        return str(data["merge_base_commit"]["sha"])

    async def tree(self, owner: str, name: str, sha: str) -> JSON:
        return cast(JSON, await self._json(f"/repos/{owner}/{name}/git/trees/{sha}", recursive="1"))

    async def file(self, owner: str, name: str, path: str, ref: str) -> bytes:
        resp = await self._request(
            "GET",
            f"/repos/{owner}/{name}/contents/{quote(path)}",
            params={"ref": ref},
            accept="application/vnd.github.raw+json",
        )
        return resp.content

    async def create_ref(self, owner: str, name: str, branch: str, sha: str) -> None:
        await self._send(
            "POST", f"/repos/{owner}/{name}/git/refs", {"ref": f"refs/heads/{branch}", "sha": sha}
        )

    async def update_ref(self, owner: str, name: str, branch: str, sha: str) -> None:
        await self._send(
            "PATCH",
            f"/repos/{owner}/{name}/git/refs/heads/{quote(branch)}",
            {"sha": sha, "force": False},
        )

    async def delete_ref(self, owner: str, name: str, branch: str) -> None:
        await self._send("DELETE", f"/repos/{owner}/{name}/git/refs/heads/{quote(branch)}")

    async def create_tree(self, owner: str, name: str, base_tree: str, entries: list[JSON]) -> JSON:
        return cast(
            JSON,
            await self._send(
                "POST",
                f"/repos/{owner}/{name}/git/trees",
                {"base_tree": base_tree, "tree": entries},
            ),
        )

    async def create_commit(
        self, owner: str, name: str, message: str, tree: str, parents: list[str]
    ) -> JSON:
        return cast(
            JSON,
            await self._send(
                "POST",
                f"/repos/{owner}/{name}/git/commits",
                {"message": message, "tree": tree, "parents": parents},
            ),
        )

    # Pull requests

    async def pulls(self, owner: str, name: str, state: str, head: str | None) -> list[JSON]:
        params: dict[str, Any] = {"state": state, "sort": "updated", "direction": "desc"}
        if head:
            params["head"] = head
        return cast(
            list[JSON], await self._json(f"/repos/{owner}/{name}/pulls", per_page=50, **params)
        )

    async def pull(self, owner: str, name: str, number: int) -> JSON:
        return cast(JSON, await self._json(f"/repos/{owner}/{name}/pulls/{number}"))

    async def pull_files(self, owner: str, name: str, number: int) -> list[JSON]:
        # GitHub caps this endpoint at 3000 files.
        return await self._pages(f"/repos/{owner}/{name}/pulls/{number}/files", max_pages=30)

    async def issue_comments(self, owner: str, name: str, number: int) -> list[JSON]:
        return await self._pages(f"/repos/{owner}/{name}/issues/{number}/comments")

    async def review_comments(self, owner: str, name: str, number: int) -> list[JSON]:
        return await self._pages(f"/repos/{owner}/{name}/pulls/{number}/comments")

    async def reviews(self, owner: str, name: str, number: int) -> list[JSON]:
        return await self._pages(f"/repos/{owner}/{name}/pulls/{number}/reviews")

    async def create_pull(self, owner: str, name: str, body: JSON) -> JSON:
        return cast(JSON, await self._send("POST", f"/repos/{owner}/{name}/pulls", body))

    async def create_issue_comment(self, owner: str, name: str, number: int, body: str) -> JSON:
        return cast(
            JSON,
            await self._send(
                "POST", f"/repos/{owner}/{name}/issues/{number}/comments", {"body": body}
            ),
        )

    async def merge_pull(self, owner: str, name: str, number: int, method: str) -> JSON:
        return cast(
            JSON,
            await self._send(
                "PUT", f"/repos/{owner}/{name}/pulls/{number}/merge", {"merge_method": method}
            ),
        )

    # CI

    async def check_runs(self, owner: str, name: str, sha: str) -> list[JSON]:
        data = await self._json(f"/repos/{owner}/{name}/commits/{sha}/check-runs", per_page=100)
        return cast(list[JSON], data["check_runs"])

    async def combined_status(self, owner: str, name: str, sha: str) -> list[JSON]:
        data = await self._json(f"/repos/{owner}/{name}/commits/{sha}/status", per_page=100)
        return cast(list[JSON], data["statuses"])

    async def job_logs(self, owner: str, name: str, job_id: int) -> str:
        # GitHub answers with a redirect to blob storage. httpx drops the Authorization
        # header on the cross-origin hop, so the token never leaves GitHub.
        resp = await self._request(
            "GET", f"/repos/{owner}/{name}/actions/jobs/{job_id}/logs", follow_redirects=True
        )
        data = resp.content[-MAX_LOG_BYTES:]
        return data.decode("utf-8", errors="replace")


def decode_text(data: bytes) -> str | None:
    """Returns the file as text, or None when it looks binary."""
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None
