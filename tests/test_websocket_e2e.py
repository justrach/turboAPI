"""End-to-end WebSocket tests against the real Zig HTTP core.

Boots a turboAPI server in a subprocess, connects with the `websockets`
library, and exercises:
  - The in-Zig /ws-echo route (no Python in the loop)
  - Python @app.websocket() handlers (FFI bridge)
  - text / binary / JSON / ping / close
  - simultaneous server push and receive, plus ordered concurrent sends
  - large messages (>16-bit length)
  - fragmented client messages
"""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

import pytest

websockets = pytest.importorskip("websockets")


REPO_ROOT = Path(__file__).resolve().parent.parent
PORT = 0


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture(scope="module")
def ws_server(tmp_path_factory: pytest.TempPathFactory):
    """Spawn a turboAPI server with WS routes and yield the base URL."""
    global PORT
    PORT = _free_port()
    script = textwrap.dedent(
        f"""
        import asyncio
        import threading

        from turboapi import TurboAPI
        from turboapi import turbonet
        from turboapi.websockets import WebSocket, WebSocketDisconnect

        app = TurboAPI(title="ws-e2e", version="0.0.1")
        retained_websockets = []
        retained_capsules = []
        buffered_receive_count = 0
        try:
            app.configure_rate_limiting(enabled=False)
        except Exception:
            pass

        @app.get("/ping")
        def ping():
            return {{"ok": True}}

        @app.websocket("/ws")
        async def echo_handler(ws: WebSocket):
            await ws.accept()
            try:
                while True:
                    msg = await ws.receive_text()
                    await ws.send_text(f"py-echo:{{msg}}")
            except WebSocketDisconnect:
                pass

        @app.websocket("/ws-bytes")
        async def bytes_handler(ws: WebSocket):
            await ws.accept()
            try:
                while True:
                    data = await ws.receive_bytes()
                    await ws.send_bytes(b"B:" + data)
            except WebSocketDisconnect:
                pass

        @app.websocket("/ws-json")
        async def json_handler(ws: WebSocket):
            await ws.accept()
            try:
                while True:
                    data = await ws.receive_json()
                    data["server"] = "turboapi"
                    await ws.send_json(data)
            except WebSocketDisconnect:
                pass

        @app.websocket("/ws-close")
        async def close_handler(ws: WebSocket):
            await ws.accept()
            await ws.send_text("hello")
            await ws.close(code=1001, reason="going away")

        @app.websocket("/ws-metadata")
        async def metadata_handler(ws: WebSocket):
            await ws.accept()
            scope_headers = {{
                name.decode("latin-1"): value.decode("latin-1")
                for name, value in ws.scope["headers"]
            }}
            await ws.send_json({{
                "headers": ws.headers,
                "query_params": ws.query_params,
                "path_params": ws.path_params,
                "scope": {{
                    "type": ws.scope["type"],
                    "scheme": ws.scope["scheme"],
                    "path": ws.scope["path"],
                    "raw_path": ws.scope["raw_path"].decode("utf-8"),
                    "query_string": ws.scope["query_string"].decode("ascii"),
                    "headers": scope_headers,
                    "path_params": ws.scope["path_params"],
                }},
            }})
            await ws.close()

        @app.websocket("/ws-duplex")
        async def duplex_handler(ws: WebSocket):
            await ws.accept()
            pending_receive = asyncio.create_task(ws.receive_text())
            await asyncio.sleep(0)
            await ws.send_text("server-push")
            message = await pending_receive
            await ws.send_text(f"client-ack:{{message}}")
            await ws.close()

        @app.websocket("/ws-concurrent-send")
        async def concurrent_send_handler(ws: WebSocket):
            await ws.accept()
            await asyncio.gather(*(
                ws.send_text(f"frame:{{index}}") for index in range(48)
            ))
            await ws.receive_text()
            await ws.close()

        @app.websocket("/ws-double-close")
        async def double_close_handler(ws: WebSocket):
            await ws.accept()
            await asyncio.gather(ws.close(), ws.close())

        @app.websocket("/ws-cross-loop")
        async def cross_loop_handler(ws: WebSocket):
            await ws.accept()
            outcomes = []

            def use_from_another_loop():
                try:
                    asyncio.run(ws.send_text("unsafe"))
                except RuntimeError as exc:
                    outcomes.append("loop-rejected" if "handler event loop" in str(exc) else "wrong-error")
                else:
                    outcomes.append("cross-loop-send-ran")

            thread = threading.Thread(target=use_from_another_loop)
            thread.start()
            thread.join()
            await ws.send_text(outcomes[0])
            await ws.close()

        @app.websocket("/ws-retain")
        async def retain_handler(ws: WebSocket):
            await ws.accept()
            retained_websockets.append(ws)
            retained_capsules.append(ws._zig_conn)
            await ws.close()

        @app.websocket("/ws-reclose-retained")
        async def reclose_retained_handler(ws: WebSocket):
            await ws.accept()
            await retained_websockets[0].close()
            try:
                turbonet._ws_shutdown(retained_capsules[0])
            except Exception:
                capsule_state = "capsule-invalid"
            else:
                capsule_state = "capsule-live"
            await ws.send_text(f"stale-safe:{{capsule_state}}")
            await ws.close()

        @app.websocket("/ws-buffer-before-close")
        async def buffer_before_close_handler(ws: WebSocket):
            global buffered_receive_count
            await ws.accept()
            await asyncio.sleep(0.05)
            try:
                while True:
                    await ws.receive_text()
                    buffered_receive_count += 1
            except WebSocketDisconnect:
                pass

        @app.get("/ws-buffer-count/{{nonce}}")
        def buffer_count(nonce: str):
            return {{"count": buffered_receive_count}}

        if __name__ == "__main__":
            app.run(host="127.0.0.1", port={PORT})
        """
    )
    log_path = tmp_path_factory.mktemp("websocket-e2e") / "server.log"
    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    # Wait for port to come up.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
                break
        except OSError:
            if proc.poll() is not None:
                output = log_path.read_text(errors="replace")
                raise RuntimeError(
                    f"ws server exited with {proc.returncode}: {output}"
                )
            time.sleep(0.05)
    else:
        proc.terminate()
        output = log_path.read_text(errors="replace")
        raise TimeoutError(f"ws server did not start on {PORT}: {output}")

    yield f"127.0.0.1:{PORT}"

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


