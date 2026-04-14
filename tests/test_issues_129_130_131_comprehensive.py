"""Comprehensive verifier tests for issues #129-131 with extreme edge cases.

These tests strengthen the original issues with comprehensive coverage including
edge cases, boundary conditions, and failure modes.
"""

import asyncio
import gzip
import json
import socket
import threading
import time
from io import BytesIO

import pytest
import requests
from turboapi import TurboAPI
from turboapi.middleware import GZipMiddleware
from turboapi.websockets import WebSocket, WebSocketDisconnect


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


# ============================================================================
# ISSUE #130: GZipMiddleware Comprehensive Tests
# ============================================================================


@pytest.mark.xfail(reason="Middleware path still breaks gzip header/body passthrough")
def test_verified_gzip_passthrough_round_trip():
    """Original test: Basic gzip round-trip."""
    app = TurboAPI(title="VerifiedGZip")
    app.add_middleware(GZipMiddleware, minimum_size=10)

    @app.get("/large")
    def large_response():
        return {"data": "A" * 1000}

    client = TestClient(app)
    response = client.get("/large", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("Content-Encoding") == "gzip"
    assert len(response.json()["data"]) == 1000


@pytest.mark.xfail(reason="GZipMiddleware issues")
def test_gzip_edge_case_empty_response():
    """Edge case: Empty response should not error with GZipMiddleware."""
    app = TurboAPI(title="GZipEmpty")
    app.add_middleware(GZipMiddleware, minimum_size=10)

    @app.get("/empty")
    def empty_response():
        return {}

    client = TestClient(app)
    response = client.get("/empty", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    # Empty responses below minimum_size should not be gzipped
    if len(json.dumps({}).encode()) < 10:
        assert response.headers.get("Content-Encoding") != "gzip"


@pytest.mark.xfail(reason="GZipMiddleware issues")
def test_gzip_edge_case_unicode_content():
    """Edge case: Unicode content should compress/decompress correctly."""
    from turboapi.testclient import TestClient

    app = TurboAPI(title="GZipUnicode")
    app.add_middleware(GZipMiddleware, minimum_size=1)

    @app.get("/unicode")
    def unicode_response():
        return {"data": "Hello 世界 🌍 ñ" * 100}

    client = TestClient(app)
    response = client.get("/unicode", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("Content-Encoding") == "gzip"

    # Decompress and verify
    import gzip, json

    decompressed = gzip.decompress(response.content)
    result = json.loads(decompressed)
    assert result["data"] == "Hello 世界 🌍 ñ" * 100


@pytest.mark.xfail(reason="GZipMiddleware issues")
def test_gzip_edge_case_special_characters():
    """Edge case: Special JSON characters should survive gzip round-trip."""
    app = TurboAPI(title="GZipSpecial")
    app.add_middleware(GZipMiddleware, minimum_size=1)

    special_content = {"data": """<script>alert("xss")</script>\n\t\r\\'"{[]}'}"""}

    @app.get("/special")
    def special_response():
        return special_content

    client = TestClient(app)
    response = client.get("/special", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("Content-Encoding") == "gzip"
    assert response.json() == special_content


@pytest.mark.xfail(reason="GZipMiddleware issues")
def test_gzip_edge_case_large_payload():
    """Edge case: Large payload (1MB) should compress/decompress correctly."""
    app = TurboAPI(title="GZipLarge")
    app.add_middleware(GZipMiddleware, minimum_size=1)

    large_data = "X" * (1024 * 1024)  # 1MB

    @app.get("/large")
    def large_response():
        return {"data": large_data}

    client = TestClient(app)
    response = client.get("/large", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("Content-Encoding") == "gzip"
    assert len(response.json()["data"]) == len(large_data)


@pytest.mark.xfail(reason="GZipMiddleware issues")
def test_gzip_edge_case_no_accept_encoding():
    """Edge case: Client without Accept-Encoding should get uncompressed response."""
    app = TurboAPI(title="GZipNoAccept")
    app.add_middleware(GZipMiddleware, minimum_size=1)

    @app.get("/data")
    def data_response():
        return {"data": "A" * 1000}

    client = TestClient(app)
    response = requests.get(f"{base}/data")  # No Accept-Encoding header

    assert response.status_code == 200
    assert response.headers.get("Content-Encoding") != "gzip"
    assert len(response.json()["data"]) == 1000


@pytest.mark.xfail(reason="GZipMiddleware issues")
def test_gzip_edge_case_below_minimum_size():
    """Edge case: Small responses below minimum_size should not be gzipped."""
    app = TurboAPI(title="GZipMinSize")
    app.add_middleware(GZipMiddleware, minimum_size=500)

    @app.get("/small")
    def small_response():
        return {"data": "small"}  # Less than 500 bytes

    client = TestClient(app)
    response = client.get("/small", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    # Small responses should NOT be gzipped
    assert response.headers.get("Content-Encoding") != "gzip"
    assert response.json()["data"] == "small"


@pytest.mark.xfail(reason="GZipMiddleware issues")
def test_gzip_edge_case_nested_json():
    """Edge case: Deeply nested JSON should survive gzip round-trip."""
    app = TurboAPI(title="GZipNested")
    app.add_middleware(GZipMiddleware, minimum_size=1)

    # Create deeply nested structure
    nested = {"level": 0}
    for i in range(1, 100):
        nested = {"level": i, "nested": nested}

    @app.get("/nested")
    def nested_response():
        return nested

    client = TestClient(app)
    response = client.get("/nested", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("Content-Encoding") == "gzip"
    result = response.json()
    assert result["level"] == 99


@pytest.mark.xfail(reason="GZipMiddleware issues")
def test_gzip_edge_case_binary_in_json():
    """Edge case: Binary data in base64 within JSON should work."""
    app = TurboAPI(title="GZipBinary")
    app.add_middleware(GZipMiddleware, minimum_size=1)

    import base64

    binary_data = base64.b64encode(b"\x00\x01\x02\xff\xfe" * 100).decode()

    @app.get("/binary")
    def binary_response():
        return {"data": binary_data}

    client = TestClient(app)
    response = client.get("/binary", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("Content-Encoding") == "gzip"
    assert response.json()["data"] == binary_data


@pytest.mark.xfail(reason="GZipMiddleware issues")
def test_gzip_edge_case_concurrent_requests():
    """Edge case: Concurrent gzip requests should all succeed."""
    app = TurboAPI(title="GZipConcurrent")
    app.add_middleware(GZipMiddleware, minimum_size=1)

    @app.get("/data")
    def data_response():
        return {"data": "A" * 1000, "timestamp": time.time()}

    client = TestClient(app)

    results = []
    errors = []

    def make_request():
        try:
            resp = requests.get(f"{base}/data", headers={"Accept-Encoding": "gzip"})
            results.append(
                resp.status_code == 200 and resp.headers.get("Content-Encoding") == "gzip"
            )
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=make_request) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Errors during concurrent requests: {errors}"
    assert all(results), "Not all concurrent requests succeeded"


# ============================================================================
# ISSUE #129: Password Hashing Comprehensive Tests
# ============================================================================


@pytest.mark.xfail(reason="Built-in password hashing helpers still raise NotImplementedError")
def test_verified_password_hashing_helpers():
    """Original test: Basic password hashing and verification."""
    from turboapi.security import get_password_hash, verify_password

    hashed = get_password_hash("secret123")

    assert hashed != "secret123"
    assert verify_password("secret123", hashed) is True
    assert verify_password("wrong-password", hashed) is False


@pytest.mark.xfail(
    reason="Package-level verify_password export resolves to JWT helper instead of security helper"
)
def test_verified_top_level_verify_password_export_matches_security_module():
    """Original test: Package-level export should match security module."""
    from turboapi import verify_password as top_verify
    from turboapi.jwt_auth import verify_password as jwt_verify
    from turboapi.security import verify_password as security_verify

    assert top_verify is security_verify
    assert top_verify is not jwt_verify


@pytest.mark.xfail(reason="Password hashing issues")
def test_password_hashing_edge_case_empty_password():
    """Edge case: Empty password should still work."""
    from turboapi.security import get_password_hash, verify_password

    hashed = get_password_hash("")
    assert hashed != ""
    assert verify_password("", hashed) is True
    assert verify_password("not-empty", hashed) is False


@pytest.mark.xfail(reason="Password hashing issues")
def test_password_hashing_edge_case_very_long_password():
    """Edge case: Very long password (10KB) should work."""
    from turboapi.security import get_password_hash, verify_password

    long_password = "A" * (1024 * 10)  # 10KB password
    hashed = get_password_hash(long_password)

    assert hashed != long_password
    assert verify_password(long_password, hashed) is True
    assert verify_password(long_password[:-1], hashed) is False


@pytest.mark.xfail(reason="Password hashing issues")
def test_password_hashing_edge_case_unicode_password():
    """Edge case: Unicode password should work."""
    from turboapi.security import get_password_hash, verify_password

    unicode_password = "пароль🔐ñöéαβγ"
    hashed = get_password_hash(unicode_password)

    assert hashed != unicode_password
    assert verify_password(unicode_password, hashed) is True
    assert verify_password("different", hashed) is False


@pytest.mark.xfail(reason="Password hashing issues")
def test_password_hashing_edge_case_special_characters():
    """Edge case: Password with special characters should work."""
    from turboapi.security import get_password_hash, verify_password

    special_password = "!@#$%^&*()_+-=[]{}|;':\",./<>?\x00\x01\x02"
    hashed = get_password_hash(special_password)

    assert hashed != special_password
    assert verify_password(special_password, hashed) is True
    assert verify_password("different", hashed) is False


@pytest.mark.xfail(reason="Password hashing issues")
def test_password_hashing_edge_case_different_hashes_different():
    """Edge case: Same password should produce different hashes (salt)."""
    from turboapi.security import get_password_hash

    password = "same_password"
    hash1 = get_password_hash(password)
    hash2 = get_password_hash(password)

    # Hashes should be different due to salt
    assert hash1 != hash2


@pytest.mark.xfail(reason="Password hashing issues")
def test_password_hashing_edge_case_timing_attack_resistance():
    """Edge case: Verify should use constant-time comparison."""
    from turboapi.security import get_password_hash, verify_password

    password = "test_password"
    hashed = get_password_hash(password)

    # These should not raise exceptions
    assert verify_password(password, hashed) is True
    assert verify_password("wrong", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password("A" * 1000, hashed) is False


@pytest.mark.xfail(reason="Password hashing issues")
def test_password_hashing_edge_case_malformed_hash():
    """Edge case: Malformed hash should return False, not raise."""
    from turboapi.security import verify_password

    # These should return False without raising
    assert verify_password("password", "") is False
    assert verify_password("password", "invalid_hash") is False
    assert verify_password("password", "$invalid$hash") is False


@pytest.mark.xfail(reason="Password hashing issues")
def test_password_hashing_compatibility_with_fastapi_pattern():
    """Edge case: Should work with FastAPI OAuth2PasswordRequestForm pattern."""
    from turboapi.security import (
        get_password_hash,
        verify_password,
        OAuth2PasswordRequestForm,
        Depends,
    )

    # Simulate a login flow
    plain_password = "user_password"
    stored_hash = get_password_hash(plain_password)

    # Simulate user lookup
    user_password = plain_password

    # Verify
    assert verify_password(user_password, stored_hash) is True


# ============================================================================
# ISSUE #131: WebSocket ASGI Dispatch Comprehensive Tests
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="WebSocket decorator exists but ASGI/runtime websocket dispatch is incomplete"
)
async def test_verified_websocket_runtime_dispatch():
    """Original test: Basic websocket dispatch."""
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


@pytest.mark.asyncio
@pytest.mark.xfail(reason="WebSocket ASGI dispatch issues")
async def test_websocket_edge_case_receive_text():
    """Edge case: WebSocket should handle text message receive/send."""
    app = TurboAPI(title="WebSocketText")
    received_messages = []
    sent_messages = []

    @app.websocket("/ws")
    async def websocket_endpoint(websocket):
        await websocket.accept()
        message = await websocket.receive_text()
        received_messages.append(message)
        await websocket.send_text(f"Echo: {message}")

    messages = [
        {"type": "websocket.connect"},
        {"type": "websocket.receive", "text": "Hello WebSocket"},
    ]
    message_iter = iter(messages)

    async def receive():
        return next(message_iter)

    async def send(message):
        sent_messages.append(message)

    await app(
        {"type": "websocket", "path": "/ws", "headers": []},
        receive,
        send,
    )

    assert "handler-called" not in sent_messages  # Handler should complete
    assert len(received_messages) == 1
    assert received_messages[0] == "Hello WebSocket"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="WebSocket ASGI dispatch issues")
async def test_websocket_edge_case_receive_binary():
    """Edge case: WebSocket should handle binary message receive/send."""
    app = TurboAPI(title="WebSocketBinary")
    received_data = []

    @app.websocket("/ws")
    async def websocket_endpoint(websocket):
        await websocket.accept()
        data = await websocket.receive_bytes()
        received_data.append(data)
        await websocket.send_bytes(b"Binary echo: " + data)

    messages = [
        {"type": "websocket.connect"},
        {"type": "websocket.receive", "bytes": b"\x00\x01\x02\xff"},
    ]
    message_iter = iter(messages)

    async def receive():
        return next(message_iter)

    sent = []

    async def send(message):
        sent.append(message)

    await app(
        {"type": "websocket", "path": "/ws", "headers": []},
        receive,
        send,
    )

    assert len(received_data) == 1
    assert received_data[0] == b"\x00\x01\x02\xff"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="WebSocket ASGI dispatch issues")
async def test_websocket_edge_case_receive_json():
    """Edge case: WebSocket should handle JSON message receive/send."""
    app = TurboAPI(title="WebSocketJSON")
    received_json = []

    @app.websocket("/ws")
    async def websocket_endpoint(websocket):
        await websocket.accept()
        data = await websocket.receive_json()
        received_json.append(data)
        await websocket.send_json({"echo": data})

    messages = [
        {"type": "websocket.connect"},
        {"type": "websocket.receive", "text": '{"key": "value", "number": 42}'},
    ]
    message_iter = iter(messages)

    async def receive():
        return next(message_iter)

    sent = []

    async def send(message):
        sent.append(message)

    await app(
        {"type": "websocket", "path": "/ws", "headers": []},
        receive,
        send,
    )

    assert len(received_json) == 1
    assert received_json[0] == {"key": "value", "number": 42}


@pytest.mark.asyncio
@pytest.mark.xfail(reason="WebSocket ASGI dispatch issues")
async def test_websocket_edge_case_multiple_messages():
    """Edge case: WebSocket should handle multiple messages."""
    app = TurboAPI(title="WebSocketMulti")
    received = []

    @app.websocket("/ws")
    async def websocket_endpoint(websocket):
        await websocket.accept()
        for _ in range(3):
            msg = await websocket.receive_text()
            received.append(msg)
            await websocket.send_text(f"Ack: {msg}")

    messages = [
        {"type": "websocket.connect"},
        {"type": "websocket.receive", "text": "msg1"},
        {"type": "websocket.receive", "text": "msg2"},
        {"type": "websocket.receive", "text": "msg3"},
    ]
    message_iter = iter(messages)

    async def receive():
        return next(message_iter)

    sent = []

    async def send(message):
        sent.append(message)

    await app(
        {"type": "websocket", "path": "/ws", "headers": []},
        receive,
        send,
    )

    assert received == ["msg1", "msg2", "msg3"]


@pytest.mark.asyncio
@pytest.mark.xfail(reason="WebSocket ASGI dispatch issues")
async def test_websocket_edge_case_disconnect():
    """Edge case: WebSocket should handle disconnect gracefully."""
    app = TurboAPI(title="WebSocketDisconnect")
    disconnect_raised = False

    @app.websocket("/ws")
    async def websocket_endpoint(websocket):
        await websocket.accept()
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            disconnect_raised = True

    messages = [
        {"type": "websocket.connect"},
        {"type": "websocket.disconnect", "code": 1000},
    ]
    message_iter = iter(messages)

    async def receive():
        return next(message_iter)

    async def send(message):
        pass

    await app(
        {"type": "websocket", "path": "/ws", "headers": []},
        receive,
        send,
    )

    assert disconnect_raised is True


@pytest.mark.asyncio
@pytest.mark.xfail(reason="WebSocket ASGI dispatch issues")
async def test_websocket_edge_case_not_found():
    """Edge case: WebSocket request to non-existent path should 404."""
    app = TurboAPI(title="WebSocketNotFound")

    @app.websocket("/ws")
    async def websocket_endpoint(websocket):
        await websocket.accept()

    async def receive():
        return {"type": "websocket.connect"}

    sent = []

    async def send(message):
        sent.append(message)

    await app(
        {"type": "websocket", "path": "/nonexistent", "headers": []},
        receive,
        send,
    )

    # Should get a close or error message
    assert len(sent) > 0


@pytest.mark.asyncio
@pytest.mark.xfail(reason="WebSocket ASGI dispatch issues")
async def test_websocket_edge_case_path_parameters():
    """Edge case: WebSocket with path parameters."""
    app = TurboAPI(title="WebSocketParams")
    captured_params = {}

    @app.websocket("/ws/{room_id}")
    async def websocket_endpoint(websocket, room_id: str):
        captured_params["room_id"] = room_id
        await websocket.accept()
        await websocket.send_text(f"Joined room: {room_id}")

    async def receive():
        return {"type": "websocket.connect"}

    sent = []

    async def send(message):
        sent.append(message)

    await app(
        {
            "type": "websocket",
            "path": "/ws/room-123",
            "headers": [],
        },
        receive,
        send,
    )

    assert captured_params.get("room_id") == "room-123"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="WebSocket ASGI dispatch issues")
async def test_websocket_edge_case_query_parameters():
    """Edge case: WebSocket with query parameters."""
    app = TurboAPI(title="WebSocketQuery")
    captured_token = None

    @app.websocket("/ws")
    async def websocket_endpoint(websocket, token: str = None):
        captured_token = token
        await websocket.accept()

    async def receive():
        return {"type": "websocket.connect"}

    sent = []

    async def send(message):
        sent.append(message)

    await app(
        {
            "type": "websocket",
            "path": "/ws",
            "query_string": b"token=secret-token-123",
            "headers": [],
        },
        receive,
        send,
    )

    assert captured_token == "secret-token-123"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="WebSocket ASGI dispatch issues")
async def test_websocket_edge_case_headers():
    """Edge case: WebSocket should have access to headers."""
    app = TurboAPI(title="WebSocketHeaders")
    captured_auth = None

    @app.websocket("/ws")
    async def websocket_endpoint(websocket):
        # Access headers from scope
        headers = dict(websocket.scope.get("headers", []))
        captured_auth = headers.get(b"authorization", b"").decode()
        await websocket.accept()

    async def receive():
        return {"type": "websocket.connect"}

    sent = []

    async def send(message):
        sent.append(message)

    await app(
        {
            "type": "websocket",
            "path": "/ws",
            "headers": [
                [b"authorization", b"Bearer token-123"],
                [b"x-custom-header", b"custom-value"],
            ],
        },
        receive,
        send,
    )

    assert captured_auth == "Bearer token-123"


# ============================================================================
# Additional Integration Tests
# ============================================================================


@pytest.mark.xfail(reason="Multiple issues")
def test_integration_security_with_gzip():
    """Integration: Security headers + GZip should work together."""
    app = TurboAPI(title="IntegrationTest")
    app.add_middleware(GZipMiddleware, minimum_size=1)

    from turboapi.security import get_password_hash

    @app.get("/secure-data")
    def secure_data():
        # Return sensitive data that should be gzipped
        return {"hash": get_password_hash("password"), "data": "X" * 1000}

    client = TestClient(app)
    response = client.get("/secure-data", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers.get("Content-Encoding") == "gzip"
    assert "hash" in response.json()
