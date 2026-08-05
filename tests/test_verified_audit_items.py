"""
Verified audit items — regression tests for issues resolved in the audit.
"""

import os
import random
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))

try:
    import requests
except ImportError:
    requests = None


def test_verified_password_hashing_helpers():
    """Issue #98: get_password_hash and verify_password must be functional."""
    from turboapi.security import get_password_hash, verify_password

    hashed = get_password_hash("mysecret")
    assert hashed != "mysecret", "must not return plaintext"
    assert verify_password("mysecret", hashed) is True
    assert verify_password("wrongpassword", hashed) is False


def _free_port():
    return random.randint(19600, 19699)


def test_verified_implicit_header_extraction():
    """
    Issue #132: TurboAPI extension for implicit header-name mapping on Zig runtime.

    This is intentionally beyond FastAPI's plain-string parameter behavior:
      authorization  -> Authorization
      x_request_id   -> X-Request-ID
    """
    if requests is None:
        import pytest

        pytest.skip("requests not installed")

    from turboapi import TurboAPI

    port = _free_port()
    app = TurboAPI(title="Implicit Header Test")

    @app.get("/headers")
    def read_headers(
        authorization: str = "missing",
        x_request_id: str = "missing",
    ):
        return {"authorization": authorization, "request_id": x_request_id}

    def start_server():
        app.run(host="127.0.0.1", port=port)

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    r = requests.get(
        f"http://127.0.0.1:{port}/headers",
        headers={"Authorization": "Bearer token123", "X-Request-ID": "req-42"},
    )
    assert r.status_code == 200, f"Unexpected status: {r.status_code}\n{r.text}"
    body = r.json()
    assert body == {"authorization": "Bearer token123", "request_id": "req-42"}, (
        f"Implicit header mapping failed: {body}"
    )


def test_verified_async_dependency_in_async_handler():
    """
    Async handlers must resolve async (coroutine) dependencies on the running
    event loop. The sync resolver used asyncio.run(), which raises
    RuntimeError inside a running loop and turned every async dependency
    into a 500.
    """
    if requests is None:
        import pytest

        pytest.skip("requests not installed")

    from turboapi import TurboAPI
    from turboapi.security import Depends

    port = _free_port()
    app = TurboAPI(title="Async Dependency Test")

    async def get_settings():
        return {"env": "test"}

    @app.get("/settings")
    async def read_settings(settings=Depends(get_settings)):
        return {"env": settings["env"]}

    def start_server():
        app.run(host="127.0.0.1", port=port)

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    r = requests.get(f"http://127.0.0.1:{port}/settings")
    assert r.status_code == 200, f"Unexpected status: {r.status_code}\n{r.text}"
    assert r.json() == {"env": "test"}, f"Async dependency not resolved: {r.text}"


def test_verified_async_handler_streaming_response():
    """
    An async handler returning a StreamingResponse must be collected on the
    running event loop. The sync collector's asyncio.run() raises inside a
    running loop and turned async streaming responses into a 500.
    """
    if requests is None:
        import pytest

        pytest.skip("requests not installed")

    from turboapi import TurboAPI
    from turboapi.responses import StreamingResponse

    port = _free_port()
    app = TurboAPI(title="Async Streaming Test")

    @app.get("/events")
    async def events():
        async def generate():
            for i in range(3):
                yield f"data: {i}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    def start_server():
        app.run(host="127.0.0.1", port=port)

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    r = requests.get(f"http://127.0.0.1:{port}/events")
    assert r.status_code == 200, f"Unexpected status: {r.status_code}\n{r.text}"
    assert "data: 0" in r.text and "data: 2" in r.text, f"Bad stream body: {r.text!r}"


