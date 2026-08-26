"""Real Zig-core coverage for pre-upgrade WebSocket guards."""

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

_WEBSOCKET_KEY = base64.b64encode(b"guard-test-key-1").decode("ascii")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def guarded_server(tmp_path_factory: pytest.TempPathFactory):
    port = _free_port()
    log_path = tmp_path_factory.mktemp("websocket-guard") / "server.log"
    script = textwrap.dedent(
        f"""
        from turboapi import (
            TurboAPI,
            WebSocketUpgradeRejection,
            WebSocketUpgradeRequest,
        )
        from turboapi.websockets import WebSocket, WebSocketDisconnect

        app = TurboAPI(title="ws-guard-e2e", version="0.0.1")
        state = {{"handled": 0, "swapped": False}}

        def guard(request: WebSocketUpgradeRequest):
            if request.headers.get("origin") != "https://allowed.example":
                return WebSocketUpgradeRejection(403)
            if request.headers.get("authorization") != "Bearer integration-credential":
                return WebSocketUpgradeRejection(401)
            if request.query_params.get("tenant") != "alpha":
                return WebSocketUpgradeRejection(403)
            return True

        def exploding_guard(_request: WebSocketUpgradeRequest):
            raise RuntimeError("Bearer never-log-this-value")

        def allow_swap(_request: WebSocketUpgradeRequest):
            return True

        def swap_guard(_request: WebSocketUpgradeRequest):
            if not state["swapped"]:
                async def new_handler(ws: WebSocket):
                    await ws.accept()
                    await ws.receive_text()
                    await ws.send_text("new")
                    try:
                        await ws.receive_text()
                    except WebSocketDisconnect:
                        pass

                app.websocket("/swap", guard=allow_swap)(new_handler)
                state["swapped"] = True
            return True

        @app.get("/stats")
        def stats(probe: int = 0):
            _ = probe
            return state

        @app.websocket("/guarded", guard=guard)
        async def guarded(ws: WebSocket):
            state["handled"] += 1
            await ws.accept()
            await ws.send_text("ready")
            try:
                while True:
                    await ws.receive_text()
            except WebSocketDisconnect:
                pass

        @app.websocket("/exploding", guard=exploding_guard)
        async def exploding(ws: WebSocket):
            state["handled"] += 1
            await ws.accept()

        @app.websocket("/swap", guard=swap_guard)
        async def old_handler(ws: WebSocket):
            await ws.accept()
            await ws.receive_text()
            await ws.send_text("old")
            try:
                await ws.receive_text()
            except WebSocketDisconnect:
                pass

        if __name__ == "__main__":
            app.run(host="127.0.0.1", port={port})
        """
    )
    env = os.environ.copy()
    env.update(
        {
            "TURBO_THREAD_POOL_SIZE": "4",
            "TURBO_HTTP_WORKER_RESERVE": "1",
            "TURBO_MAX_WEBSOCKETS": "1",
        }
    )
    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            if proc.poll() is not None:
                output = log_path.read_text(errors="replace")
                raise RuntimeError(f"guard server exited with {proc.returncode}: {output}")
            time.sleep(0.05)
    else:
        proc.terminate()
        raise TimeoutError("guard server did not start")

    yield f"127.0.0.1:{port}", log_path

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _upgrade(
    server: str,
    path: str,
    *,
    authorization: str | None = None,
    origin: str | None = "https://allowed.example",
    security_headers: list[tuple[str, str]] | None = None,
) -> tuple[socket.socket, int, bytes]:
    host, port_text = server.rsplit(":", 1)
    client = socket.create_connection((host, int(port_text)), timeout=2)
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {server}",
        "Upgrade: websocket",
        "Connection: Upgrade",
    ]
    if security_headers is None:
        lines.extend(
            [
                f"Sec-WebSocket-Key: {_WEBSOCKET_KEY}",
                "Sec-WebSocket-Version: 13",
            ]
        )
        if authorization is not None:
            lines.append(f"Authorization: {authorization}")
        if origin is not None:
            lines.append(f"Origin: {origin}")
    else:
        lines.extend(f"{name}: {value}" for name, value in security_headers)
    client.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))

    response = bytearray()
    while b"\r\n\r\n" not in response:
        # Read exactly through the HTTP header terminator so a coalesced first
        # WebSocket frame remains available to the close/frame assertions.
        chunk = client.recv(1)
        if not chunk:
            break
        response.extend(chunk)
        if len(response) > 1024:
            raise AssertionError("unbounded WebSocket rejection")
    status = int(response.split(b" ", 2)[1])
    return client, status, bytes(response)


