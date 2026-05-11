"""End-to-end WebSocket tests against the real Zig HTTP core.

Boots a turboAPI server in a subprocess, connects with the `websockets`
library, and exercises:
  - The in-Zig /ws-echo route (no Python in the loop)
  - Python @app.websocket() handlers (FFI bridge)
  - text / binary / JSON / ping / close
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
from pathlib import Path

import pytest

websockets = pytest.importorskip("websockets")


REPO_ROOT = Path(__file__).resolve().parent.parent
PORT = 18920  # avoid clashes with other test servers


@pytest.fixture(scope="module")
def ws_server():
    """Spawn a turboAPI server with WS routes and yield the base URL."""
    script = textwrap.dedent(
        f"""
        from turboapi import TurboAPI
        from turboapi.websockets import WebSocket, WebSocketDisconnect

        app = TurboAPI(title="ws-e2e", version="0.0.1")
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

        if __name__ == "__main__":
            app.run(host="127.0.0.1", port={PORT})
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for port to come up.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    else:
        proc.terminate()
        raise TimeoutError(f"ws server did not start on {PORT}")

    yield f"127.0.0.1:{PORT}"

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


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
    """Exercise 16-bit length encoding."""
    async with websockets.connect(f"ws://{ws_server}/ws-echo") as ws:
        msg = "x" * 1000
        await ws.send(msg)
        reply = await ws.recv()
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
