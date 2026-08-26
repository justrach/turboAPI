"""WebSocket support for TurboAPI.

FastAPI-compatible WebSocket API. Two modes:

1. **In-memory mode** (default, used by parity tests). Push/pop on
   asyncio.Queue. No real socket. Set by leaving `_zig_conn` as None.

2. **Connected mode** (real). `_zig_conn` is a short-lived PyCapsule wrapping a
   Zig `*WsConn`. `send_*` / `receive_*` call into the turbonet C extension's
   FFI primitives, using direct blocking reads for the sequential hot path and
   descriptor readiness once a handler yields or starts concurrent I/O.

Both modes share the same public API so handlers don't need to know which
they're in.
"""

import asyncio
import inspect
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import get_ident
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qsl


def _bounded_int_env(
    name: str, default: int, hard_min: int, hard_max: int
) -> int:
    """Read an unsigned 64-bit ASCII decimal and clamp it to fixed bounds.

    Signs, whitespace, non-ASCII digits, empty values, and uint64 overflow are
    invalid and use ``default``. This intentionally matches Zig's native
    server normalization byte-for-byte.
    """
    raw = os.environ.get(name)
    if raw is None or not raw or any(byte < "0" or byte > "9" for byte in raw):
        return default
    # Avoid asking Python to construct an arbitrarily large integer from an
    # untrusted environment string, and match Zig's u64 overflow boundary.
    significant = raw.lstrip("0") or "0"
    if len(significant) > 20 or (
        len(significant) == 20 and significant > "18446744073709551615"
    ):
        return default
    value = int(significant, 10)
    return min(max(hard_min, value), hard_max)


class WebSocketDisconnect(Exception):
    """Raised when a WebSocket connection is closed."""

    def __init__(self, code: int = 1000, reason: str | None = None):
        self.code = code
        self.reason = reason


@dataclass(frozen=True, slots=True)
class WebSocketUpgradeRequest:
    """Read-only metadata exposed to a native pre-upgrade route guard.

    Header names are normalized to lowercase and repeated query parameters use
    the last value, matching :class:`WebSocket`'s post-upgrade convenience
    mappings. ``query_string`` preserves the original bytes for policies that
    need to distinguish repeated or blank values.
    """

    path: str
    headers: Mapping[str, str]
    query_params: Mapping[str, str]
    query_string: bytes


_SAFE_WEBSOCKET_REJECTION_STATUSES = frozenset({400, 401, 403, 404, 429, 500, 503})


@dataclass(frozen=True, slots=True)
class WebSocketUpgradeRejection:
    """Status-only pre-upgrade rejection.

    TurboAPI deliberately does not accept an application-supplied response
    body here: an empty bounded response cannot accidentally reflect bearer
    credentials or other request metadata.
    """

    status_code: int = 403

    def __post_init__(self) -> None:
        if (
            isinstance(self.status_code, bool)
            or not isinstance(self.status_code, int)
            or self.status_code not in _SAFE_WEBSOCKET_REJECTION_STATUSES
        ):
            allowed = ", ".join(str(status) for status in sorted(_SAFE_WEBSOCKET_REJECTION_STATUSES))
            raise ValueError(f"WebSocket guard rejection status must be one of: {allowed}")


WebSocketUpgradeGuard = Callable[
    [WebSocketUpgradeRequest], bool | WebSocketUpgradeRejection
]


def _upgrade_request_from_raw(
    path: str,
    query_string: bytes | str,
    headers: list[tuple[bytes | str, bytes | str]],
) -> WebSocketUpgradeRequest:
    """Build the public guard request from the Zig core's borrowed metadata."""
    if isinstance(query_string, bytes):
        raw_query = query_string
        decoded_query = query_string.decode("ascii", errors="replace")
    else:
        decoded_query = str(query_string)
        raw_query = decoded_query.encode("ascii", errors="replace")

    normalized_headers: dict[str, str] = {}
    for name, value in headers:
        if isinstance(name, bytes):
            decoded_name = name.decode("latin-1")
        else:
            decoded_name = str(name)
        if isinstance(value, bytes):
            decoded_value = value.decode("latin-1")
        else:
            decoded_value = str(value)
        normalized_headers[decoded_name.lower()] = decoded_value

    query_params = (
        dict(parse_qsl(decoded_query, keep_blank_values=True)) if decoded_query else {}
    )
    return WebSocketUpgradeRequest(
        path=str(path),
        headers=MappingProxyType(normalized_headers),
        query_params=MappingProxyType(query_params),
        query_string=raw_query,
    )


