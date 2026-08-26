"""Real-core regression coverage for native connection capacity.

TurboAPI transfers upgraded WebSockets to an isolated, bounded worker pool.
This test intentionally uses one ordinary HTTP worker and three WebSocket
workers, verifies that the fourth upgrade is rejected before ``101 Switching
Protocols``, and proves HTTP remains responsive under the saturated WS load.

The native HTTP core also keeps a worker attached to each persistent connection.
The pool-ceiling regression starts 256 workers and proves that all 256 requested
keep-alive connections can receive an HTTP response instead of being silently
clamped to a smaller pool.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request

import pytest

try:
    import resource
except ImportError:  # pragma: no cover - the native core is Unix-only today
    resource = None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def capped_ws_server():
    port = _free_port()
    script = textwrap.dedent(
        f"""
        from turboapi import TurboAPI

        app = TurboAPI(title="ws-capacity-e2e", version="0.0.1")

        @app.get("/ping")
        def ping():
            return {{"ok": True}}

        if __name__ == "__main__":
            app.run(host="127.0.0.1", port={port})
        """
    )
    env = os.environ.copy()
    env.update(
        {
            "TURBO_THREAD_POOL_SIZE": "1",
            "TURBO_WS_WORKER_POOL_SIZE": "3",
            "TURBO_MAX_WEBSOCKETS": "3",
        }
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError(f"capacity test server exited with {proc.returncode}")
            time.sleep(0.05)
    else:
        proc.terminate()
        raise TimeoutError(f"capacity test server did not start on {port}")

    yield f"127.0.0.1:{port}"

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture
def backpressure_ws_server():
    port = _free_port()
    script = textwrap.dedent(
        f"""
        import asyncio

        from turboapi import TurboAPI
        from turboapi.websockets import WebSocket, WebSocketDisconnect

        app = TurboAPI(title="ws-backpressure-e2e", version="0.0.1")

        @app.get("/ping")
        def ping():
            return {{"ok": True}}

        @app.websocket("/ws-slow-reader")
        async def slow_reader(ws: WebSocket):
            await ws.accept()
            payload = b"x" * (256 * 1024)
            await asyncio.gather(
                *(ws.send_bytes(payload) for _ in range(32)),
                return_exceptions=True,
            )

        @app.websocket("/ws-inbound-overload")
        async def inbound_overload(ws: WebSocket):
            await ws.accept()
            await asyncio.sleep(0.2)
            try:
                await ws.receive_text()
            except WebSocketDisconnect:
                pass

        @app.websocket("/ws-idle")
        async def idle_socket(ws: WebSocket):
            await ws.accept()
            await asyncio.sleep(0.35)
            await ws.send_text("still-alive")
            await ws.close()

        if __name__ == "__main__":
            app.run(host="127.0.0.1", port={port})
        """
    )
    env = os.environ.copy()
    env.update(
        {
            "TURBO_THREAD_POOL_SIZE": "1",
            "TURBO_WS_WORKER_POOL_SIZE": "2",
            "TURBO_MAX_WEBSOCKETS": "2",
            "TURBO_WS_QUEUE_MESSAGES": "4",
            "TURBO_WS_QUEUE_BYTES": str(1024 * 1024),
            "TURBO_HTTP_HEADER_TIMEOUT_MS": "100",
        }
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError(f"backpressure server exited with {proc.returncode}")
            time.sleep(0.05)
    else:
        proc.terminate()
        raise TimeoutError(f"backpressure server did not start on {port}")

    yield f"127.0.0.1:{port}", proc

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture
def blocked_write_ws_server():
    port = _free_port()
    script = textwrap.dedent(
        f"""
        from turboapi import TurboAPI
        from turboapi.websockets import WebSocket

        app = TurboAPI(title="ws-blocked-write", version="0.0.1")

        @app.get("/ping")
        def ping():
            return {{"ok": True}}

        @app.websocket("/ws-one-blocked-write")
        async def one_blocked_write(ws: WebSocket):
            await ws.accept()
            await ws.send_bytes(b"x" * (16 * 1024 * 1024))
            await ws.close()

        if __name__ == "__main__":
            app.run(host="127.0.0.1", port={port})
        """
    )
    env = os.environ.copy()
    env.update(
        {
            "TURBO_THREAD_POOL_SIZE": "1",
            "TURBO_WS_WORKER_POOL_SIZE": "1",
            "TURBO_MAX_WEBSOCKETS": "1",
            "TURBO_WS_QUEUE_BYTES": str(16 * 1024 * 1024),
            "TURBO_WS_WRITE_TIMEOUT_MS": "100",
        }
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError(f"blocked-write server exited with {proc.returncode}")
            time.sleep(0.05)
    else:
        proc.terminate()
        raise TimeoutError(f"blocked-write server did not start on {port}")
    yield f"127.0.0.1:{port}", proc
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture
def pool256_server(tmp_path: pathlib.Path):
    if resource is None:
        pytest.skip("resource limits are unavailable on this platform")

    original_nofile = resource.getrlimit(resource.RLIMIT_NOFILE)
    desired_nofile = 512
    if original_nofile[0] < desired_nofile:
        if original_nofile[1] < desired_nofile:
            pytest.skip("hard file-descriptor limit is below 512")
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (desired_nofile, original_nofile[1]),
        )

    port = _free_port()
    script = textwrap.dedent(
        f"""
        from turboapi import TurboAPI

        app = TurboAPI(title="pool-capacity-e2e", version="0.0.1")

        @app.get("/ping")
        def ping():
            return {{"ok": True}}

        if __name__ == "__main__":
            app.run(host="127.0.0.1", port={port})
        """
    )
    env = os.environ.copy()
    env["TURBO_THREAD_POOL_SIZE"] = "256"
    log_path = tmp_path / "pool256-server.log"
    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError(f"pool test server exited with {proc.returncode}")
            time.sleep(0.05)
    else:
        proc.terminate()
        raise TimeoutError(f"pool test server did not start on {port}")

    try:
        yield f"127.0.0.1:{port}", log_path
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if original_nofile[0] < desired_nofile:
            resource.setrlimit(resource.RLIMIT_NOFILE, original_nofile)


def _http_ping(server: str) -> dict[str, object]:
    with urllib.request.urlopen(f"http://{server}/ping", timeout=1.0) as response:
        return json.loads(response.read())


def _persistent_http_ping(server: str) -> socket.socket:
    host, port_text = server.rsplit(":", 1)
    client = socket.create_connection((host, int(port_text)), timeout=5.0)
    request = (
        "GET /ping HTTP/1.1\r\n"
        f"Host: {server}\r\n"
        "Connection: keep-alive\r\n"
        "\r\n"
    )
    client.sendall(request.encode("ascii"))

    response = bytearray()
    while b"\r\n\r\n" not in response:
        chunk = client.recv(4096)
        if not chunk:
            raise AssertionError("server closed before sending response headers")
        response.extend(chunk)
        if len(response) > 8192:
            raise AssertionError("oversized HTTP response headers")

    raw_headers, body = bytes(response).split(b"\r\n\r\n", 1)
    first_line, *header_lines = raw_headers.split(b"\r\n")
    assert first_line.split()[1] == b"200"
    headers = {
        name.strip().lower(): value.strip()
        for line in header_lines
        for name, value in [line.split(b":", 1)]
    }
    content_length = int(headers[b"content-length"])
    while len(body) < content_length:
        chunk = client.recv(content_length - len(body))
        if not chunk:
            raise AssertionError("server closed before sending the response body")
        body += chunk
    assert json.loads(body[:content_length]) == {"ok": True}
    return client


def _wait_for_log(
    log_path: pathlib.Path,
    expected: str,
    *,
    timeout: float = 5.0,
) -> None:
    """Wait for a child-process diagnostic to become visible on disk."""
    deadline = time.monotonic() + timeout
    output = ""
    while time.monotonic() < deadline:
        output = log_path.read_text(errors="replace")
        if expected in output:
            return
        time.sleep(0.01)

    raise AssertionError(
        f"server log did not contain {expected!r} within {timeout:.1f}s; last output: {output!r}"
    )


def _upgrade(server: str, path: str = "/ws-echo") -> tuple[socket.socket, int]:
    host, port_text = server.rsplit(":", 1)
    client = socket.create_connection((host, int(port_text)), timeout=1.0)
    key = base64.b64encode(b"turbo-capacity-1").decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {server}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    client.sendall(request.encode("ascii"))
    response = bytearray()
    while b"\r\n\r\n" not in response:
        chunk = client.recv(4096)
        if not chunk:
            break
        response.extend(chunk)
        if len(response) > 8192:
            raise AssertionError("oversized WebSocket upgrade response")
    first_line = bytes(response).split(b"\r\n", 1)[0]
    status = int(first_line.split()[1])
    return client, status


def _rss_kib(pid: int) -> int:
    output = subprocess.check_output(
        ["ps", "-o", "rss=", "-p", str(pid)], text=True
    ).strip()
    return int(output)


def _close_websocket(client: socket.socket) -> None:
    # Masked close frame with status 1000. Waiting for the peer close makes the
    # worker's deferred active-count cleanup deterministic before reconnect.
    mask = b"\x01\x02\x03\x04"
    payload = b"\x03\xe8"
    masked = bytes(byte ^ mask[index & 3] for index, byte in enumerate(payload))
    try:
        client.sendall(b"\x88\x82" + mask + masked)
        client.recv(128)
    except OSError:
        pass
    finally:
        client.close()


def _masked_text_frame(payload: bytes) -> bytes:
    assert len(payload) <= 125
    mask = b"\x11\x22\x33\x44"
    masked = bytes(byte ^ mask[index & 3] for index, byte in enumerate(payload))
    return bytes((0x81, 0x80 | len(payload))) + mask + masked


def test_websocket_pool_isolates_http_and_reuses_slot(capped_ws_server: str) -> None:
    clients: list[socket.socket] = []
    try:
        for _ in range(3):
            client, status = _upgrade(capped_ws_server)
            assert status == 101
            clients.append(client)

        rejected, status = _upgrade(capped_ws_server)
        rejected.close()
        assert status == 503

        # The WebSockets are all deliberately idle here. The sole HTTP worker
        # remains available because upgraded sockets have transferred pools.
        assert _http_ping(capped_ws_server) == {"ok": True}

        _close_websocket(clients.pop())

        replacement, status = _upgrade(capped_ws_server)
        assert status == 101
        clients.append(replacement)
        assert _http_ping(capped_ws_server) == {"ok": True}
    finally:
        for client in clients:
            _close_websocket(client)


def test_slow_reader_is_bounded_and_http_remains_responsive(
    backpressure_ws_server,
) -> None:
    server, proc = backpressure_ws_server
    rss_before = _rss_kib(proc.pid)
    clients = []
    try:
        # Two connections simultaneously saturate their bounded native output
        # queues. Emergency abort does not wait behind a blocked writer, so
        # both transports still shed promptly instead of deadlocking.
        for _ in range(2):
            client, status = _upgrade(server, "/ws-slow-reader")
            assert status == 101
            clients.append(client)

        # Do not read while the application attempts 8 MiB of concurrent
        # output. The 1 MiB/4-message queue must fail closed without retaining
        # all payloads or occupying the ordinary HTTP worker.
        time.sleep(0.15)
        started = time.monotonic()
        for _ in range(20):
            assert _http_ping(server) == {"ok": True}
        assert time.monotonic() - started < 2.0

        rss_after = _rss_kib(proc.pid)
        assert rss_after - rss_before < 64 * 1024

        for client in clients:
            client.settimeout(2.0)
            received = 0
            while True:
                chunk = client.recv(64 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                assert received < 8 * 1024 * 1024
    finally:
        for client in clients:
            client.close()


def test_inbound_queue_overload_closes_with_try_again_later(
    backpressure_ws_server,
) -> None:
    server, _proc = backpressure_ws_server
    client, status = _upgrade(server, "/ws-inbound-overload")
    assert status == 101
    try:
        client.sendall(b"".join(_masked_text_frame(f"m{index}".encode()) for index in range(16)))
        client.settimeout(2.0)
        response = client.recv(512)
        assert response and response[0] & 0x0F == 0x08
        payload_len = response[1] & 0x7F
        assert payload_len >= 2
        assert int.from_bytes(response[2:4], "big") == 1013
    finally:
        client.close()


def test_websocket_idle_survives_http_header_timeout(backpressure_ws_server) -> None:
    server, _proc = backpressure_ws_server
    client, status = _upgrade(server, "/ws-idle")
    assert status == 101
    try:
        client.settimeout(2.0)
        header = client.recv(2)
        assert header == b"\x81\x0b"
        assert client.recv(11) == b"still-alive"
    finally:
        client.close()


def test_single_blocked_write_has_deadline_and_releases_slot(
    blocked_write_ws_server,
) -> None:
    server, proc = blocked_write_ws_server
    rss_before = _rss_kib(proc.pid)
    client, status = _upgrade(server, "/ws-one-blocked-write")
    assert status == 101
    try:
        # The client intentionally never reads the 16 MiB frame. Both the
        # blocking fast path and readiness-driven flush share the 100 ms bound.
        time.sleep(0.5)
        assert _http_ping(server) == {"ok": True}
        replacement, replacement_status = _upgrade(server, "/ws-one-blocked-write")
        replacement.close()
        assert replacement_status == 101
        assert _rss_kib(proc.pid) - rss_before < 64 * 1024
    finally:
        client.close()


def test_requested_pool256_serves_256_persistent_clients(pool256_server) -> None:
    server, log_path = pool256_server
    clients: list[socket.socket] = []
    try:
        # This direct native-core signal makes the ceiling assertion independent
        # of load timing. The child writes the log asynchronously relative to
        # this test process, so allow a bounded interval for it to become visible.
        # The persistent clients below remain the authoritative behavior check.
        _wait_for_log(log_path, "Zig HTTP core active – 256-thread pool")

        for _ in range(256):
            clients.append(_persistent_http_ping(server))
    finally:
        for client in clients:
            client.close()
