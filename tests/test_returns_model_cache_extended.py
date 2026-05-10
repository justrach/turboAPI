"""Targeted regression tests for PR #157 — `_returns_model` caching extended.

Extends the coverage from `test_returns_model_cache.py` (which exercises
`create_fast_handler`) to the three additional dispatch sites patched
in #157:

* `create_pos_handler.pos_handler`              (sync, positional)
* `create_async_pos_handler.pos_handler`        (async, positional)
* `create_fast_model_handler.fast_model_handler` (model-input dispatch)

Each handler is exercised in three shapes:
* annotated `-> Model`  : should call `result.model_dump()`
* annotated `-> dict`   : should skip the model_dump path
* unannotated           : should fall back to per-response hasattr
"""

from __future__ import annotations

import asyncio
import json

from dhi import BaseModel
from turboapi.request_handler import (
    create_async_pos_handler,
    create_fast_model_handler,
    create_pos_handler,
)


class Item(BaseModel):
    name: str
    qty: int


# -- create_pos_handler --------------------------------------------------

def test_pos_handler_model_annotated():
    def h() -> Item:
        return Item(name="widget", qty=3)

    fast = create_pos_handler(h)
    status, ctype, body = fast()
    assert status == 200
    assert ctype == "application/json"
    assert json.loads(body) == {"name": "widget", "qty": 3}


def test_pos_handler_dict_annotated():
    def h() -> dict:
        return {"hello": "world"}

    fast = create_pos_handler(h)
    status, _, body = fast()
    assert status == 200
    assert json.loads(body) == {"hello": "world"}


def test_pos_handler_unannotated_model_return():
    def h():
        return Item(name="thing", qty=7)

    fast = create_pos_handler(h)
    status, _, body = fast()
    assert status == 200
    assert json.loads(body) == {"name": "thing", "qty": 7}


def test_pos_handler_unannotated_dict_return():
    def h():
        return {"a": 1}

    fast = create_pos_handler(h)
    status, _, body = fast()
    assert status == 200
    assert json.loads(body) == {"a": 1}


# -- create_async_pos_handler --------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if asyncio.get_event_loop().is_running() is False else asyncio.run(coro)


def test_async_pos_handler_model_annotated():
    async def h() -> Item:
        return Item(name="widget", qty=3)

    fast = create_async_pos_handler(h)
    status, ctype, body = asyncio.run(fast())
    assert status == 200
    assert ctype == "application/json"
    assert json.loads(body) == {"name": "widget", "qty": 3}


def test_async_pos_handler_dict_annotated():
    async def h() -> dict:
        return {"hello": "world"}

    fast = create_async_pos_handler(h)
    status, _, body = asyncio.run(fast())
    assert status == 200
    assert json.loads(body) == {"hello": "world"}


def test_async_pos_handler_unannotated_model_return():
    async def h():
        return Item(name="thing", qty=7)

    fast = create_async_pos_handler(h)
    status, _, body = asyncio.run(fast())
    assert status == 200
    assert json.loads(body) == {"name": "thing", "qty": 7}


# -- create_fast_model_handler -------------------------------------------

def test_fast_model_handler_model_annotated_return():
    # Handler takes a model in, returns a (different shape) model out.
    class Out(BaseModel):
        echoed: str
        doubled_qty: int

    def h(item: Item) -> Out:
        return Out(echoed=item.name, doubled_qty=item.qty * 2)

    fast = create_fast_model_handler(h, Item, "item")
    status, ctype, body = fast(body_dict={"name": "widget", "qty": 5})
    assert status == 200
    assert ctype == "application/json"
    assert json.loads(body) == {"echoed": "widget", "doubled_qty": 10}


def test_fast_model_handler_dict_annotated_return():
    def h(item: Item) -> dict:
        return {"name": item.name, "qty": item.qty}

    fast = create_fast_model_handler(h, Item, "item")
    status, _, body = fast(body_dict={"name": "widget", "qty": 5})
    assert status == 200
    assert json.loads(body) == {"name": "widget", "qty": 5}


def test_fast_model_handler_unannotated_model_return():
    def h(item):
        return Item(name=item.name + "!", qty=item.qty)

    fast = create_fast_model_handler(h, Item, "item")
    status, _, body = fast(body_dict={"name": "widget", "qty": 5})
    assert status == 200
    assert json.loads(body) == {"name": "widget!", "qty": 5}