async def _open_raw_ws(path: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection("127.0.0.1", PORT)
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{PORT}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    writer.write(request.encode("ascii"))
    await writer.drain()
    assert b"101" in await reader.readline()
    while await reader.readline() not in (b"\r\n", b"", b"\n"):
        pass
    return reader, writer


async def _raw_upgrade_status(
    path: str,
    key: str,
    *,
    include_host: bool = True,
    http_version: str = "HTTP/1.1",
    host_header_name: str = "Host",
    upgrade_header_name: str = "Upgrade",
    extra_lines: tuple[str, ...] = (),
) -> int:
    reader, writer = await asyncio.open_connection("127.0.0.1", PORT)
    try:
        lines = [f"GET {path} {http_version}"]
        if include_host:
            lines.append(f"{host_header_name}: 127.0.0.1:{PORT}")
        lines.extend(
            (
                f"{upgrade_header_name}: websocket",
                "Connection: Upgrade",
                f"Sec-WebSocket-Key: {key}",
                "Sec-WebSocket-Version: 13",
            )
        )
        lines.extend(extra_lines)
        request = "\r\n".join(lines) + "\r\n\r\n"
        writer.write(request.encode("ascii"))
        await writer.drain()
        return int((await reader.readline()).split()[1])
    finally:
        writer.close()
        await writer.wait_closed()


def _masked_client_frame(opcode: int, payload: bytes, *, fin: bool = True) -> bytes:
    assert len(payload) <= 125
    mask = b"\x11\x22\x33\x44"
    masked = bytes(byte ^ mask[index & 3] for index, byte in enumerate(payload))
    return bytes(((0x80 if fin else 0) | opcode, 0x80 | len(payload))) + mask + masked


async def _read_server_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    header = await reader.readexactly(2)
    length = header[1] & 0x7F
    if length == 126:
        length = int.from_bytes(await reader.readexactly(2), "big")
    elif length == 127:
        length = int.from_bytes(await reader.readexactly(8), "big")
    return header[0] & 0x0F, await reader.readexactly(length)


# ── Zig-only echo route (no Python in the loop) ──

@pytest.mark.asyncio
async def test_ws_echo_text_zig(ws_server: str) -> None:
    async with websockets.connect(f"ws://{ws_server}/ws-echo") as ws:
        await ws.send("hello")
        assert await ws.recv() == "hello"


@pytest.mark.asyncio
async def test_ws_echo_binary_zig(ws_server: str) -> None:
    async with websockets.connect(f"ws://{ws_server}/ws-echo") as ws:
        await ws.send(b"\x00\xff\xab")
        assert await ws.recv() == b"\x00\xff\xab"


@pytest.mark.asyncio
async def test_ws_echo_large_zig(ws_server: str) -> None:
    """Exercise a single 64-bit-length frame beyond the 16 KiB inline buffer."""
    async with websockets.connect(f"ws://{ws_server}/ws-echo") as ws:
        msg = "x" * 70_000
        await ws.send(msg)
        reply = await asyncio.wait_for(ws.recv(), timeout=2.0)
        assert reply == msg


@pytest.mark.asyncio
async def test_ws_ping_pong_zig(ws_server: str) -> None:
    async with websockets.connect(f"ws://{ws_server}/ws-echo") as ws:
        pong = await ws.ping(b"abc")
        await asyncio.wait_for(pong, timeout=2.0)
        # Connection still alive after ping.
        await ws.send("still here")
        assert await ws.recv() == "still here"


# ── Python handler routes (FFI bridge) ──

@pytest.mark.asyncio
async def test_ws_python_echo(ws_server: str) -> None:
    async with websockets.connect(f"ws://{ws_server}/ws") as ws:
        await ws.send("hello")
        assert await ws.recv() == "py-echo:hello"
        await ws.send("again")
        assert await ws.recv() == "py-echo:again"


@pytest.mark.asyncio
async def test_ws_python_bytes(ws_server: str) -> None:
    async with websockets.connect(f"ws://{ws_server}/ws-bytes") as ws:
        await ws.send(b"abc")
        assert await ws.recv() == b"B:abc"


@pytest.mark.asyncio
async def test_ws_python_json(ws_server: str) -> None:
    async with websockets.connect(f"ws://{ws_server}/ws-json") as ws:
        await ws.send(json.dumps({"q": "hi"}))
        reply = json.loads(await ws.recv())
        assert reply == {"q": "hi", "server": "turboapi"}


@pytest.mark.asyncio
async def test_ws_python_server_close(ws_server: str) -> None:
    """Server initiates the close — client should see the close frame."""
    async with websockets.connect(f"ws://{ws_server}/ws-close") as ws:
        assert await ws.recv() == "hello"
        # Next recv raises ConnectionClosedOK because server closed cleanly.
        with pytest.raises(websockets.exceptions.ConnectionClosed):
            await ws.recv()


@pytest.mark.asyncio
async def test_ws_python_request_metadata(ws_server: str) -> None:
    """The real Zig bridge preserves the upgrade request's metadata."""
    reader, writer = await asyncio.open_connection("127.0.0.1", PORT)
    try:
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        query = "repo=codedb&tag=one&tag=two&empty="
        request = (
            f"GET /ws-metadata?{query} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{PORT}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: keep-alive, Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "X-CodeDB-Tenant: alpha\r\n"
            "X-Trace-ID: trace-196\r\n"
            "\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()

        status = await reader.readline()
        assert b"101 Switching Protocols" in status
        while await reader.readline() not in (b"\r\n", b"", b"\n"):
            pass

        frame_header = await reader.readexactly(2)
        assert frame_header[0] == 0x81  # FIN + text
        payload_len = frame_header[1] & 0x7F
        if payload_len == 126:
            payload_len = int.from_bytes(await reader.readexactly(2), "big")
        elif payload_len == 127:
            payload_len = int.from_bytes(await reader.readexactly(8), "big")
        metadata = json.loads(await reader.readexactly(payload_len))

        assert metadata["headers"]["x-codedb-tenant"] == "alpha"
        assert metadata["headers"]["x-trace-id"] == "trace-196"
        assert metadata["query_params"] == {
            "repo": "codedb",
            "tag": "two",
            "empty": "",
        }
        assert metadata["path_params"] == {}
        assert metadata["scope"] == {
            "type": "websocket",
            "scheme": "ws",
            "path": "/ws-metadata",
            "raw_path": "/ws-metadata",
            "query_string": query,
            "headers": {
                "host": f"127.0.0.1:{PORT}",
                "upgrade": "websocket",
                "connection": "keep-alive, Upgrade",
                "sec-websocket-key": key,
                "sec-websocket-version": "13",
                "x-codedb-tenant": "alpha",
                "x-trace-id": "trace-196",
            },
            "path_params": {},
        }
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_ws_python_full_duplex_server_push(ws_server: str) -> None:
    """A blocked receive must not prevent an independent server push."""
    async with websockets.connect(f"ws://{ws_server}/ws-duplex") as ws:
        assert await asyncio.wait_for(ws.recv(), timeout=2.0) == "server-push"
        await ws.send("hello")
        assert await asyncio.wait_for(ws.recv(), timeout=2.0) == "client-ack:hello"


@pytest.mark.asyncio
async def test_ws_python_concurrent_sends_are_serialized(ws_server: str) -> None:
    """Concurrent sends and reader-generated pongs never interleave frames."""
    async with websockets.connect(f"ws://{ws_server}/ws-concurrent-send") as ws:
        pongs = [await ws.ping(f"ping:{index}".encode()) for index in range(32)]
        frames = [await asyncio.wait_for(ws.recv(), timeout=2.0) for _ in range(48)]
        assert frames == [f"frame:{index}" for index in range(48)]
        await asyncio.gather(*(asyncio.wait_for(pong, timeout=2.0) for pong in pongs))
        await ws.send("close")


@pytest.mark.asyncio
async def test_ws_concurrent_close_is_idempotent(ws_server: str) -> None:
    async with websockets.connect(f"ws://{ws_server}/ws-double-close") as ws:
        await asyncio.wait_for(ws.wait_closed(), timeout=2.0)
        assert ws.close_code == 1000


@pytest.mark.asyncio
async def test_ws_rejects_cross_event_loop_capsule_use(ws_server: str) -> None:
    async with websockets.connect(f"ws://{ws_server}/ws-cross-loop") as ws:
        assert await asyncio.wait_for(ws.recv(), timeout=2.0) == "loop-rejected"


@pytest.mark.asyncio
async def test_ws_retained_capsule_fails_safe_after_handler(ws_server: str) -> None:
    async with websockets.connect(f"ws://{ws_server}/ws-retain") as ws:
        await asyncio.wait_for(ws.wait_closed(), timeout=2.0)
    async with websockets.connect(f"ws://{ws_server}/ws-reclose-retained") as ws:
        assert (
            await asyncio.wait_for(ws.recv(), timeout=2.0)
            == "stale-safe:capsule-invalid"
        )


@pytest.mark.asyncio
async def test_ws_delivers_buffered_messages_before_peer_close(ws_server: str) -> None:
    reader, writer = await _open_raw_ws("/ws-buffer-before-close")
    try:
        writer.write(
            _masked_client_frame(0x1, b"first")
            + _masked_client_frame(0x1, b"second")
            + _masked_client_frame(0x8, (1000).to_bytes(2, "big"))
        )
        await writer.drain()
        opcode, _payload = await asyncio.wait_for(_read_server_frame(reader), timeout=2.0)
        assert opcode == 0x8
    finally:
        writer.close()
        await writer.wait_closed()

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        with urllib.request.urlopen(
            f"http://{ws_server}/ws-buffer-count/{time.monotonic_ns()}", timeout=1.0
        ) as response:
            count = json.loads(response.read())["count"]
        if count == 2:
            break
        await asyncio.sleep(0.01)
    assert count == 2


@pytest.mark.asyncio
async def test_ws_echoes_valid_peer_close_code_and_reason(ws_server: str) -> None:
    async with websockets.connect(f"ws://{ws_server}/ws") as ws:
        await ws.close(code=1008, reason="policy")
        assert ws.close_code == 1008
        assert ws.close_reason == "policy"


@pytest.mark.asyncio
async def test_ws_echoes_empty_peer_close_without_inventing_a_code(
    ws_server: str,
) -> None:
    reader, writer = await _open_raw_ws("/ws-echo")
    try:
        writer.write(_masked_client_frame(0x8, b""))
        await writer.drain()
        opcode, response = await asyncio.wait_for(_read_server_frame(reader), timeout=2.0)
        assert opcode == 0x8
        assert response == b""
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (b"x", 1002),
        ((1005).to_bytes(2, "big"), 1002),
        ((1000).to_bytes(2, "big") + b"\xff", 1007),
    ],
)
async def test_ws_rejects_invalid_peer_close(
    ws_server: str, payload: bytes, expected_code: int
) -> None:
    reader, writer = await _open_raw_ws("/ws-echo")
    try:
        writer.write(_masked_client_frame(0x8, payload))
        await writer.drain()
        opcode, response = await asyncio.wait_for(_read_server_frame(reader), timeout=2.0)
        assert opcode == 0x8
        assert int.from_bytes(response[:2], "big") == expected_code
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_ws_rejects_invalid_text_utf8(ws_server: str) -> None:
    reader, writer = await _open_raw_ws("/ws-echo")
    try:
        writer.write(_masked_client_frame(0x1, b"\xff"))
        await writer.drain()
        opcode, response = await asyncio.wait_for(_read_server_frame(reader), timeout=2.0)
        assert opcode == 0x8
        assert int.from_bytes(response[:2], "big") == 1007
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key",
    ["not-base64", "c2hvcnQ=", "dGhlIHNhbXBsZSBub25jZSB0b28="],
)
async def test_ws_rejects_invalid_handshake_key(ws_server: str, key: str) -> None:
    assert await _raw_upgrade_status("/ws-echo", key) == 400


