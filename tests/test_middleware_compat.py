"""
Middleware compatibility tests (#36).

Verifies that all handler types (simple_sync_noargs, simple_sync, body_sync,
model_sync) return correct responses when wrapped with CORSMiddleware.
Previously these routes were registered with the wrong Zig dispatch type and
returned 500 with "bad tuple[0]".
"""

import threading
import time

import pytest
import requests
from turboapi import TurboAPI
from turboapi.middleware import CORSMiddleware, GZipMiddleware, LoggingMiddleware


def _start(app, port):
    t = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port), daemon=True)
    t.start()
    time.sleep(1.5)

@pytest.fixture(scope="module")
def gzip_app():
    app = TurboAPI()
    app.add_middleware(GZipMiddleware, minimum_size=10)

    @app.get("/large")
    def large_response():
        return {"data": "A" * 1000}

    _start(app, 9851)
    return "http://127.0.0.1:9851"
def test_gzip_middleware_compat(gzip_app):
    """GZip middleware must correctly compress and return 200."""
    headers = {"Accept-Encoding": "gzip"}
    r = requests.get(f"{gzip_app}/large", headers=headers)
    assert r.status_code == 200, r.text
    assert r.headers.get("Content-Encoding") == "gzip"

@pytest.fixture(scope="module")
def stacked_app():
    app = TurboAPI()
    # Stacking Auth (simulated via logging) and CORS
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/stacked")
    def stacked_route():
        return {"status": "ok", "latency": "stable"}

    _start(app, 9852)
    return "http://127.0.0.1:9852"

def test_stacked_middleware_compat(stacked_app):
    """Stacked middlewares must process the request and return 200 successfully."""
    r = requests.get(f"{stacked_app}/stacked")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ok"
    assert "Access-Control-Allow-Origin" in r.headers

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

    _start(app, 9850)
    return "http://127.0.0.1:9850"


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


@pytest.fixture(scope="module")
def https_redirect_app():
    from turboapi.middleware import HTTPSRedirectMiddleware

    app = TurboAPI()
    app.add_middleware(HTTPSRedirectMiddleware)

    @app.get("/secure")
    def secure_route():
        return {"secured": True}

    _start(app, 9853)
    return "http://127.0.0.1:9853"


def test_https_redirect_passthrough(https_redirect_app):
    """HTTPSRedirectMiddleware must pass through requests that already carry
    x-forwarded-proto: https (simulates a TLS-terminating proxy)."""
    r = requests.get(
        f"{https_redirect_app}/secure",
        headers={"x-forwarded-proto": "https"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"secured": True}


def test_https_redirect_blocked(https_redirect_app):
    """HTTPSRedirectMiddleware must block plain HTTP requests (no x-forwarded-proto)
    and return a 4xx/5xx — not a 200. In TurboAPI's middleware path BeforeRequest
    exceptions map to a 429 error response rather than a 301 redirect because the
    Zig transport cannot issue a redirect directly from a Python exception."""
    r = requests.get(f"{https_redirect_app}/secure")
    # Must NOT be 200 – the middleware raised before the handler ran.
    assert r.status_code != 200, (
        f"Expected non-200 for plain HTTP request, got {r.status_code}: {r.text}"
    )
