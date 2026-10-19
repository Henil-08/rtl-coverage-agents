"""Live event channel. The service installs a sink for the duration of a run; agents and tools
publish what they are doing into it (tokens as the LLM writes, artifacts, simulator output)."""

from __future__ import annotations

import contextvars
import time
from typing import Callable

_sink: contextvars.ContextVar[Callable[[dict], None] | None] = contextvars.ContextVar("event_sink", default=None)


def install(fn: Callable[[dict], None] | None):
    return _sink.set(fn)


def remove(token) -> None:
    _sink.reset(token)


def active() -> bool:
    return _sink.get() is not None


def emit(kind: str, **data) -> None:
    fn = _sink.get()
    if fn is not None:
        fn({"type": kind, "t": round(time.time(), 3), **data})


class TokenBuffer:
    """Batches streamed LLM tokens so the UI gets smooth updates without one message per token."""

    def __init__(self, agent: str, every: float = 0.05):
        self.agent, self.every, self.buf, self.last = agent, every, [], time.monotonic()

    def add(self, text: str) -> None:
        self.buf.append(text)
        if time.monotonic() - self.last >= self.every:
            self.flush()

    def flush(self) -> None:
        if self.buf:
            emit("token", agent=self.agent, text="".join(self.buf))
            self.buf = []
        self.last = time.monotonic()