@pytest.mark.asyncio
async def test_ws_rejects_missing_host_and_http_1_0(ws_server: str) -> None:
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    assert await _raw_upgrade_status("/ws-echo", key, include_host=False) == 400
    assert await _raw_upgrade_status("/ws-echo", key, http_version="HTTP/1.0") == 400


@pytest.mark.asyncio
async def test_ws_upgrade_header_name_is_case_insensitive_and_malformed_headers_fail(
    ws_server: str,
) -> None:
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    assert (
        await _raw_upgrade_status(
            "/ws-echo", key, upgrade_header_name="uPgRaDe"
        )
        == 101
    )
    assert (
        await _raw_upgrade_status(
            "/ws-echo", key, host_header_name="Host "
        )
        == 400
    )
    assert (
        await _raw_upgrade_status(
            "/ws-echo", key, extra_lines=(" folded-value",)
        )
        == 400
    )


@pytest.mark.asyncio
async def test_ws_rejection_closes_socket_without_retaining_http_worker(
    ws_server: str,
) -> None:
    reader, writer = await asyncio.open_connection("127.0.0.1", PORT)
    try:
        request = (
            "GET /ws-echo HTTP/1.0\r\n"
            f"Host: 127.0.0.1:{PORT}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()
        response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=1)
        assert response.startswith(b"HTTP/1.1 400 ")
        assert await asyncio.wait_for(reader.read(), timeout=0.5) == b""
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_ws_rejects_noncanonical_extended_length(ws_server: str) -> None:
    reader, writer = await _open_raw_ws("/ws-echo")
    try:
        # A 125-byte payload must use the seven-bit length directly; encoding
        # it via the 16-bit form is a protocol error even if the frame is masked.
        payload = b"x" * 125
        mask = b"\x11\x22\x33\x44"
        masked = bytes(byte ^ mask[index & 3] for index, byte in enumerate(payload))
        writer.write(b"\x81\xfe\x00\x7d" + mask + masked)
        await writer.drain()
        opcode, response = await asyncio.wait_for(_read_server_frame(reader), timeout=2.0)
        assert opcode == 0x8
        assert int.from_bytes(response[:2], "big") == 1002
    finally:
        writer.close()
        await writer.wait_closed()


