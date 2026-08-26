"""Unit coverage for the public pre-upgrade WebSocket guard API."""

from __future__ import annotations

import importlib.util
import threading
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


def test_concurrent_successful_registrations_keep_python_and_native_in_sync(
    monkeypatch,
) -> None:
    app = TurboAPI()
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())

    async def first_handler(_websocket) -> None:
        pass

    async def second_handler(_websocket) -> None:
        pass

    def first_guard(_request: WebSocketUpgradeRequest) -> bool:
        return True

    def second_guard(_request: WebSocketUpgradeRequest) -> bool:
        return True

    first_entered_native = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_entered_native = threading.Event()

    class ReorderedServer:
        current = None

        def add_websocket_route(self, path, handler, guard=None) -> None:
            if handler is first_handler:
                first_entered_native.set()
                assert release_first.wait(2)
            elif handler is second_handler:
                second_entered_native.set()
            self.current = (path, handler, guard)

    server = ReorderedServer()
    app.zig_server = server
    errors: list[BaseException] = []

    def register_first() -> None:
        try:
            app.websocket("/race", guard=first_guard)(first_handler)
        except BaseException as exc:  # pragma: no cover - assertion aid
            errors.append(exc)

    def register_second() -> None:
        second_started.set()
        try:
            app.websocket("/race", guard=second_guard)(second_handler)
        except BaseException as exc:  # pragma: no cover - assertion aid
            errors.append(exc)

    first = threading.Thread(target=register_first)
    second = threading.Thread(target=register_second)
    first.start()
    assert first_entered_native.wait(2)
    second.start()
    assert second_started.wait(2)
    assert not second_entered_native.wait(0.05)
    release_first.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert server.current == ("/race", second_handler, second_guard)
    assert app._websocket_routes["/race"] is second_handler
    assert app._websocket_guards["/race"] is second_guard


@pytest.mark.parametrize("failure_first", [True, False])
def test_concurrent_success_and_failure_roll_back_their_own_snapshot(
    monkeypatch, failure_first: bool
) -> None:
    app = TurboAPI()
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())

    def old_guard(_request: WebSocketUpgradeRequest) -> bool:
        return True

    async def old_handler(_websocket) -> None:
        pass

    app.websocket("/race", guard=old_guard)(old_handler)

    async def successful_handler(_websocket) -> None:
        pass

    async def failing_handler(_websocket) -> None:
        pass

    def successful_guard(_request: WebSocketUpgradeRequest) -> bool:
        return True

    def failing_guard(_request: WebSocketUpgradeRequest) -> bool:
        return False

    first_handler = failing_handler if failure_first else successful_handler
    first_guard = failing_guard if failure_first else successful_guard
    second_handler = successful_handler if failure_first else failing_handler
    second_guard = successful_guard if failure_first else failing_guard
    first_entered_native = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_entered_native = threading.Event()

    class ReorderedServer:
        current = ("/race", old_handler, old_guard)

        def add_websocket_route(self, path, handler, guard=None) -> None:
            if handler is first_handler:
                first_entered_native.set()
                assert release_first.wait(2)
            elif handler is second_handler:
                second_entered_native.set()
            if handler is failing_handler:
                raise RuntimeError("native registration failed")
            self.current = (path, handler, guard)

    server = ReorderedServer()
    app.zig_server = server
    errors: list[tuple[object, BaseException]] = []

    def register(handler, guard, started=None) -> None:
        if started is not None:
            started.set()
        try:
            app.websocket("/race", guard=guard)(handler)
        except BaseException as exc:
            errors.append((handler, exc))

    first = threading.Thread(target=register, args=(first_handler, first_guard))
    second = threading.Thread(
        target=register,
        args=(second_handler, second_guard, second_started),
    )
    first.start()
    assert first_entered_native.wait(2)
    second.start()
    assert second_started.wait(2)
    assert not second_entered_native.wait(0.05)
    release_first.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(errors) == 1
    assert errors[0][0] is failing_handler
    assert isinstance(errors[0][1], RuntimeError)
    assert server.current == ("/race", successful_handler, successful_guard)
    assert app._websocket_routes["/race"] is successful_handler
    assert app._websocket_guards["/race"] is successful_guard


def test_live_registration_lock_is_reentrant(monkeypatch) -> None:
    app = TurboAPI()
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())

    async def inner_handler(_websocket) -> None:
        pass

    async def outer_handler(_websocket) -> None:
        pass

    class ReentrantServer:
        routes: dict[str, object] = {}

        def add_websocket_route(self, path, handler, guard=None) -> None:
            self.routes[path] = (handler, guard)
            if path == "/outer":
                app.websocket("/inner")(inner_handler)

    server = ReentrantServer()
    app.zig_server = server
    app.websocket("/outer")(outer_handler)

    assert server.routes["/outer"] == (outer_handler, None)
    assert server.routes["/inner"] == (inner_handler, None)
    assert app._websocket_routes["/outer"] is outer_handler
    assert app._websocket_routes["/inner"] is inner_handler


