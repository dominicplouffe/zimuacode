"""Task events: saved to the database, then fanned out to live subscribers (SSE streams)."""

import asyncio
from collections import defaultdict
from collections.abc import AsyncGenerator
from typing import Any

from sqlmodel import Session, col, func, select

from app.db import get_engine
from app.models import TaskEvent

# Normalized event types the UI understands:
#   user_message {text, queued?}      assistant_text {text}      thinking {text}
#   tool_call {id, name, input}       tool_result {id, output, is_error}
#   command {id, command, output, exit_code}   file_change {changes: [{path, kind}]}
#   todo {items: [{text, completed}]}  status {status, detail?}  usage {cost_usd?, ...}
#   error {message}                    log {text}  (non-JSON output from the CLI)


def event_dict(e: TaskEvent) -> dict[str, Any]:
    return {"seq": e.seq, "type": e.type, "data": e.data, "created_at": e.created_at.isoformat()}


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._seq: dict[str, int] = {}

    def _next_seq(self, session: Session, task_id: str) -> int:
        if task_id not in self._seq:
            last = session.exec(
                select(func.max(TaskEvent.seq)).where(TaskEvent.task_id == task_id)
            ).one()
            self._seq[task_id] = last or 0
        self._seq[task_id] += 1
        return self._seq[task_id]

    def publish(self, task_id: str, type: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(get_engine()) as session:
            event = TaskEvent(
                task_id=task_id, seq=self._next_seq(session, task_id), type=type, data=data
            )
            session.add(event)
            session.commit()
            session.refresh(event)
            payload = event_dict(event)
        for queue in self._subscribers.get(task_id, ()):
            queue.put_nowait(payload)
        return payload

    def history(self, task_id: str, after: int = 0) -> list[dict[str, Any]]:
        with Session(get_engine()) as session:
            events = session.exec(
                select(TaskEvent)
                .where(TaskEvent.task_id == task_id, col(TaskEvent.seq) > after)
                .order_by(col(TaskEvent.seq))
            ).all()
            return [event_dict(e) for e in events]

    async def stream(self, task_id: str, after: int = 0) -> AsyncGenerator[dict[str, Any], None]:
        """Past events after `after`, then live ones, without gaps or duplicates."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        # Subscribe before reading history, so nothing published in between is missed.
        self._subscribers[task_id].add(queue)
        try:
            last = after
            for event in self.history(task_id, after):
                last = event["seq"]
                yield event
            while True:
                event = await queue.get()
                if event["seq"] > last:
                    last = event["seq"]
                    yield event
        finally:
            self._subscribers[task_id].discard(queue)
            if not self._subscribers[task_id]:
                del self._subscribers[task_id]
