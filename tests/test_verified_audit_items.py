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
    Issue #97: Implicit header-name mapping must populate plain handler params on Zig runtime.

    FastAPI maps snake_case param names to hyphenated HTTP headers:
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
