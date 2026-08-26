"""Unit coverage for the public pre-upgrade WebSocket guard API."""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping

import pytest
from turboapi import (
    TurboAPI,
    WebSocketUpgradeRejection,
    WebSocketUpgradeRequest,
)
from turboapi.websockets import _evaluate_websocket_upgrade_guard


def test_upgrade_request_normalizes_metadata_and_is_read_only() -> None:
    captured: list[WebSocketUpgradeRequest] = []

    def guard(request: WebSocketUpgradeRequest) -> bool:
        captured.append(request)
        return True

    assert (
        _evaluate_websocket_upgrade_guard(
            guard,
            "/guarded",
            b"repo=turboapi&tag=one&tag=two&empty=",
            [
                (b"Authorization", b"Bearer example"),
                (b"X-Tenant", b"alpha"),
            ],
        )
        == 0
    )
    request = captured.pop()
    assert request.path == "/guarded"
    assert request.headers == {
        "authorization": "Bearer example",
        "x-tenant": "alpha",
    }
    assert request.query_params == {
        "repo": "turboapi",
        "tag": "two",
        "empty": "",
    }
    assert request.query_string == b"repo=turboapi&tag=one&tag=two&empty="
    assert isinstance(request.headers, Mapping)
    with pytest.raises(TypeError):
        request.headers["authorization"] = "replacement"  # type: ignore[index]


@pytest.mark.parametrize("result", [False, None, 1, "allow", object()])
def test_guard_requires_literal_true(result: object) -> None:
    assert _evaluate_websocket_upgrade_guard(lambda _request: result, "/ws", b"", []) == 403


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_guard_rejection_selects_a_safe_http_error(status: int) -> None:
    assert (
        _evaluate_websocket_upgrade_guard(
            lambda _request: WebSocketUpgradeRejection(status), "/ws", b"", []
        )
        == status
    )


@pytest.mark.parametrize("status", [200, 418, 502, 504, 599, 600, True, "403"])
def test_guard_rejection_rejects_unsafe_or_invalid_status(status: object) -> None:
    with pytest.raises(ValueError):
        WebSocketUpgradeRejection(status)  # type: ignore[arg-type]


def test_guard_exceptions_and_async_results_fail_closed() -> None:
    def raises(_request: WebSocketUpgradeRequest) -> bool:
        raise RuntimeError("authorization material must not escape")

    async def async_guard(_request: WebSocketUpgradeRequest) -> bool:
        return True

    assert _evaluate_websocket_upgrade_guard(raises, "/ws", b"", []) == 403
    assert _evaluate_websocket_upgrade_guard(async_guard, "/ws", b"", []) == 403


def test_route_decorator_tracks_guard_and_rejects_noncallables() -> None:
    app = TurboAPI()

    def guard(_request: WebSocketUpgradeRequest) -> bool:
        return True

    @app.websocket("/guarded", guard=guard)
    async def guarded(_websocket) -> None:
        pass

    assert app._websocket_guards["/guarded"] is guard
    with pytest.raises(TypeError, match="guard must be callable"):
        app.websocket("/bad", guard="not callable")  # type: ignore[arg-type]


def test_failed_live_registration_rolls_back_python_routes(monkeypatch) -> None:
    app = TurboAPI()

    def old_guard(_request: WebSocketUpgradeRequest) -> bool:
        return True

    async def old_handler(_websocket) -> None:
        pass

    app.websocket("/guarded", guard=old_guard)(old_handler)

    class FailingServer:
        def add_websocket_route(self, *_args) -> None:
            raise RuntimeError("native registration failed")

    app.zig_server = FailingServer()
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())

    def replacement_guard(_request: WebSocketUpgradeRequest) -> bool:
        return False

    async def replacement_handler(_websocket) -> None:
        pass

    with pytest.raises(RuntimeError, match="native registration failed"):
        app.websocket("/guarded", guard=replacement_guard)(replacement_handler)
    assert app._websocket_routes["/guarded"] is old_handler
    assert app._websocket_guards["/guarded"] is old_guard

    with pytest.raises(RuntimeError, match="native registration failed"):
        app.websocket("/new", guard=replacement_guard)(replacement_handler)
    assert "/new" not in app._websocket_routes
    assert "/new" not in app._websocket_guards
