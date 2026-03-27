"""
Exact repro tests for issues #96, #97, and #98.

Each test is self-contained, starts its own server on a random port,
and is the sole acceptance criterion for the corresponding issue.
"""

import socket
import threading
import time

import requests


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(app, port, timeout: float = 2.5):
    t = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port), daemon=True)
    t.start()
    time.sleep(timeout)


def test_verified_gzip_passthrough_round_trip():
    """Issue #96 repro."""
    import os

    os.environ["TURBO_DISABLE_CACHE"] = "1"

    from turboapi import TurboAPI
    from turboapi.middleware import GZipMiddleware

    app = TurboAPI(title="GZip test")
    app.add_middleware(GZipMiddleware, minimum_size=10)

    @app.get("/large")
    def large_response():
        return {"data": "A" * 1000}

    port = _free_port()
    _start(app, port)

    r = requests.get(
        f"http://127.0.0.1:{port}/large",
        headers={"Accept-Encoding": "gzip"},
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("Content-Encoding") == "gzip", (
        f"Expected Content-Encoding: gzip, got headers: {dict(r.headers)}"
    )
    data = r.json()
    assert len(data["data"]) == 1000


def test_verified_implicit_header_extraction():
    """Issue #97 repro."""
    import os

    os.environ["TURBO_DISABLE_CACHE"] = "1"

    from turboapi import TurboAPI
    from turboapi.middleware import LoggingMiddleware

    app = TurboAPI(title="Header test")
    app.add_middleware(LoggingMiddleware)

    @app.get("/implicit-headers")
    def implicit_headers(authorization: str = "missing", x_request_id: str = "missing"):
        return {"authorization": authorization, "request_id": x_request_id}

    port = _free_port()
    _start(app, port)

    r = requests.get(
        f"http://127.0.0.1:{port}/implicit-headers",
        headers={"Authorization": "Bearer token123", "X-Request-ID": "req-42"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"authorization": "Bearer token123", "request_id": "req-42"}, (
        f"Implicit header extraction failed: {body}"
    )


def test_verified_password_hashing_helpers():
    """Issue #98 repro."""
    from turboapi.security import get_password_hash, verify_password

    password = "correct-horse-battery-staple"
    hashed = get_password_hash(password)

    assert isinstance(hashed, str) and hashed
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrong-password", hashed) is False

    hashed2 = get_password_hash(password)
    assert hashed != hashed2
    assert verify_password(password, hashed2) is True
    assert verify_password("bad", hashed2) is False