def _evaluate_websocket_upgrade_guard(
    guard: WebSocketUpgradeGuard,
    path: str,
    query_string: bytes | str,
    headers: list[tuple[bytes | str, bytes | str]],
) -> int:
    """Return 0 to allow or a bounded HTTP status to reject.

    Only the literal ``True`` allows an upgrade. Exceptions, invalid return
    values, and asynchronous guards fail closed with 403 and are intentionally
    not logged, because exception text can contain request credentials.
    """
    try:
        request = _upgrade_request_from_raw(path, query_string, headers)
        result = guard(request)
        if result is True:
            return 0
        if isinstance(result, WebSocketUpgradeRejection):
            return result.status_code
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            return 403
        return 403
    except BaseException:
        return 403


def _validate_close(code: int, reason: str | None) -> None:
    valid = not isinstance(code, bool) and isinstance(code, int) and (code in {
        1000,
        1001,
        1002,
        1003,
        1007,
        1008,
        1009,
        1010,
        1011,
        1012,
        1013,
        1014,
    } or 3000 <= code <= 4999)
    if not valid:
        raise ValueError("invalid WebSocket close code")
    if reason is not None and not isinstance(reason, str):
        raise TypeError("WebSocket close reason must be a string")
    try:
        encoded_reason = (reason or "").encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("WebSocket close reason must be valid UTF-8") from exc
    if len(encoded_reason) > 123:
        raise ValueError("WebSocket close reason exceeds 123 UTF-8 bytes")


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
        # Connected mode keeps the sequential receive/send hot path direct,
        # then switches the native socket once to descriptor readiness when a
        # handler yields or starts concurrent I/O. This avoids a thread-pool
        # round trip on every frame while keeping slow peers bounded.
        self._write_timeout_s = (
            _bounded_int_env("TURBO_WS_WRITE_TIMEOUT_MS", 5000, 100, 30000)
            / 1000
        )
        self._queue_bytes = _bounded_int_env(
            "TURBO_WS_QUEUE_BYTES", 16 * 1024 * 1024, 1, 16 * 1024 * 1024
        )
        queue_messages = _bounded_int_env(
            "TURBO_WS_QUEUE_MESSAGES", 64, 1, 1024
        )
        self._zig_writer_task: asyncio.Task | None = None
        self._zig_write_deadline: float | None = None
        self._zig_control_task: asyncio.Task | None = None
        self._zig_inbound: asyncio.Queue = asyncio.Queue(maxsize=queue_messages)
        self._zig_inbound_bytes = 0
        self._zig_disconnect: WebSocketDisconnect | None = None
        self._closing_requested = False
        self._receive_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._handler_task: asyncio.Task | None = None
        self._zig_owner_thread: int | None = None
        self._native_config_synced = False
        self._nonblocking_transport = False
        self._control_scheduled = False
        self.client_state = "connecting"
        self.path_params: dict[str, Any] = dict(self.scope.get("path_params") or {})
        self.query_params: dict[str, str] = self._scope_query_params()
        self.headers: dict[str, str] = self._scope_headers()

    def _scope_query_params(self) -> dict[str, str]:
        """Decode the ASGI-style raw query string into a convenience mapping.

        ``dict`` deliberately preserves the class's existing public type: when
        a key is repeated, the last value wins. The unmodified bytes remain in
        ``scope["query_string"]`` for callers that need every value.
        """
        raw_query = self.scope.get("query_string", b"")
        if isinstance(raw_query, bytes):
            raw_query = raw_query.decode("ascii", errors="replace")
        elif not isinstance(raw_query, str):
            raw_query = str(raw_query)
        return dict(parse_qsl(raw_query, keep_blank_values=True))

    def _scope_headers(self) -> dict[str, str]:
        """Normalize ASGI-style header pairs for case-insensitive lookup."""
        raw_headers = self.scope.get("headers") or []
        items = raw_headers.items() if isinstance(raw_headers, dict) else raw_headers
        headers: dict[str, str] = {}
        for name, value in items:
            if isinstance(name, bytes):
                name = name.decode("latin-1")
            else:
                name = str(name)
            if isinstance(value, bytes):
                value = value.decode("latin-1")
            else:
                value = str(value)
            headers[name.lower()] = value
        return headers

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
        if self._is_zig_backed:
            self._bind_native_loop()
            self._require_readiness_loop()
            self._handler_task = asyncio.current_task()
            if not self._control_scheduled:
                self._control_scheduled = True
                asyncio.get_running_loop().call_soon(self._start_control_if_idle)

    def _bind_native_loop(self) -> None:
        owner_thread = get_ident()
        if self._zig_owner_thread is None:
            self._zig_owner_thread = owner_thread
        elif self._zig_owner_thread != owner_thread:
            raise RuntimeError(
                "native WebSockets must be used from their handler event loop"
            )
        if self._is_zig_backed and not self._native_config_synced:
            t = _turbonet()
            if t is None:
                raise RuntimeError("WebSocket transport is unavailable")
            metrics = dict(t._ws_metrics(self._zig_conn))
            # The native pool is process-global and freezes these settings on
            # its first successful pool initialization. Synchronize before the
            # handler can enqueue anything, so later environment changes cannot
            # split the Python and Zig queue/deadline contracts.
            self._zig_inbound = asyncio.Queue(maxsize=int(metrics["message_limit"]))
            self._queue_bytes = int(metrics["byte_limit"])
            self._write_timeout_s = int(metrics["write_timeout_ms"]) / 1000
            self._native_config_synced = True

    def _require_readiness_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if not hasattr(loop, "add_reader") or not hasattr(loop, "add_writer"):
            raise RuntimeError(
                "native WebSockets require an event loop with fd readiness support"
            )

    def _fileno(self) -> int:
        t = _turbonet()
        if t is None or self._zig_conn is None:
            raise RuntimeError("WebSocket transport is unavailable")
        return int(t._ws_fileno(self._zig_conn))

    def _activate_nonblocking(self) -> None:
        if self._nonblocking_transport:
            return
        t = _turbonet()
        if t is None or self._zig_conn is None:
            raise RuntimeError("WebSocket transport is unavailable")
        t._ws_set_nonblocking(self._zig_conn)
        self._nonblocking_transport = True

    def _start_control_if_idle(self) -> None:
        self._control_scheduled = False
        if self._closed or self._zig_conn is None or self._zig_control_task is not None:
            return
        self._activate_nonblocking()
        self._zig_control_task = asyncio.create_task(self._zig_control_loop())

    @staticmethod
    def _message_size(data: Any) -> int:
        if isinstance(data, str):
            return len(data.encode("utf-8"))
        if isinstance(data, (bytes, bytearray, memoryview)):
            return len(data)
        return 0

    async def _wait_fd(self, *, writable: bool) -> None:
        self._activate_nonblocking()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        fd = self._fileno()

        def ready() -> None:
            if not future.done():
                future.set_result(None)

        add = loop.add_writer if writable else loop.add_reader
        remove = loop.remove_writer if writable else loop.remove_reader
        try:
            add(fd, ready)
        except (AttributeError, NotImplementedError) as exc:
            raise RuntimeError(
                "native WebSockets require an event loop with fd readiness support"
            ) from exc
        try:
            await future
        finally:
            remove(fd)

    async def _cancel_control_task(self) -> None:
        task = self._zig_control_task
        if task is None or task is asyncio.current_task():
            return
        self._zig_control_task = None
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def _queue_disconnect(self, code: int, reason: str | None) -> None:
        self._zig_disconnect = WebSocketDisconnect(code, reason)
        while self._zig_inbound.full():
            try:
                _kind, data = self._zig_inbound.get_nowait()
                self._zig_inbound_bytes = max(
                    0, self._zig_inbound_bytes - self._message_size(data)
                )
                self._zig_inbound.task_done()
            except asyncio.QueueEmpty:
                break
        self._zig_inbound.put_nowait(("disconnect", (code, reason)))

    async def _zig_control_loop(self) -> None:
        """Service control frames while a handler isn't actively receiving."""
        t = _turbonet()
        if t is None or self._zig_conn is None:
            return
        try:
            while not self._closed:
                result = t._ws_recv(self._zig_conn)
                if result is None:
                    await self._wait_fd(writable=False)
                    continue
                type_str, data, pending = result
                if pending:
                    self._ensure_writer_task()
                if type_str == "control":
                    continue
                if type_str == "disconnect":
                    code, reason = data
                    self._closed = True
                    self._closing_requested = True
                    self.client_state = "disconnected"
                    self._queue_disconnect(code, reason or None)
                    return
                size = self._message_size(data)
                if (
                    self._zig_inbound.full()
                    or size > self._queue_bytes
                    or self._zig_inbound_bytes > self._queue_bytes - size
                ):
                    await self._abort_transport(1013, "inbound backpressure")
                    self._queue_disconnect(1013, "inbound backpressure")
                    return
                self._zig_inbound_bytes += size
                self._zig_inbound.put_nowait((type_str, data))
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self._closed:
                await self._abort_transport(1011, "reader failure")
                self._queue_disconnect(1011, "reader failure")

    def _ensure_writer_task(self, *, deadline: float | None = None) -> None:
        if self._zig_conn is None:
            return
        self._activate_nonblocking()
        if deadline is None:
            deadline = asyncio.get_running_loop().time() + self._write_timeout_s
        if self._zig_write_deadline is None:
            self._zig_write_deadline = deadline
        else:
            # The oldest queued frame owns the deadline. New writes cannot
            # extend how long a stalled peer retains this connection slot.
            self._zig_write_deadline = min(self._zig_write_deadline, deadline)
        if self._zig_writer_task is None or self._zig_writer_task.done():
            self._zig_writer_task = asyncio.create_task(self._zig_writer_loop())

    async def _join_writer(self) -> None:
        writer = self._zig_writer_task
        if writer is None or writer is asyncio.current_task():
            return
        try:
            await asyncio.wait_for(asyncio.shield(writer), self._write_timeout_s)
        except Exception:
            await self._abort_transport(1013, "write timeout")
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)

    async def _abort_transport(self, code: int, reason: str) -> None:
        self._closed = True
        self._closing_requested = True
        self.client_state = "disconnected"
        self._zig_disconnect = WebSocketDisconnect(code=code, reason=reason)
        t = _turbonet()
        if t is not None and self._zig_conn is not None:
            try:
                t._ws_abort(self._zig_conn, int(code), reason)
            except Exception:
                pass

    async def _shutdown_transport(self) -> None:
        """Close and fully join connected-mode I/O before the native scope ends."""
        if self._is_zig_backed:
            self._bind_native_loop()
        await self._cancel_control_task()
        if not self._is_zig_backed:
            if not self._closed:
                await self.close()
            return
        if not self._closed and not self._closing_requested:
            await self.close()
            return
        if self._zig_writer_task is not None:
            await self._join_writer()
        t = _turbonet()
        if t is not None and self._zig_conn is not None:
            try:
                t._ws_shutdown(self._zig_conn)
            except Exception:
                pass

    async def _zig_writer_loop(self) -> None:
        t = _turbonet()
        if t is None or self._zig_conn is None:
            await self._abort_transport(1011, "turbonet unavailable")
            return
        try:
            while self._zig_conn is not None:
                if t._ws_flush(self._zig_conn):
                    return
                deadline = self._zig_write_deadline
                if deadline is None:
                    deadline = (
                        asyncio.get_running_loop().time() + self._write_timeout_s
                    )
                    self._zig_write_deadline = deadline
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError
                await asyncio.wait_for(
                    self._wait_fd(writable=True), timeout=remaining
                )
        except Exception:
            await self._abort_transport(1013, "write timeout")
        finally:
            self._zig_write_deadline = None

    async def _enqueue_zig_send(self, kind: str, data: Any) -> None:
        self._bind_native_loop()
        if self._closed or self._closing_requested:
            raise RuntimeError("WebSocket is not connected")
        t = _turbonet()
        if t is None or self._zig_conn is None:
            raise RuntimeError("turbonet not available")
        deadline = asyncio.get_running_loop().time() + self._write_timeout_s
        try:
            pending = (
                t._ws_send_text(self._zig_conn, data)
                if kind == "text"
                else t._ws_send_bytes(self._zig_conn, data)
            )
        except BufferError:
            await self._abort_transport(1013, "outbound backpressure")
            raise RuntimeError("WebSocket outbound queue exceeded its bounded capacity")
        if pending:
            self._ensure_writer_task(deadline=deadline)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        """Close the WebSocket connection."""
        _validate_close(code, reason)
        if self._is_zig_backed:
            self._bind_native_loop()
            async with self._close_lock:
                if self._closed:
                    return
                # Give the readiness task one final turn to service already
                # received pings before the close frame is ordered.
                await asyncio.sleep(0)
                await self._cancel_control_task()
                self._closing_requested = True
                t = _turbonet()
                if t is not None and self._zig_conn is not None:
                    try:
                        if t._ws_close(self._zig_conn, int(code), reason or ""):
                            self._ensure_writer_task()
                            await self._join_writer()
                            if self._closed:
                                return
                    except Exception:
                        await self._abort_transport(1013, "close failed")
                        return
                self._closed = True
                self.client_state = "disconnected"
                self._zig_disconnect = WebSocketDisconnect(code=code, reason=reason)
                if t is not None and self._zig_conn is not None:
                    try:
                        t._ws_shutdown(self._zig_conn)
                    except Exception:
                        pass
                return
        if self._closed:
            return
        self._closed = True
        self.client_state = "disconnected"

    @property
    def transport_metrics(self) -> dict[str, int]:
        """Transport occupancy, capacity, and deadline; never message payloads."""
        if not self._is_zig_backed:
            return {
                "inbound_messages": 0,
                "inbound_bytes": 0,
                "outbound_messages": 0,
                "outbound_bytes": 0,
                "message_limit": 0,
                "byte_limit": 0,
                "write_timeout_ms": 0,
                "worker_count": 0,
                "max_active": 0,
            }
        self._bind_native_loop()
        t = _turbonet()
        if t is None:
            raise RuntimeError("turbonet not available")
        metrics = dict(t._ws_metrics(self._zig_conn))
        metrics["inbound_messages"] = self._zig_inbound.qsize()
        metrics["inbound_bytes"] += self._zig_inbound_bytes
        return metrics

    async def send_text(self, data: str) -> None:
        """Send a text message."""
        if not self._accepted or self._closed:
            raise RuntimeError("WebSocket is not connected")
        if self._is_zig_backed:
            await self._enqueue_zig_send("text", data)
        else:
            await self._send_queue.put({"type": "text", "data": data})

    async def send_bytes(self, data: bytes) -> None:
        """Send a binary message."""
        if not self._accepted or self._closed:
            raise RuntimeError("WebSocket is not connected")
        if self._is_zig_backed:
            await self._enqueue_zig_send("bytes", bytes(data))
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
        if self._is_zig_backed:
            type_str, data = await self._receive_zig_message()
            if type_str == "bytes":
                # Bytes arrived where text was expected — decode.
                return data.decode("utf-8", errors="replace")
            return data
        if self._closed:
            raise WebSocketDisconnect()
        message = await self._receive_queue.get()
        if message.get("type") == "disconnect":
            raise WebSocketDisconnect(code=message.get("code", 1000))
        return message.get("data", "")

    async def receive_bytes(self) -> bytes:
        """Receive a binary message."""
        if self._is_zig_backed:
            type_str, data = await self._receive_zig_message()
            if type_str == "text":
                return data.encode("utf-8")
            return data
        if self._closed:
            raise WebSocketDisconnect()
        message = await self._receive_queue.get()
        if message.get("type") == "disconnect":
            raise WebSocketDisconnect(code=message.get("code", 1000))
        data = message.get("data", b"")
        if isinstance(data, str):
            return data.encode("utf-8")
        return data

    async def _receive_zig_message(self) -> tuple[str, Any]:
        self._bind_native_loop()
        t = _turbonet()
        if t is None or self._zig_conn is None:
            raise RuntimeError("turbonet not available")
        async with self._receive_lock:
            await self._cancel_control_task()
            if (
                asyncio.current_task() is self._handler_task
                and not self._nonblocking_transport
                and self._zig_inbound.empty()
            ):
                type_str, data, pending = t._ws_recv_blocking(self._zig_conn)
                if pending:
                    self._ensure_writer_task()
                if type_str == "disconnect":
                    code, reason = data
                    self._closed = True
                    self._closing_requested = True
                    self.client_state = "disconnected"
                    self._zig_disconnect = WebSocketDisconnect(code, reason or None)
                    raise self._zig_disconnect
                return type_str, data
            while True:
                if not self._zig_inbound.empty():
                    type_str, data = self._zig_inbound.get_nowait()
                    self._zig_inbound.task_done()
                    self._zig_inbound_bytes = max(
                        0, self._zig_inbound_bytes - self._message_size(data)
                    )
                    if type_str == "disconnect":
                        raise self._zig_disconnect or WebSocketDisconnect()
                    return type_str, data
                if self._closed:
                    raise self._zig_disconnect or WebSocketDisconnect()
                result = t._ws_recv(self._zig_conn)
                if result is None:
                    await self._wait_fd(writable=False)
                    continue
                type_str, data, pending = result
                if pending:
                    self._ensure_writer_task()
                if type_str == "control":
                    continue
                if type_str == "disconnect":
                    code, reason = data
                    self._closed = True
                    self._closing_requested = True
                    self.client_state = "disconnected"
                    self._zig_disconnect = WebSocketDisconnect(code, reason or None)
                    raise self._zig_disconnect
                return type_str, data

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

    def __init__(
        self,
        path: str,
        handler: Callable,
        guard: WebSocketUpgradeGuard | None = None,
    ):
        self.path = path
        self.handler = handler
        self.guard = guard
