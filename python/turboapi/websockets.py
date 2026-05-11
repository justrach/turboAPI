"""WebSocket support for TurboAPI.

FastAPI-compatible WebSocket API. Two modes:

1. **In-memory mode** (default, used by parity tests). Push/pop on
   asyncio.Queue. No real socket. Set by leaving `_zig_conn` as None.

2. **Connected mode** (real). `_zig_conn` is a PyCapsule wrapping a Zig
   `*WsConn`. `send_*` / `receive_*` call into the turbonet C extension's
   FFI primitives (`_ws_send_text`, `_ws_send_bytes`, `_ws_recv`, `_ws_close`)
   which read/write actual WebSocket frames on the underlying TCP socket.

Both modes share the same public API so handlers don't need to know which
they're in.
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any


class WebSocketDisconnect(Exception):
    """Raised when a WebSocket connection is closed."""

    def __init__(self, code: int = 1000, reason: str | None = None):
        self.code = code
        self.reason = reason


def _turbonet():
    """Lazy import of the compiled module — keeps in-memory mode working
    even if turbonet hasn't been built (e.g. during unit tests)."""
    try:
        from turboapi import turbonet  # type: ignore
    except ImportError:
        return None
    return turbonet


class WebSocket:
    """WebSocket connection object.

    Provides methods for sending and receiving messages over a WebSocket
    connection.
    """

    def __init__(self, scope: dict | None = None):
        self.scope = scope or {}
        self._accepted = False
        self._closed = False
        # In-memory mode queues (used when _zig_conn is None).
        self._send_queue: asyncio.Queue = asyncio.Queue()
        self._receive_queue: asyncio.Queue = asyncio.Queue()
        # Connected mode: PyCapsule wrapping the Zig *WsConn pointer.
        # When set, send/receive go through FFI instead of queues.
        self._zig_conn: Any = None
        self.client_state = "connecting"
        self.path_params: dict[str, Any] = {}
        self.query_params: dict[str, str] = {}
        self.headers: dict[str, str] = {}

    @property
    def _is_zig_backed(self) -> bool:
        return self._zig_conn is not None

    async def accept(
        self,
        subprotocol: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Accept the WebSocket connection.

        In connected mode, the handshake was already completed in Zig before
        this handler was invoked — `accept()` is essentially a no-op that
        flips local state. In in-memory mode, just flips state.
        """
        self._accepted = True
        self.client_state = "connected"

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        """Close the WebSocket connection."""
        if self._closed:
            return
        self._closed = True
        self.client_state = "disconnected"
        if self._is_zig_backed:
            t = _turbonet()
            if t is not None:
                try:
                    t._ws_close(self._zig_conn, int(code), (reason or ""))
                except Exception:
                    pass

    async def send_text(self, data: str) -> None:
        """Send a text message."""
        if not self._accepted or self._closed:
            raise RuntimeError("WebSocket is not connected")
        if self._is_zig_backed:
            t = _turbonet()
            if t is None:
                raise RuntimeError("turbonet not available")
            t._ws_send_text(self._zig_conn, data)
        else:
            await self._send_queue.put({"type": "text", "data": data})

    async def send_bytes(self, data: bytes) -> None:
        """Send a binary message."""
        if not self._accepted or self._closed:
            raise RuntimeError("WebSocket is not connected")
        if self._is_zig_backed:
            t = _turbonet()
            if t is None:
                raise RuntimeError("turbonet not available")
            t._ws_send_bytes(self._zig_conn, bytes(data))
        else:
            await self._send_queue.put({"type": "bytes", "data": data})

    async def send_json(self, data: Any, mode: str = "text") -> None:
        """Send a JSON message."""
        text = json.dumps(data, ensure_ascii=False)
        if mode == "text":
            await self.send_text(text)
        else:
            await self.send_bytes(text.encode("utf-8"))

    async def receive_text(self) -> str:
        """Receive a text message."""
        if self._closed:
            raise WebSocketDisconnect()
        if self._is_zig_backed:
            t = _turbonet()
            if t is None:
                raise RuntimeError("turbonet not available")
            try:
                type_str, data = t._ws_recv(self._zig_conn)
            except RuntimeError as exc:
                self._closed = True
                self.client_state = "disconnected"
                raise WebSocketDisconnect() from exc
            if type_str == "bytes":
                # Bytes arrived where text was expected — decode.
                return data.decode("utf-8", errors="replace")
            return data
        message = await self._receive_queue.get()
        if message.get("type") == "disconnect":
            raise WebSocketDisconnect(code=message.get("code", 1000))
        return message.get("data", "")

    async def receive_bytes(self) -> bytes:
        """Receive a binary message."""
        if self._closed:
            raise WebSocketDisconnect()
        if self._is_zig_backed:
            t = _turbonet()
            if t is None:
                raise RuntimeError("turbonet not available")
            try:
                type_str, data = t._ws_recv(self._zig_conn)
            except RuntimeError as exc:
                self._closed = True
                self.client_state = "disconnected"
                raise WebSocketDisconnect() from exc
            if type_str == "text":
                return data.encode("utf-8")
            return data
        message = await self._receive_queue.get()
        if message.get("type") == "disconnect":
            raise WebSocketDisconnect(code=message.get("code", 1000))
        data = message.get("data", b"")
        if isinstance(data, str):
            return data.encode("utf-8")
        return data

    async def receive_json(self, mode: str = "text") -> Any:
        """Receive a JSON message."""
        if mode == "text":
            text = await self.receive_text()
        else:
            data = await self.receive_bytes()
            text = data.decode("utf-8")
        return json.loads(text)

    async def iter_text(self):
        """Iterate over text messages."""
        try:
            while True:
                yield await self.receive_text()
        except WebSocketDisconnect:
            pass

    async def iter_bytes(self):
        """Iterate over binary messages."""
        try:
            while True:
                yield await self.receive_bytes()
        except WebSocketDisconnect:
            pass

    async def iter_json(self):
        """Iterate over JSON messages."""
        try:
            while True:
                yield await self.receive_json()
        except WebSocketDisconnect:
            pass


class WebSocketRoute:
    """Represents a registered WebSocket route."""

    def __init__(self, path: str, handler: Callable):
        self.path = path
        self.handler = handler
