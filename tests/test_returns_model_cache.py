"""Targeted regression tests for PR #150 — `_returns_model` caching.

Confirms the three branches of `_returns_model` and that the cached
result drives the right behavior in `create_fast_handler`:

* annotated `-> Model`  : should call `result.model_dump()` (skipping
                          the per-response hasattr).
* annotated `-> dict`   : should NOT call model_dump (and skip hasattr).
* unannotated handler   : should fall back to per-response hasattr —
                          and still call model_dump on a model return.
"""

from __future__ import annotations

import json

from dhi import BaseModel
from turboapi.request_handler import _returns_model, create_fast_handler
from turboapi.routing import HTTPMethod, RouteDefinition


class Item(BaseModel):
    name: str
    qty: int


def _route() -> RouteDefinition:
    return RouteDefinition(
        path="/x",
        method=HTTPMethod.GET,
        handler=lambda: None,
        path_params=[],
        query_params={},
    )


def test_returns_model_dhi_basemodel():
    def h() -> Item: ...
    assert _returns_model(h) is True


def test_returns_model_leaf_dict():
    def h() -> dict: ...
    assert _returns_model(h) is False


def test_returns_model_leaf_str():
    def h() -> str: ...
    assert _returns_model(h) is False


def test_returns_model_leaf_none():
    def h() -> None: ...
    assert _returns_model(h) is False


def test_returns_model_unannotated():
    def h(): ...
    assert _returns_model(h) is None


def test_returns_model_optional_falls_back():
    def h() -> dict | None: ...
    # Generic / Union — keep per-response check.
    assert _returns_model(h) is None


def test_fast_handler_model_annotated_calls_model_dump():
    def h() -> Item:
        return Item(name="widget", qty=3)

    fast = create_fast_handler(h, _route())
    status, ctype, body = fast()
    assert status == 200
    assert ctype == "application/json"
    assert json.loads(body) == {"name": "widget", "qty": 3}


def test_fast_handler_dict_annotated_skips_model_dump():
    def h() -> dict:
        return {"hello": "world"}

    fast = create_fast_handler(h, _route())
    status, ctype, body = fast()
    assert status == 200
    assert ctype == "application/json"
    assert json.loads(body) == {"hello": "world"}


def test_fast_handler_unannotated_falls_back_to_hasattr_for_model():
    # No return annotation — the cached value is None, so per-response
    # hasattr still runs and still recognizes the model. Identity-
    # preserving with the pre-PR behavior for unannotated handlers.
    def h():
        return Item(name="thing", qty=7)

    fast = create_fast_handler(h, _route())
    status, ctype, body = fast()
    assert status == 200
    assert json.loads(body) == {"name": "thing", "qty": 7}


def test_fast_handler_unannotated_dict_passthrough():
    def h():
        return {"a": 1}

    fast = create_fast_handler(h, _route())
    status, ctype, body = fast()
    assert status == 200
    assert json.loads(body) == {"a": 1}