def _close(client: socket.socket) -> None:
    mask = b"\x01\x02\x03\x04"
    payload = b"\x03\xe8"
    masked = bytes(byte ^ mask[index & 3] for index, byte in enumerate(payload))
    client.settimeout(2)
    try:
        client.sendall(b"\x88\x82" + mask + masked)
        for _ in range(4):
            opcode, _payload = _receive_server_frame(client)
            if opcode == 0x08:
                return
        raise AssertionError("server did not complete the WebSocket close handshake")
    finally:
        client.close()


def _receive_exactly(client: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        chunk = client.recv(length - len(result))
        if not chunk:
            raise AssertionError("server closed before completing the WebSocket frame")
        result.extend(chunk)
    return bytes(result)


def _receive_server_frame(client: socket.socket) -> tuple[int, bytes]:
    header = _receive_exactly(client, 2)
    opcode = header[0] & 0x0F
    payload_length = header[1] & 0x7F
    if payload_length == 126:
        payload_length = int.from_bytes(_receive_exactly(client, 2), "big")
    elif payload_length == 127:
        payload_length = int.from_bytes(_receive_exactly(client, 8), "big")
    assert not header[1] & 0x80, "server frames must not be masked"
    return opcode, _receive_exactly(client, payload_length)


def _send_masked_text(client: socket.socket, text: str) -> None:
    payload = text.encode("utf-8")
    assert len(payload) < 126
    mask = b"\x05\x06\x07\x08"
    masked = bytes(byte ^ mask[index & 3] for index, byte in enumerate(payload))
    client.sendall(bytes((0x81, 0x80 | len(payload))) + mask + masked)


def _valid_security_headers() -> list[tuple[str, str]]:
    return [
        ("Sec-WebSocket-Key", _WEBSOCKET_KEY),
        ("Sec-WebSocket-Version", "13"),
        ("Authorization", "Bearer integration-credential"),
        ("Origin", "https://allowed.example"),
    ]


def _wait_for_upgrade_slot(
    server: str,
    path: str,
    *,
    authorization: str | None = None,
    timeout: float = 2,
) -> socket.socket:
    deadline = time.monotonic() + timeout
    last_status = 0
    while time.monotonic() < deadline:
        client, last_status, _response = _upgrade(
            server,
            path,
            authorization=authorization,
        )
        if last_status == 101:
            return client
        client.close()
        assert last_status == 503
        time.sleep(0.01)
    raise AssertionError(f"WebSocket slot was not released within {timeout}s; {last_status=}")


def _stats(server: str) -> dict[str, int]:
    probe = time.monotonic_ns()
    with urllib.request.urlopen(f"http://{server}/stats?probe={probe}", timeout=2) as response:
        return json.loads(response.read())


def _assert_bounded_empty_denial(response: bytes, status: int) -> None:
    assert response.startswith(f"HTTP/1.1 {status} ".encode("ascii"))
    headers, body = response.split(b"\r\n\r\n", 1)
    assert len(response) <= 512
    assert b"Content-Length: 0" in headers
    assert b"Cache-Control: no-store" in headers
    assert body == b""


def test_missing_and_invalid_credentials_never_upgrade(guarded_server) -> None:
    server, _log_path = guarded_server
    before = _stats(server)["handled"]
    for authorization in (None, "Bearer incorrect"):
        client, status, response = _upgrade(
            server, "/guarded?tenant=alpha", authorization=authorization
        )
        try:
            assert status == 401
            assert b"101 Switching Protocols" not in response
            assert b"WWW-Authenticate: Bearer" in response
            _assert_bounded_empty_denial(response, 401)
        finally:
            client.close()
    assert _stats(server)["handled"] == before


def test_origin_allowlist_and_request_metadata(guarded_server) -> None:
    server, _log_path = guarded_server
    denied, status, response = _upgrade(
        server,
        "/guarded?tenant=alpha",
        authorization="Bearer integration-credential",
        origin="https://denied.example",
    )
    try:
        assert status == 403
        _assert_bounded_empty_denial(response, 403)
    finally:
        denied.close()

    allowed, status, response = _upgrade(
        server,
        "/guarded?tenant=alpha",
        authorization="Bearer integration-credential",
    )
    try:
        assert status == 101
        assert b"101 Switching Protocols" in response
    finally:
        _close(allowed)


@pytest.mark.parametrize(
    "duplicate_headers",
    [
        [
            ("Authorization", "Bearer integration-credential"),
            ("aUtHoRiZaTiOn", "Bearer incorrect"),
        ],
        [
            ("authorization", "Bearer incorrect"),
            ("AUTHORIZATION", "Bearer integration-credential"),
        ],
        [
            ("Origin", "https://allowed.example"),
            ("oRiGiN", "https://denied.example"),
        ],
        [
            ("origin", "https://denied.example"),
            ("ORIGIN", "https://allowed.example"),
        ],
        [
            ("Sec-WebSocket-Key", _WEBSOCKET_KEY),
            ("sEc-WeBsOcKeT-kEy", "another-key"),
        ],
        [
            ("sec-websocket-key", "another-key"),
            ("SEC-WEBSOCKET-KEY", _WEBSOCKET_KEY),
        ],
        [
            ("Sec-WebSocket-Version", "13"),
            ("sEc-WeBsOcKeT-vErSiOn", "12"),
        ],
        [
            ("sec-websocket-version", "12"),
            ("SEC-WEBSOCKET-VERSION", "13"),
        ],
    ],
)
def test_duplicate_security_headers_fail_before_guard(
    guarded_server, duplicate_headers: list[tuple[str, str]]
) -> None:
    server, _log_path = guarded_server
    duplicate_name = duplicate_headers[0][0].lower()
    remaining_headers = [
        header
        for header in _valid_security_headers()
        if header[0].lower() != duplicate_name
    ]
    client, status, response = _upgrade(
        server,
        "/guarded?tenant=alpha",
        security_headers=duplicate_headers + remaining_headers,
    )
    try:
        assert status == 400
        assert b"101 Switching Protocols" not in response
        headers, body = response.split(b"\r\n\r\n", 1)
        assert b"Content-Length: 0" in headers
        assert body == b""
    finally:
        client.close()


def test_guard_runs_before_capacity_admission(guarded_server) -> None:
    server, _log_path = guarded_server
    allowed, status, _response = _upgrade(
        server,
        "/guarded?tenant=alpha",
        authorization="Bearer integration-credential",
    )
    assert status == 101
    try:
        rejected, rejected_status, response = _upgrade(server, "/guarded?tenant=alpha")
        try:
            assert rejected_status == 401, "guard denial must win over capacity 503"
            _assert_bounded_empty_denial(response, 401)
        finally:
            rejected.close()
        assert _stats(server)["handled"] >= 1
    finally:
        _close(allowed)

    replacement = _wait_for_upgrade_slot(
        server,
        "/guarded?tenant=alpha",
        authorization="Bearer integration-credential",
    )
    _close(replacement)


def test_guard_exception_fails_closed_without_secret_logging(guarded_server) -> None:
    server, log_path = guarded_server
    client, status, response = _upgrade(server, "/exploding")
    try:
        assert status == 403
        _assert_bounded_empty_denial(response, 403)
    finally:
        client.close()
    time.sleep(0.05)
    output = log_path.read_text(errors="replace")
    assert "never-log-this-value" not in output


def test_live_replacement_keeps_one_owned_snapshot_through_handler(guarded_server) -> None:
    server, _log_path = guarded_server

    first, status, _response = _upgrade(server, "/swap")
    assert status == 101
    try:
        _send_masked_text(first, "go")
        assert _receive_server_frame(first) == (0x01, b"old")
    finally:
        _close(first)

    second = _wait_for_upgrade_slot(server, "/swap")
    try:
        _send_masked_text(second, "go")
        assert _receive_server_frame(second) == (0x01, b"new")
    finally:
        _close(second)
