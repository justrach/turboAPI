#!/usr/bin/env python3
"""
Unit tests for perf/noargs-callnoargs and perf/tuple-response-abi.

- noargs-callnoargs: zero-param handlers are classified as "simple_sync_noargs"
  and called via PyObject_CallNoArgs in Zig.
- tuple-response-abi: fast handlers return (status_code, content_type, body_str)
  3-tuples instead of dicts — eliminates 3x PyDict_GetItemString per response.
"""

import sys
import threading
import time

import pytest
import requests

sys.path.insert(0, "python")

from dhi import BaseModel
from turboapi import TurboAPI
from turboapi.request_handler import create_fast_handler, create_fast_model_handler
from turboapi.zig_integration import classify_handler

# ── Fixtures ─────────────────────────────────────────────────────────────────


class FakeRoute:
    """Minimal stand-in for a route definition used in classify_handler."""

    def __init__(self, method: str = "GET", path: str = "/"):
        class _Method:
            def __init__(self, v):
                self.value = v

        self.method = _Method(method)
        self.path = path


# ── classify_handler: noargs → simple_sync_noargs ────────────────────────────


def test_classify_noargs_get():
    """Zero-param GET handler → simple_sync_noargs (PyObject_CallNoArgs path)."""

    def handler():
        return {"ok": True}

    ht, param_types, model_info = classify_handler(handler, FakeRoute("GET"))
    assert ht == "simple_sync_noargs", f"expected simple_sync_noargs, got {ht}"
    assert param_types == {}
    assert model_info == {}


def test_classify_simple_sync_with_path_param():
    """GET handler with path param → simple_sync (not noargs)."""

    def handler(item_id: str):
        return {"item_id": item_id}

    ht, _, _ = classify_handler(handler, FakeRoute("GET"))
    assert ht == "simple_sync"


def test_classify_body_sync_post_no_model():
    """POST handler without body model → body_sync."""

    def handler(name: str):
        return {"name": name}

    ht, _, _ = classify_handler(handler, FakeRoute("POST"))
    assert ht == "body_sync"


# ── Tuple ABI: create_fast_handler returns 3-tuples ──────────────────────────


def test_fast_handler_returns_tuple_dict_result():
    """fast_handler returns (200, 'application/json', json_str) for dict result."""

    def handler():
        return {"hello": "world"}

    route = FakeRoute("GET")
    h = create_fast_handler(handler, route)
    result = h(path_params={})

    assert isinstance(result, tuple), f"expected tuple, got {type(result)}"
    assert len(result) == 3
    status, ct, body = result
    assert status == 200
    assert ct == "application/json"
    assert '"hello"' in body


def test_fast_handler_returns_tuple_for_noargs():
    """Zero-arg handler's fast_handler_noargs also returns 3-tuple."""

    def handler():
        return {"ping": True}

    route = FakeRoute("GET")
    h = create_fast_handler(handler, route)
    result = h()  # called with no kwargs (noargs path)

    assert isinstance(result, tuple) and len(result) == 3
    assert result[0] == 200
    assert "ping" in result[2]


def test_fast_handler_returns_tuple_with_path_param():
    """simple_sync handler returns 3-tuple with path params resolved."""

    def handler(item_id: str):
        return {"item_id": item_id}

    route = FakeRoute("GET", "/items/{item_id}")
    h = create_fast_handler(handler, route)
    result = h(path_params={"item_id": "42"}, query_string="")

    assert result[0] == 200
    import json

    data = json.loads(result[2])
    assert data["item_id"] == "42"


def test_fast_handler_returns_tuple_with_int_path_param():
    """Path param with int annotation is correctly converted."""

    def handler(item_id: int):
        return {"item_id": item_id, "type": type(item_id).__name__}

    route = FakeRoute("GET", "/items/{item_id}")
    h = create_fast_handler(handler, route)
    result = h(path_params={"item_id": "7"}, query_string="")

    import json

    data = json.loads(result[2])
    assert data["item_id"] == 7
    assert data["type"] == "int"


def test_fast_handler_http_exception_returns_tuple():
    """HTTPException inside handler is caught and returned as tuple."""
    from turboapi.exceptions import HTTPException

    def handler():
        raise HTTPException(status_code=404, detail="not found")

    route = FakeRoute("GET")
    h = create_fast_handler(handler, route)
    result = h(path_params={})

    assert result[0] == 404
    import json

    data = json.loads(result[2])
    assert data["detail"] == "not found"


