"""Tiny in-process event bus (event-driven core).

Publishers (sync layer, decision engine, audit trail) emit typed domain events; subscribers (the live UI stream,
the activity feed) consume them. Publishing never blocks or fails: a slow subscriber loses its oldest events, and
because the UI treats an event as a hint and re-reads state over REST, nothing is ever lost that matters."""
import asyncio
import time
from collections import deque
from typing import Any


class EventBus:
    def __init__(self, keep: int = 300):
        self.seq = 0
        self.recent: deque[dict] = deque(maxlen=keep)
        self._subs: set[asyncio.Queue] = set()

    def publish(self, type_: str, **data: Any) -> dict:
        self.seq += 1
        evt = {"id": self.seq, "type": type_, "ts": round(time.time(), 3), "data": data}
        self.recent.append(evt)
        for q in list(self._subs):
            if q.full():
                try:
                    q.get_nowait()  # drop the oldest; the consumer will resync from REST
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(evt)
        return evt

    def subscribe(self, maxsize: int = 200) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def since(self, last_id: int) -> list[dict]:
        return [e for e in self.recent if e["id"] > last_id]

    @property
    def subscribers(self) -> int:
        return len(self._subs)
