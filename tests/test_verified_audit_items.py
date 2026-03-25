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


# ── Issue #96 — GZipMiddleware + Zig runtime: Content-Encoding header ────────


def test_verified_gzip_passthrough_round_trip():
    """
    GZipMiddleware must:
    1. Set Content-Encoding: gzip on responses larger than minimum_size.
    2. Return a body that decompresses to the original JSON payload.

    Repro for https://github.com/justrach/turboAPI/issues/96
    """
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
    # requests auto-decompresses; verify round-trip integrity
    data = r.json()
    assert len(data["data"]) == 1000, "Body was mangled during gzip round-trip"


# ── Issue #97 — Implicit header-name mapping for plain handler params ─────────


def test_verified_implicit_header_extraction():
    """
    Plain handler params such as `authorization` and `x_request_id` must be
    populated from request headers via underscore-to-dash name mapping,
    without requiring explicit Header() markers.

    Uses LoggingMiddleware to route through the enhanced handler path (the path
    that passes the full headers dict to Python). CORSMiddleware is excluded
    because the Zig runtime intercepts it natively and leaves _middleware_instances
    empty, keeping the handler on the vectorcall path that only receives
    path/query params.

    Repro for https://github.com/justrach/turboAPI/issues/97
    """
    import os

    os.environ["TURBO_DISABLE_CACHE"] = "1"

    from turboapi import TurboAPI
    from turboapi.middleware import LoggingMiddleware

    app = TurboAPI(title="Header test")
    # LoggingMiddleware is instantiated in _middleware_instances (not intercepted by
    # Zig native), which forces the handler to use the enhanced (dict-kwargs) path
    # that passes the full headers dict to Python.
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
# ── Issue #98 — Built-in password hashing helpers ────────────────────────────


def test_verified_password_hashing_helpers():
    """
    turboapi.security.get_password_hash / verify_password must work out of the
    box without raising NotImplementedError.

    Repro for https://github.com/justrach/turboAPI/issues/98
    """
    from turboapi import get_password_hash, verify_password_hash

    password = "correct-horse-battery-staple"
    hashed = get_password_hash(password)

    # Hash must be a non-empty string and must not be the plaintext password
    assert isinstance(hashed, str) and hashed, "get_password_hash returned empty string"
    assert hashed != password, "get_password_hash returned plaintext — no hashing performed"

    # Correct password must verify
    assert verify_password_hash(password, hashed) is True, (
        "verify_password returned False for the correct password"
    )

    # Wrong password must not verify
    assert verify_password_hash("wrong-password", hashed) is False, (
        "verify_password returned True for a wrong password"
    )

    # Two hashes of the same password must differ (random salt)
    hashed2 = get_password_hash(password)
    assert hashed != hashed2, "get_password_hash produced identical hashes (missing random salt)"

    # Cross-verify: each hash must only accept its own password
    assert verify_password_hash(password, hashed2) is True
    assert verify_password_hash("bad", hashed2) is False
