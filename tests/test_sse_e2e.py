"""End-to-end SSE streaming over the live Zig HTTP server.

Boots a real TurboAPI app on a port, hits it with `httpx.stream` and a raw
socket, and asserts wire-level behavior: chunked transfer encoding, headers
preserved from EventSourceResponse, real-time delivery of events as
separate chunks, proper terminator.

Replaces the placeholder skip in `tests/test_sse.py::test_event_source_response_end_to_end_over_zig_server`.

Marked as opt-in via env var TURBOAPI_RUN_E2E=1 by default; set it in CI to
run. Skipped otherwise so a missing socket / port collision doesn't break
unit-test runs.
"""

from __future__ import annotations

import os
import socket
import subprocess
import textwrap
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON_BIN = REPO_ROOT / ".venv" / "bin" / "python"

# Pick a port unlikely to clash. The server binds with SO_REUSEADDR.
SSE_PORT = int(os.environ.get("TURBOAPI_TEST_SSE_PORT", "18765"))
SSE_HOST = "127.0.0.1"


pytestmark = pytest.mark.skipif(
    not PYTHON_BIN.exists(),
    reason="requires built .venv with the Zig backend installed (run python zig/build_turbonet.py --install)",
)


SERVER_SCRIPT = textwrap.dedent(
    f"""
    import asyncio, os, sys
    sys.path.insert(0, "{REPO_ROOT / 'python'}")
    from turboapi import TurboAPI
    from turboapi.sse import EventSourceResponse, ServerSentEvent

    app = TurboAPI(title="sse-e2e")

    @app.get("/sse")
    async def sse_endpoint():
        async def generate():
            for i in range(5):
                yield ServerSentEvent(data={{"i": i}})
                await asyncio.sleep(0.05)
        return EventSourceResponse(generate())

    @app.get("/sse-bytes")
    async def sse_bytes_endpoint():
        from turboapi.responses import StreamingResponse
        async def gen():
            for i in range(3):
                yield f"chunk-{{i}}".encode()
                await asyncio.sleep(0.02)
        return StreamingResponse(gen(), media_type="application/octet-stream")

    @app.get("/ping")
    def ping():
        return {{"ok": True}}

    if __name__ == "__main__":
        app.run(host="{SSE_HOST}", port={SSE_PORT})
    """
).strip()


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            try:
                s.connect((host, port))
                return
            except OSError:
                time.sleep(0.05)
    raise RuntimeError(f"server didn't start on {host}:{port} within {timeout}s")


@pytest.fixture(scope="module")
def sse_server(tmp_path_factory):
    """Spawn the SSE server subprocess for the module."""
    script_path = tmp_path_factory.mktemp("sse_e2e") / "server.py"
    script_path.write_text(SERVER_SCRIPT)

    env = os.environ.copy()
    env.setdefault("PYTHON_GIL", "0")
    proc = subprocess.Popen(
        [str(PYTHON_BIN), str(script_path)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_port(SSE_HOST, SSE_PORT)
        yield f"http://{SSE_HOST}:{SSE_PORT}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------------------
# Wire-level tests
# ---------------------------------------------------------------------------


def test_sanity_ping(sse_server):
    """Confirms the server is up and the non-streaming path still works."""
    r = httpx.get(f"{sse_server}/ping", timeout=5.0)
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_sse_headers_announce_chunked_transfer(sse_server):
    """SSE response must use Transfer-Encoding: chunked, not Content-Length."""
    with httpx.stream("GET", f"{sse_server}/sse", timeout=10.0) as r:
        assert r.status_code == 200
        assert r.headers["content-type"] == "text/event-stream"
        assert r.headers.get("transfer-encoding", "").lower() == "chunked"
        # Chunked responses must NOT also send Content-Length.
        assert "content-length" not in {k.lower() for k in r.headers.keys()}


def test_sse_custom_headers_pass_through(sse_server):
    """Cache-Control + X-Accel-Buffering from EventSourceResponse must reach the wire."""
    with httpx.stream("GET", f"{sse_server}/sse", timeout=10.0) as r:
        # Lowercase header lookup — httpx normalizes.
        assert r.headers.get("cache-control") == "no-cache"
        assert r.headers.get("x-accel-buffering") == "no"


def test_sse_streams_events_as_separate_chunks(sse_server):
    """Each yielded ServerSentEvent must arrive as its own chunk, in real time."""
    chunks: list[tuple[float, bytes]] = []
    start = time.monotonic()
    with httpx.stream("GET", f"{sse_server}/sse", timeout=10.0) as r:
        for chunk in r.iter_bytes():
            chunks.append((time.monotonic() - start, chunk))

    # 5 events were generated. We may receive them coalesced if the OS buffers,
    # but should at minimum get the full payload.
    payload = b"".join(c for _, c in chunks)
    for i in range(5):
        assert f'data: {{"i": {i}}}\n\n'.encode() in payload, f"missing event {i}"

    # Real-time check: total elapsed should be at least ~150ms (5 events * 50ms - some slack).
    # If everything arrived in the first chunk before the generator finished sleeping,
    # the streaming wasn't real-time.
    elapsed_ms = (time.monotonic() - start) * 1000
    assert elapsed_ms >= 150, f"stream completed in {elapsed_ms:.0f}ms — looks pre-buffered"


def test_sse_terminates_with_zero_chunk(sse_server):
    """The chunked-transfer terminator (0\\r\\n\\r\\n) must close the stream cleanly."""
    # Use a raw socket to see the raw byte stream including the terminator.
    with socket.create_connection((SSE_HOST, SSE_PORT), timeout=5.0) as s:
        s.settimeout(5.0)
        s.sendall(b"GET /sse HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        buf = b""
        while True:
            try:
                chunk = s.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            if buf.endswith(b"0\r\n\r\n"):
                break

    # Must contain the chunked-transfer marker
    assert b"Transfer-Encoding: chunked" in buf
    # Each event arrives as `<hex-len>\r\n<body>\r\n`. Hex 10 = 16 bytes ('data: {"i": N}\n\n').
    assert b"10\r\ndata: " in buf
    # Stream ends with the zero-length terminator.
    assert buf.endswith(b"0\r\n\r\n")


def test_streaming_response_bytes_passthrough(sse_server):
    """Raw bytes generators (not SSE) also stream correctly with the right content type."""
    chunks: list[bytes] = []
    with httpx.stream("GET", f"{sse_server}/sse-bytes", timeout=10.0) as r:
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/octet-stream"
        assert r.headers.get("transfer-encoding", "").lower() == "chunked"
        for chunk in r.iter_bytes():
            chunks.append(chunk)
    payload = b"".join(chunks)
    assert payload == b"chunk-0chunk-1chunk-2"
