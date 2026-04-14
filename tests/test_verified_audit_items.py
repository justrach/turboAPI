"""Verifier tests for the remaining audit-backed compatibility gaps.

These are focused reproducers for known incomplete behavior. They are marked
xfail so they can live in the suite as executable issue documentation until
the underlying behavior is implemented.
"""

import socket
import threading
import time

import pytest
import requests
from turboapi import TurboAPI
from turboapi.middleware import GZipMiddleware


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(app: TurboAPI, port: int) -> str:
    thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port),
        daemon=True,
    )
    thread.start()
    time.sleep(1.5)
    return f"http://127.0.0.1:{port}"


def test_verified_gzip_passthrough_round_trip():
    """Test that GZipMiddleware compresses responses when Accept-Encoding: gzip is present."""
    from turboapi.testclient import TestClient
    import gzip
    import json

    app = TurboAPI(title="VerifiedGZip")
    app.add_middleware(GZipMiddleware, minimum_size=10)

    @app.get("/large")
    def large_response():
        return {"data": "A" * 1000}

    client = TestClient(app)
    response = client.get("/large", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("Content-Encoding") == "gzip"
    # Decompress and verify
    decompressed = gzip.decompress(response.content)
    parsed = json.loads(decompressed)
    assert len(parsed["data"]) == 1000


@pytest.mark.xfail(reason="Implicit header extraction still requires explicit Header() markers")
def test_verified_implicit_header_extraction():
    app = TurboAPI(title="VerifiedHeaders")

    @app.get("/auth")
    def auth_check(authorization: str = "missing", x_request_id: str = "missing"):
        return {
            "authorization": authorization,
            "request_id": x_request_id,
        }

    base = _start_server(app, _free_port())
    response = requests.get(
        f"{base}/auth",
        headers={
            "Authorization": "Bearer token123",
            "X-Request-ID": "req-42",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "authorization": "Bearer token123",
        "request_id": "req-42",
    }


def test_verified_password_hashing_helpers():
    """Test that password hashing and verification work correctly."""
    from turboapi.security import get_password_hash, verify_password

    hashed = get_password_hash("secret123")

    assert hashed != "secret123"
    assert verify_password("secret123", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_verified_top_level_verify_password_export_matches_security_module():
    """Test that top-level verify_password export is from security module, not jwt_auth."""
    from turboapi import verify_password as top_verify
    from turboapi.jwt_auth import verify_password as jwt_verify
    from turboapi.security import verify_password as security_verify

    assert top_verify is security_verify
    assert top_verify is not jwt_verify


@pytest.mark.asyncio
async def test_verified_websocket_runtime_dispatch():
    """Test that WebSocket endpoints work via ASGI dispatch."""
    app = TurboAPI(title="VerifiedWebSocket")
    events = []

    @app.websocket("/ws")
    async def websocket_endpoint(websocket):
        events.append("handler-called")
        await websocket.accept()

    async def receive():
        return {"type": "websocket.connect"}

    sent = []

    async def send(message):
        sent.append(message["type"])

    await app(
        {
            "type": "websocket",
            "path": "/ws",
            "headers": [],
        },
        receive,
        send,
    )

    assert events == ["handler-called"]
    assert sent


@pytest.mark.xfail(reason="HTTP2/TLS docs still overstate support compared with runtime reality")
def test_verified_http2_docs_match_runtime_support():
    with open("docs/HTTP2.md") as f:
        http2_docs = f.read().lower()

    with open("docs/TLS_SETUP.md") as f:
        tls_docs = f.read().lower()

    assert "includes http/2 support" not in http2_docs
    assert "automatically enabled when using tls" not in http2_docs
    assert "ssl_certfile" not in http2_docs
    assert "not yet available" in tls_docs
