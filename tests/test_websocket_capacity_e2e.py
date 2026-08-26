"""Real-core regression coverage for native connection capacity.

TurboAPI currently gives an upgraded WebSocket exclusive use of one connection
worker for its lifetime.  This test intentionally uses a four-worker server,
caps WebSockets at three, and verifies that the fourth upgrade is rejected
before ``101 Switching Protocols`` while the reserved worker still serves HTTP.

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
            "TURBO_THREAD_POOL_SIZE": "4",
            "TURBO_HTTP_WORKER_RESERVE": "1",
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


def _upgrade(server: str) -> tuple[socket.socket, int]:
    host, port_text = server.rsplit(":", 1)
    client = socket.create_connection((host, int(port_text)), timeout=1.0)
    key = base64.b64encode(b"turbo-capacity-1").decode("ascii")
    request = (
        "GET /ws-echo HTTP/1.1\r\n"
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


def test_websocket_cap_preserves_http_worker_and_reuses_slot(capped_ws_server: str) -> None:
    clients: list[socket.socket] = []
    try:
        for _ in range(3):
            client, status = _upgrade(capped_ws_server)
            assert status == 101
            clients.append(client)

        rejected, status = _upgrade(capped_ws_server)
        rejected.close()
        assert status == 503

        # The WebSockets are all deliberately idle here.  HTTP must still have
        # a worker available instead of waiting behind those long-lived sockets.
        assert _http_ping(capped_ws_server) == {"ok": True}

        _close_websocket(clients.pop())

        replacement, status = _upgrade(capped_ws_server)
        assert status == 101
        clients.append(replacement)
        assert _http_ping(capped_ws_server) == {"ok": True}
    finally:
        for client in clients:
            _close_websocket(client)


def test_requested_pool256_serves_256_persistent_clients(pool256_server) -> None:
    server, log_path = pool256_server
    clients: list[socket.socket] = []
    try:
        # This direct native-core signal makes the ceiling assertion independent
        # of load timing.  The persistent clients below exercise the behavior.
        assert "Zig HTTP core active – 256-thread pool" in log_path.read_text()

        for _ in range(256):
            clients.append(_persistent_http_ping(server))
    finally:
        for client in clients:
            client.close()
