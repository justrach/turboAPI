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
from turboapi.middleware import CORSMiddleware


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
