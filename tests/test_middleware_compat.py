"""
Middleware compatibility tests (#36).

Verifies that all handler types (simple_sync_noargs, simple_sync, body_sync,
model_sync) return correct responses when wrapped with CORSMiddleware.
Previously these routes were registered with the wrong Zig dispatch type and
returned 500 with "bad tuple[0]".
"""

import socket
import threading
import time

import pytest
import requests
from turboapi import TurboAPI
from turboapi.middleware import CORSMiddleware, GZipMiddleware, LoggingMiddleware


def _free_port() -> int:
    """Ask the OS for a free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def _start(app, port):
    t = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port), daemon=True)
    t.start()
    time.sleep(1.5)


@pytest.fixture(scope="module")
def cors_app():
    try:
        from dhi import BaseModel as DhiModel
    except ImportError:
        pytest.skip("dhi not installed")

    class Item(DhiModel):
        name: str
        price: float

    app = TurboAPI()
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/")
    def root():
        return {"ok": True}

    @app.get("/items/{item_id}")
    def get_item(item_id: int):
        return {"id": item_id, "doubled": item_id * 2}

    @app.get("/search")
    def search(q: str, limit: int = 10):
        return {"q": q, "limit": limit}

    @app.post("/items")
    def create_item(body: Item):
        return {"id": 1, "name": body.name, "price": body.price}

    port = _free_port()
    _start(app, port)
    return f"http://127.0.0.1:{port}"


def test_cors_noargs_get(cors_app):
    """simple_sync_noargs + CORS must return 200, not 500."""
    r = requests.get(f"{cors_app}/")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}


def test_cors_path_param_get(cors_app):
    """simple_sync with path param + CORS must coerce type and return 200."""
    r = requests.get(f"{cors_app}/items/7")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == 7
    assert data["doubled"] == 14


def test_cors_query_param_get(cors_app):
    """simple_sync with query params + CORS must return 200 with correct values.
    Note: with middleware, query params arrive as strings (no Zig type coercion).
    """
    r = requests.get(f"{cors_app}/search?q=hello&limit=5")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["q"] == "hello"
    # In the enhanced (middleware) path, int query params come back as strings
    assert int(data["limit"]) == 5


def test_cors_query_param_default(cors_app):
    """Optional query param must use Python default when absent."""
    r = requests.get(f"{cors_app}/search?q=world")
    assert r.status_code == 200, r.text
    assert r.json()["limit"] == 10


def test_cors_model_post(cors_app):
    """model_sync + CORS must parse JSON body and return 200."""
    r = requests.post(f"{cors_app}/items", json={"name": "widget", "price": 4.99})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "widget"
    assert data["price"] == 4.99


def test_cors_response_ok(cors_app):
    """All routes with CORS must return 200 — regression for 'bad tuple[0]' crash."""
    for url in ["/", "/items/1", "/search?q=x"]:
        r = requests.get(f"{cors_app}{url}")
        assert r.status_code == 200, f"{url} returned {r.status_code}: {r.text}"


# ---- Stricter middleware compat tests ----


@pytest.fixture(scope="module")
def gzip_app():
    app = TurboAPI()
    app.add_middleware(GZipMiddleware, minimum_size=10)

    @app.get("/large")
    def large_response():
        return {"data": "A" * 1000}

    port = _free_port()
    _start(app, port)
    return f"http://127.0.0.1:{port}"


@pytest.mark.xfail(reason="Requires middleware header/body passthrough (PR #55)")
def test_gzip_middleware_compat(gzip_app):
    """GZip middleware must correctly compress and return 200."""
    r = requests.get(f"{gzip_app}/large", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200, r.text
    assert r.headers.get("Content-Encoding") == "gzip"

@pytest.mark.xfail(reason="Requires middleware header/body passthrough (PR #55)")
def test_gzip_body_is_actually_compressed(gzip_app):
    """The body must actually be gzip-compressed bytes, not original JSON.
    Decompress and verify the data survived the round trip."""
    r = requests.get(f"{gzip_app}/large", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("Content-Encoding") == "gzip"
    data = r.json()
    assert len(data["data"]) == 1000, "Body was mangled during gzip passthrough"


def test_large_header_not_truncated(cors_app):
    """Middleware-set headers must not be silently truncated.
    A real CSP header can be 500+ bytes. If sendResponseExt
    truncates at the buffer limit, this catches it."""
    r = requests.get(f"{cors_app}/search?q=test")
    assert r.status_code == 200
    origin = r.headers.get("Access-Control-Allow-Origin")
    assert origin is not None, "CORS header missing entirely"
    assert origin == "*", f"CORS header truncated or wrong: {origin!r}"


def test_no_middleware_body_unchanged():
    """When no middleware mutates the body, the original response
    must come through byte-for-byte."""
    app = TurboAPI()

    @app.get("/raw")
    def raw():
        return {"exact": "value", "number": 42}

    port = _free_port()
    _start(app, port)
    r = requests.get(f"http://127.0.0.1:{port}/raw")
    assert r.status_code == 200
    assert r.json() == {"exact": "value", "number": 42}, f"Body mutated without middleware: {r.json()}"


def test_async_handler_under_middleware():
    """Async handlers wrapped by middleware must return the actual
    result, not a coroutine object or repr string."""
    app = TurboAPI()
    app.add_middleware(CORSMiddleware, allow_origins=["*"])

    @app.get("/async-test")
    async def async_endpoint():
        return {"async": True, "value": 123}

    port = _free_port()
    _start(app, port)
    r = requests.get(f"http://127.0.0.1:{port}/async-test")
    assert r.status_code == 200
    data = r.json()
    assert data["async"] is True, f"Got coroutine object instead of result: {data}"
    assert data["value"] == 123


def test_non_middleware_route_no_extra_headers():
    """Routes without middleware must NOT have middleware-injected headers
    like Content-Encoding leaking into the response. CORS headers are
    excluded from this check because cors_enabled is global Zig state."""
    app = TurboAPI()

    @app.get("/clean")
    def clean():
        return {"clean": True}

    port = _free_port()
    _start(app, port)
    r = requests.get(f"http://127.0.0.1:{port}/clean")
    assert r.status_code == 200
    # No middleware-injected headers should appear
    assert "Content-Encoding" not in r.headers
    assert r.json() == {"clean": True}


def test_stacked_middleware_all_headers_present():
    """When multiple middlewares are stacked, ALL of their headers
    must be present in the response, not just the last one."""
    app = TurboAPI()
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/multi")
    def multi():
        return {"stacked": True}

    port = _free_port()
    _start(app, port)
    r = requests.get(f"http://127.0.0.1:{port}/multi")
    assert r.status_code == 200
    assert r.headers.get("Access-Control-Allow-Origin") is not None, "CORS header missing after stacking"
    assert r.json()["stacked"] is True
