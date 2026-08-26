"""Real-core regression coverage for bounded WebSocket admission.

TurboAPI currently gives an upgraded WebSocket exclusive use of one connection
worker for its lifetime.  This test intentionally uses a four-worker server,
caps WebSockets at three, and verifies that the fourth upgrade is rejected
before ``101 Switching Protocols`` while the reserved worker still serves HTTP.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import textwrap
import time
import urllib.request

import pytest


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


def _http_ping(server: str) -> dict[str, object]:
    with urllib.request.urlopen(f"http://{server}/ping", timeout=1.0) as response:
        return json.loads(response.read())


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
