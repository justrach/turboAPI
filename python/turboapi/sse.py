"""
Server-Sent Events (SSE) support for TurboAPI.
Compatible with FastAPI's EventSourceResponse.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from .responses import StreamingResponse


@dataclass
class ServerSentEvent:
    """Represents a single SSE event."""

    data: Any = ""
    event: str | None = None
    id: str | int | None = None
    retry: int | None = None
    comment: str | None = None

    def encode(self) -> str:
        """Encode this event to SSE wire format."""
        return format_sse_event(self)


def format_sse_event(evt: ServerSentEvent) -> str:
    """Format a ServerSentEvent into SSE wire format."""
    lines = []

    if evt.comment is not None:
        for line in str(evt.comment).splitlines():
            lines.append(f": {line}")

    if evt.event is not None:
        lines.append(f"event: {evt.event}")

    if evt.id is not None:
        lines.append(f"id: {evt.id}")

    if evt.retry is not None:
        lines.append(f"retry: {evt.retry}")

    # Serialize data
    if evt.data is not None:
        if isinstance(evt.data, str):
            data_str = evt.data
        else:
            data_str = json.dumps(evt.data)

        for line in data_str.splitlines():
            lines.append(f"data: {line}")

    lines.append("")  # trailing newline
    lines.append("")  # double newline terminates event
    return "\n".join(lines)


class EventSourceResponse(StreamingResponse):
    """SSE response that streams events to the client.

    Usage:
        @app.get("/events")
        async def stream_events():
            async def generate():
                for i in range(10):
                    yield ServerSentEvent(data={"count": i}, event="update")
                    await asyncio.sleep(1)
            return EventSourceResponse(generate())
    """

    def __init__(
        self,
        content: AsyncIterator,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        ping_interval: float = 15,
    ):
        self.ping_interval = ping_interval
        self._source = content

        sse_headers = {
            "content-type": "text/event-stream",
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "x-accel-buffering": "no",
        }
        if headers:
            sse_headers.update(headers)

        super().__init__(
            content=self._wrap_with_ping(content),
            status_code=status_code,
            media_type="text/event-stream",
            headers=sse_headers,
        )

    async def _wrap_with_ping(self, source: AsyncIterator):
        """Wrap the source iterator with keep-alive pings."""
        ping_event = ServerSentEvent(comment="ping")
        ping_encoded = ping_event.encode()

        async def _ping_task(queue: asyncio.Queue):
            try:
                while True:
                    await asyncio.sleep(self.ping_interval)
                    await queue.put(ping_encoded)
            except asyncio.CancelledError:
                pass

        queue: asyncio.Queue[str | None] = asyncio.Queue()
        ping = asyncio.create_task(_ping_task(queue))

        try:
            async for item in source:
                # Auto-wrap non-SSE items
                if isinstance(item, ServerSentEvent):
                    yield item.encode()
                elif isinstance(item, dict):
                    yield format_sse_event(ServerSentEvent(data=item))
                elif isinstance(item, str):
                    yield format_sse_event(ServerSentEvent(data=item))
                else:
                    yield format_sse_event(ServerSentEvent(data=item))

                # Drain any pending pings
                while not queue.empty():
                    yield queue.get_nowait()
        finally:
            ping.cancel()
            try:
                await ping
            except asyncio.CancelledError:
                pass