def test_startup_snapshot_is_serialized_with_live_registration(monkeypatch) -> None:
    app = TurboAPI()
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())

    def old_guard(_request: WebSocketUpgradeRequest) -> bool:
        return True

    def new_guard(_request: WebSocketUpgradeRequest) -> bool:
        return True

    async def old_handler(_websocket) -> None:
        pass

    async def new_handler(_websocket) -> None:
        pass

    app.websocket("/race", guard=old_guard)(old_handler)
    startup_entered_native = threading.Event()
    release_startup = threading.Event()
    replacement_started = threading.Event()
    replacement_entered_native = threading.Event()

    class BlockingStartupServer:
        current = None

        def add_websocket_route(self, path, handler, guard=None) -> None:
            if handler is old_handler:
                startup_entered_native.set()
                assert release_startup.wait(2)
            elif handler is new_handler:
                replacement_entered_native.set()
            self.current = (path, handler, guard)

    server = BlockingStartupServer()
    app.zig_server = server

    startup = threading.Thread(
        target=app._register_websocket_routes_with_server,
        args=(server,),
    )

    def replace() -> None:
        replacement_started.set()
        app.websocket("/race", guard=new_guard)(new_handler)

    replacement = threading.Thread(target=replace)
    startup.start()
    assert startup_entered_native.wait(2)
    replacement.start()
    assert replacement_started.wait(2)
    assert not replacement_entered_native.wait(0.05)
    release_startup.set()
    startup.join(2)
    replacement.join(2)

    assert not startup.is_alive()
    assert not replacement.is_alive()
    assert server.current == ("/race", new_handler, new_guard)
    assert app._websocket_routes["/race"] is new_handler
    assert app._websocket_guards["/race"] is new_guard


def test_startup_reentrant_addition_registers_live(monkeypatch) -> None:
    app = TurboAPI()
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())

    async def initial_handler(_websocket) -> None:
        pass

    async def added_handler(_websocket) -> None:
        pass

    app.websocket("/initial")(initial_handler)

    class ReentrantAddServer:
        routes: dict[str, tuple[object, object]] = {}
        added = False

        def add_websocket_route(self, path, handler, guard=None) -> None:
            self.routes[path] = (handler, guard)
            if path == "/initial" and not self.added:
                self.added = True
                app.websocket("/added")(added_handler)

    server = ReentrantAddServer()
    app.zig_server = server
    assert app._register_websocket_routes_with_server(server) == ("/initial",)

    assert server.routes == {
        "/initial": (initial_handler, None),
        "/added": (added_handler, None),
    }
    assert app._websocket_routes["/added"] is added_handler


def test_startup_reentrant_replacement_reads_current_not_stale_snapshot(monkeypatch) -> None:
    app = TurboAPI()
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())

    async def trigger_handler(_websocket) -> None:
        pass

    async def old_later_handler(_websocket) -> None:
        pass

    async def new_later_handler(_websocket) -> None:
        pass

    app.websocket("/trigger")(trigger_handler)
    app.websocket("/later")(old_later_handler)

    class ReentrantReplaceServer:
        routes: dict[str, tuple[object, object]] = {}
        calls: list[tuple[str, object]] = []
        replaced = False

        def add_websocket_route(self, path, handler, guard=None) -> None:
            self.calls.append((path, handler))
            self.routes[path] = (handler, guard)
            if path == "/trigger" and not self.replaced:
                self.replaced = True
                app.websocket("/later")(new_later_handler)

    server = ReentrantReplaceServer()
    app.zig_server = server
    assert app._register_websocket_routes_with_server(server) == (
        "/trigger",
        "/later",
    )

    assert server.routes["/later"] == (new_later_handler, None)
    assert app._websocket_routes["/later"] is new_later_handler
    assert ("/later", old_later_handler) not in server.calls
    assert server.calls.count(("/later", new_later_handler)) == 2


def test_startup_failure_after_reentry_is_consistent_and_retryable(monkeypatch) -> None:
    app = TurboAPI()
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())

    async def initial_handler(_websocket) -> None:
        pass

    async def added_handler(_websocket) -> None:
        pass

    app.websocket("/initial")(initial_handler)

    class FailingReentrantServer:
        routes: dict[str, tuple[object, object]] = {}
        reentered = False
        fail_startup = True

        def add_websocket_route(self, path, handler, guard=None) -> None:
            self.routes[path] = (handler, guard)
            if path == "/initial" and not self.reentered:
                self.reentered = True
                app.websocket("/added")(added_handler)
                if self.fail_startup:
                    raise RuntimeError("startup registration failed")

    server = FailingReentrantServer()
    app.zig_server = server
    with pytest.raises(RuntimeError, match="startup registration failed"):
        app._register_websocket_routes_with_server(server)

    assert app._websocket_routes == {
        "/initial": initial_handler,
        "/added": added_handler,
    }
    assert server.routes["/added"] == (added_handler, None)

    server.fail_startup = False
    assert app._register_websocket_routes_with_server(server) == (
        "/initial",
        "/added",
    )
    assert server.routes == {
        "/initial": (initial_handler, None),
        "/added": (added_handler, None),
    }
