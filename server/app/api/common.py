from collections.abc import Awaitable

from fastapi import HTTPException

from app.github.client import GitHubError

# GitHub statuses worth passing to the browser as-is; anything else is a bad gateway.
PASSTHROUGH = {401, 403, 404, 405, 409, 422}


async def gh_call[T](call: Awaitable[T]) -> T:
    try:
        return await call
    except GitHubError as e:
        raise HTTPException(e.status if e.status in PASSTHROUGH else 502, e.message) from e