def test_fast_handler_exception_returns_500_tuple():
    """Uncaught exception inside handler returns (500, ...) tuple."""

    def handler():
        raise RuntimeError("boom")

    route = FakeRoute("GET")
    h = create_fast_handler(handler, route)
    result = h(path_params={})

    assert result[0] == 500
    import json

    data = json.loads(result[2])
    assert "boom" in data["error"]


# ── Tuple ABI: create_fast_model_handler returns 3-tuples ────────────────────


class Widget(BaseModel):
    name: str
    price: float


def test_fast_model_handler_returns_tuple():
    """create_fast_model_handler wraps model handler and returns 3-tuple."""

    def handler(widget: Widget):
        return {"name": widget.name, "price": widget.price}

    h = create_fast_model_handler(handler, Widget, "widget")
    result = h(body_dict={"name": "gadget", "price": 4.99}, path_params={})

    assert isinstance(result, tuple) and len(result) == 3
    assert result[0] == 200
    import json

    data = json.loads(result[2])
    assert data["name"] == "gadget"
    assert data["price"] == 4.99


def test_fast_model_handler_invalid_model_returns_500():
    """Missing required field in body_dict returns (500, ...) tuple."""

    def handler(widget: Widget):
        return widget.model_dump()

    h = create_fast_model_handler(handler, Widget, "widget")
    result = h(body_dict={"name": "gadget"}, path_params={})  # missing price

    assert result[0] == 500  # validation error → 500


def test_fast_model_handler_empty_body_returns_400():
    """Empty body returns 400 from fast_model_handler."""

    def handler(widget: Widget):
        return widget.model_dump()

    h = create_fast_model_handler(handler, Widget, "widget")
    result = h(path_params={})  # no body_dict, no body

    assert result[0] == 400


# ── End-to-end: live server tests ────────────────────────────────────────────

PORT = 9987


@pytest.fixture(scope="module")
def server():
    app = TurboAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.get("/hello")
    def hello():
        return {"message": "hello"}

    @app.get("/items/{item_id}")
    def get_item(item_id: str):
        return {"item_id": item_id}

    @app.get("/typed/{n}")
    def typed(n: int):
        return {"n": n, "doubled": n * 2}

    class Item(BaseModel):
        name: str
        price: float

    @app.post("/items")
    def create_item(item: Item):
        return {"name": item.name, "price": item.price, "created": True}

    def run():
        app.run(host="127.0.0.1", port=PORT)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(1.5)
    yield
    # daemon thread exits when test process ends


def test_e2e_noargs_get(server):
    """simple_sync_noargs route returns correct JSON via live server."""
    r = requests.get(f"http://127.0.0.1:{PORT}/ping")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_e2e_noargs_second_route(server):
    """Second zero-arg route also works (exercises tuple ABI)."""
    r = requests.get(f"http://127.0.0.1:{PORT}/hello")
    assert r.status_code == 200
    assert r.json()["message"] == "hello"


def test_e2e_simple_sync_path_param(server):
    """simple_sync route with string path param returns correct value."""
    r = requests.get(f"http://127.0.0.1:{PORT}/items/abc")
    assert r.status_code == 200
    assert r.json()["item_id"] == "abc"


def test_e2e_simple_sync_int_path_param(server):
    """simple_sync route with int path param converts correctly."""
    r = requests.get(f"http://127.0.0.1:{PORT}/typed/5")
    assert r.status_code == 200
    data = r.json()
    assert data["n"] == 5
    assert data["doubled"] == 10


def test_e2e_post_pydantic_model(server):
    """POST with Pydantic body model parses correctly end-to-end."""
    r = requests.post(
        f"http://127.0.0.1:{PORT}/items",
        json={"name": "widget", "price": 9.99},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "widget"
    assert data["price"] == pytest.approx(9.99)
    assert data["created"] is True


def test_e2e_post_invalid_json(server):
    """POST with malformed JSON returns non-200 status."""
    r = requests.post(
        f"http://127.0.0.1:{PORT}/items",
        data="not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code != 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