def test_verified_fast_path_param_coercion_is_400_not_500():
    """
    Type coercion of path/query params in the fast path: invalid client input
    (e.g. ?page=abc for an int param) must be a 400, not an unhandled 500;
    valid query values must arrive coerced (int, not str).
    """
    if requests is None:
        import pytest

        pytest.skip("requests not installed")

    from turboapi import TurboAPI

    port = _free_port()
    app = TurboAPI(title="Coercion Test")

    @app.get("/items/{item_id}")
    def read_item(item_id: int, page: int = 1):
        return {"item_id": item_id, "page": page, "page_type": type(page).__name__}

    def start_server():
        app.run(host="127.0.0.1", port=port)

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    r = requests.get(f"http://127.0.0.1:{port}/items/42", params={"page": "2"})
    assert r.status_code == 200, f"Unexpected status: {r.status_code}\n{r.text}"
    assert r.json() == {"item_id": 42, "page": 2, "page_type": "int"}, r.text

    r = requests.get(f"http://127.0.0.1:{port}/items/42", params={"page": "abc"})
    assert r.status_code == 400, f"Expected 400 for bad query value, got {r.status_code}: {r.text}"

    r = requests.get(f"http://127.0.0.1:{port}/items/notanint")
    assert r.status_code in (400, 404), (
        f"Expected 400/404 for bad path value, got {r.status_code}: {r.text}"
    )


def test_verified_dependency_cleanup_runs_on_handler_exception():
    """
    Generator dependencies must teardown even when the handler raises —
    previously the cleanup block sat after the handler call on the success
    path only, leaking DB sessions on every failing request.
    """
    if requests is None:
        import pytest

        pytest.skip("requests not installed")

    from turboapi import TurboAPI
    from turboapi.security import Depends

    port = _free_port()
    app = TurboAPI(title="Dep Cleanup Test")
    events = []

    def get_session():
        events.append("open")
        try:
            yield {"db": True}
        finally:
            events.append("closed")

    @app.get("/fail")
    def failing(session=Depends(get_session)):
        raise ValueError("boom")

    def start_server():
        app.run(host="127.0.0.1", port=port)

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    r = requests.get(f"http://127.0.0.1:{port}/fail")
    assert r.status_code == 500, f"Unexpected status: {r.status_code}\n{r.text}"
    assert events == ["open", "closed"], f"Dependency teardown did not run: {events}"


def test_verified_header_cannot_override_path_param():
    """
    Implicit header mapping (Issue #132) must not override a path/query param
    that was already extracted and type-coerced: a client "user-id" header
    must never replace the {user_id} path value.
    """
    if requests is None:
        import pytest

        pytest.skip("requests not installed")

    from turboapi import TurboAPI

    port = _free_port()
    app = TurboAPI(title="Header Override Test")

    @app.get("/users/{user_id}")
    def get_user(user_id: int):
        return {"user_id": user_id, "type": type(user_id).__name__}

    def start_server():
        app.run(host="127.0.0.1", port=port)

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    r = requests.get(
        f"http://127.0.0.1:{port}/users/123",
        headers={"User-Id": "0"},
    )
    assert r.status_code == 200, f"Unexpected status: {r.status_code}\n{r.text}"
    body = r.json()
    assert body == {"user_id": 123, "type": "int"}, (
        f"Header overrode path param (or broke its type): {body}"
    )


def test_verified_gzip_passthrough_round_trip():
    """
    Issue #96: GZipMiddleware on Zig runtime must set Content-Encoding: gzip
    and return a correctly compressed body.
    """
    if requests is None:
        import pytest

        pytest.skip("requests not installed")

    from turboapi import TurboAPI
    from turboapi.middleware import GZipMiddleware

    port = _free_port()
    app = TurboAPI(title="GZip Test")
    app.add_middleware(GZipMiddleware, minimum_size=10)

    payload = {"data": "A" * 1000}

    @app.get("/large")
    def large_response():
        return payload

    def start_server():
        app.run(host="127.0.0.1", port=port)

    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    # requests decompresses gzip automatically; disable to inspect raw header
    r = requests.get(
        f"http://127.0.0.1:{port}/large",
        headers={"Accept-Encoding": "gzip"},
        stream=True,
    )
    assert r.status_code == 200, f"Unexpected status: {r.status_code}\n{r.text}"
    assert r.headers.get("Content-Encoding") == "gzip", (
        f"Expected Content-Encoding: gzip, got: {r.headers}"
    )
    # Decompress and verify round-trip integrity
    data = r.json()
    assert data["data"] == "A" * 1000, f"Body was mangled: {data}"