# ── Routing edge cases ──

@pytest.mark.asyncio
async def test_ws_unknown_path_returns_404(ws_server: str) -> None:
    with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
        async with websockets.connect(f"ws://{ws_server}/no-such-route"):
            pass
    assert exc_info.value.response.status_code == 404


# ── Fragmentation (Phase 6) ──

@pytest.mark.asyncio
async def test_ws_fragmented_message_reassembled(ws_server: str) -> None:
    """Send a fragmented text message; server must reassemble before echo."""
    # The `websockets` high-level API doesn't expose fragmentation directly,
    # so we drive the protocol manually.

    reader, writer = await asyncio.open_connection("127.0.0.1", PORT)
    try:
        # Send HTTP upgrade request manually.
        key = "dGhlIHNhbXBsZSBub25jZQ=="  # 16-byte base64 == "the sample nonce"
        req = (
            f"GET /ws-echo HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{PORT}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        writer.write(req.encode())
        await writer.drain()

        # Read 101 response.
        line = await reader.readline()
        assert b"101" in line, line
        # Drain headers.
        while True:
            hdr = await reader.readline()
            if hdr in (b"\r\n", b"", b"\n"):
                break

        # Send fragmented text "hello world" as ["hello ", "world"] with
        # FIN=0 on first frame, FIN=1 + continuation on second.
        def make_frame(fin: bool, opcode: int, payload: bytes, mask: bytes = b"\x01\x02\x03\x04") -> bytes:
            b0 = (0x80 if fin else 0) | opcode
            assert len(payload) <= 125  # keep it simple for the test
            b1 = 0x80 | len(payload)
            masked = bytes(p ^ mask[i & 3] for i, p in enumerate(payload))
            return bytes([b0, b1]) + mask + masked

        writer.write(make_frame(fin=False, opcode=0x1, payload=b"hello "))
        writer.write(make_frame(fin=True, opcode=0x0, payload=b"world"))
        await writer.drain()

        # Read the echoed frame back.
        # Expect: FIN=1, text, len=11, "hello world".
        hdr = await reader.readexactly(2)
        assert hdr[0] == 0x81, f"expected FIN+text, got {hdr[0]:#x}"
        assert hdr[1] == 11, f"expected len=11, got {hdr[1]}"
        body = await reader.readexactly(11)
        assert body == b"hello world", body
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_ws_fragmented_message_over_limit_closes_1009(ws_server: str) -> None:
    """The 16 MiB cap applies to the complete message, not each fragment."""
    chunk = "x" * (1024 * 1024)
    async with websockets.connect(
        f"ws://{ws_server}/ws-echo", max_size=None
    ) as ws:
        await ws.send([chunk] * 17)
        with pytest.raises(websockets.exceptions.ConnectionClosed):
            await ws.recv()
        assert ws.close_code == 1009
