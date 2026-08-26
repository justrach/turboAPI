"""Native WebSocket route registries stay scoped to their TurboServer."""

from __future__ import annotations

import asyncio
import gc
import socket
import subprocess
import sys
import textwrap
import threading
import time
import weakref

import pytest

websockets = pytest.importorskip("websockets")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def isolated_ws_server(tmp_path_factory: pytest.TempPathFactory):
    port_a = _free_port()
    port_b = _free_port()
    ready_path = tmp_path_factory.mktemp("ws-route-isolation") / "ready"
    script = textwrap.dedent(
        """
        import concurrent.futures
        import gc
        import socket
        import sys
        import threading
        import time
        import weakref

        from turboapi import turbonet
        from turboapi.websockets import WebSocket, WebSocketDisconnect

        port_a = int(sys.argv[1])
        port_b = int(sys.argv[2])
        ready_path = sys.argv[3]

        async def a_same(ws: WebSocket):
            await ws.accept()
            await ws.send_text("A")
            await ws.close()

        async def b_same(ws: WebSocket):
            await ws.accept()
            await ws.send_text("B")
            await ws.close()

        async def b_private(ws: WebSocket):
            await ws.accept()
            await ws.send_text("PRIVATE-B")
            await ws.close()

        async def b_replace(ws: WebSocket):
            await ws.accept()
            await ws.send_text("B-REPLACE")
            await ws.close()

        async def old_replace(ws: WebSocket):
            await ws.accept()
            try:
                while True:
                    await ws.send_text("OLD:" + await ws.receive_text())
            except WebSocketDisconnect:
                pass

        async def new_replace(ws: WebSocket):
            await ws.accept()
            try:
                while True:
                    await ws.send_text("NEW:" + await ws.receive_text())
            except WebSocketDisconnect:
                pass

        class LifetimeHandler:
            async def __call__(self, ws: WebSocket):
                await ws.accept()
                try:
                    while True:
                        await ws.send_text("LIFETIME-OLD:" + await ws.receive_text())
                except WebSocketDisconnect:
                    pass

        class LifetimeGuard:
            def __call__(self, _request):
                return True

        async def new_lifetime(ws: WebSocket):
            await ws.accept()
            try:
                while True:
                    await ws.send_text("LIFETIME-NEW:" + await ws.receive_text())
            except WebSocketDisconnect:
                pass

        server_a = turbonet.TurboServer("127.0.0.1", port_a)
        server_a.add_websocket_route("/same", a_same)
        server_a.add_websocket_route("/replace", old_replace)
        lifetime_handler = LifetimeHandler()
        lifetime_guard = LifetimeGuard()
        lifetime_handler_ref = weakref.ref(lifetime_handler)
        lifetime_guard_ref = weakref.ref(lifetime_guard)
        server_a.add_websocket_route("/lifetime", lifetime_handler, lifetime_guard)
        del lifetime_handler, lifetime_guard

        async def replace_control(ws: WebSocket):
            server_a.add_websocket_route("/replace", new_replace)
            await ws.accept()
            await ws.send_text("swapped")
            await ws.close()

        server_a.add_websocket_route("/replace-control", replace_control)

        async def lifetime_replace_control(ws: WebSocket):
            server_a.add_websocket_route("/lifetime", new_lifetime)
            gc.collect()
            await ws.accept()
            await ws.send_text(
                f"{int(lifetime_handler_ref() is not None)}:"
                f"{int(lifetime_guard_ref() is not None)}"
            )
            await ws.close()

        async def lifetime_status(ws: WebSocket):
            gc.collect()
            await ws.accept()
            await ws.send_text(
                f"{int(lifetime_handler_ref() is not None)}:"
                f"{int(lifetime_guard_ref() is not None)}"
            )
            await ws.close()

        server_a.add_websocket_route("/lifetime-replace", lifetime_replace_control)
        server_a.add_websocket_route("/lifetime-status", lifetime_status)
        threading.Thread(target=server_a.run, daemon=True).start()

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port_a), timeout=0.1).close()
                break
            except OSError:
                time.sleep(0.02)
        else:
            raise RuntimeError("server A did not start")

        # Register app B only after A is serving. Before the fix these calls
        # replaced A's /same route and exposed /private-b on A's listener.
        server_b = turbonet.TurboServer("127.0.0.1", port_b)
        server_b.add_websocket_route("/same", b_same)
        server_b.add_websocket_route("/private-b", b_private)
        server_b.add_websocket_route("/replace", b_replace)

        def add_route(server, prefix, index):
            async def handler(ws: WebSocket):
                await ws.accept()
                await ws.send_text(f"{prefix}:{index}")
                await ws.close()
            server.add_websocket_route(f"/{prefix}-{index}", handler)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = []
            for index in range(32):
                futures.append(pool.submit(add_route, server_a, "a", index))
                futures.append(pool.submit(add_route, server_b, "b", index))
            for future in futures:
                future.result()

        threading.Thread(target=server_b.run, daemon=True).start()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port_b), timeout=0.1).close()
                break
            except OSError:
                time.sleep(0.02)
        else:
            raise RuntimeError("server B did not start")

        Path = __import__("pathlib").Path
        Path(ready_path).write_text("ready")
        while True:
            time.sleep(1)
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(port_a), str(port_b), str(ready_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"isolation server exited with {proc.returncode}")
        if ready_path.exists():
            break
        time.sleep(0.02)
    else:
        proc.terminate()
        raise TimeoutError("isolation server did not become ready")

    yield f"127.0.0.1:{port_a}", f"127.0.0.1:{port_b}"

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


async def _one_message(base: str, path: str) -> str:
    async with websockets.connect(f"ws://{base}{path}", close_timeout=0.2) as ws:
        return str(await asyncio.wait_for(ws.recv(), timeout=2.0))


@pytest.mark.asyncio
async def test_two_live_apps_keep_routes_on_their_own_ports(
    isolated_ws_server: tuple[str, str],
) -> None:
    server_a, server_b = isolated_ws_server
    assert await _one_message(server_a, "/same") == "A"
    assert await _one_message(server_b, "/same") == "B"
    assert await _one_message(server_a, "/a-17") == "a:17"
    assert await _one_message(server_b, "/b-17") == "b:17"
    assert await _one_message(server_b, "/private-b") == "PRIVATE-B"

    for base, path in (
        (server_a, "/private-b"),
        (server_a, "/b-17"),
        (server_b, "/a-17"),
    ):
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            await _one_message(base, path)
        assert exc_info.value.response.status_code == 404


@pytest.mark.asyncio
async def test_concurrent_native_dispatch_preserves_listener_identity(
    isolated_ws_server: tuple[str, str],
) -> None:
    server_a, server_b = isolated_ws_server
    requests = []
    expected = []
    for index in range(8):
        requests.append(_one_message(server_a, f"/a-{index}"))
        expected.append(f"a:{index}")
        requests.append(_one_message(server_b, f"/b-{index}"))
        expected.append(f"b:{index}")

    assert await asyncio.gather(*requests) == expected


@pytest.mark.asyncio
async def test_live_replacement_is_scoped_and_inflight_snapshot_is_owned(
    isolated_ws_server: tuple[str, str],
) -> None:
    server_a, server_b = isolated_ws_server
    async with websockets.connect(f"ws://{server_a}/replace", close_timeout=0.2) as old_ws:
        await old_ws.send("first")
        assert await old_ws.recv() == "OLD:first"
        assert await _one_message(server_a, "/replace-control") == "swapped"

        # The existing connection owns the old handler snapshot.
        await old_ws.send("second")
        assert await old_ws.recv() == "OLD:second"

        async with websockets.connect(f"ws://{server_a}/replace", close_timeout=0.2) as new_ws:
            await new_ws.send("third")
            assert await new_ws.recv() == "NEW:third"

        assert await _one_message(server_b, "/replace") == "B-REPLACE"


@pytest.mark.asyncio
async def test_concurrent_replacement_and_close_release_inflight_callbacks(
    isolated_ws_server: tuple[str, str],
) -> None:
    server_a, _server_b = isolated_ws_server
    old_ws = await websockets.connect(f"ws://{server_a}/lifetime", close_timeout=0.2)
    try:
        await old_ws.send("first")
        assert await old_ws.recv() == "LIFETIME-OLD:first"

        # Replacement races an already accepted connection. The connection's
        # native snapshot must retain both callbacks until its worker exits.
        swapped, _ = await asyncio.gather(
            _one_message(server_a, "/lifetime-replace"),
            old_ws.send("during-swap"),
        )
        assert swapped == "1:1"
        assert await old_ws.recv() == "LIFETIME-OLD:during-swap"
    finally:
        await old_ws.close()

    deadline = time.monotonic() + 3.0
    while True:
        status = await _one_message(server_a, "/lifetime-status")
        if status == "0:0":
            break
        if time.monotonic() >= deadline:
            pytest.fail(f"in-flight callback snapshot was not released: {status}")
        await asyncio.sleep(0.02)

    async with websockets.connect(f"ws://{server_a}/lifetime", close_timeout=0.2) as new_ws:
        await new_ws.send("after")
        assert await new_ws.recv() == "LIFETIME-NEW:after"


def test_server_state_releases_callbacks_on_teardown() -> None:
    from turboapi import turbonet

    class Callback:
        def __call__(self, *_args):
            return None

    server = turbonet.TurboServer("127.0.0.1", _free_port())
    handler = Callback()
    guard = Callback()
    handler_ref = weakref.ref(handler)
    guard_ref = weakref.ref(guard)
    server.add_websocket_route("/owned", handler, guard)

    del handler, guard
    gc.collect()
    assert handler_ref() is not None
    assert guard_ref() is not None

    del server
    gc.collect()
    assert handler_ref() is None
    assert guard_ref() is None


def test_callback_ownership_follows_retained_native_state() -> None:
    from turboapi import turbonet

    class Callback:
        def __call__(self, *_args):
            return None

    server = turbonet.TurboServer("127.0.0.1", _free_port())
    state = server._state
    handler = Callback()
    handler_ref = weakref.ref(handler)
    server.add_websocket_route("/state-owned", handler)

    del handler, server
    gc.collect()
    assert handler_ref() is not None

    # The state dict, not the convenience wrapper, is the native registry's
    # lifetime anchor. This also keeps low-level `_server_run(state)` safe.
    del state
    gc.collect()
    assert handler_ref() is None


def test_replacement_releases_callback_finalizers_outside_native_lock() -> None:
    from turboapi import turbonet

    server = turbonet.TurboServer("127.0.0.1", _free_port())
    finalized: list[str] = []

    async def replacement(_websocket) -> None:
        return None

    class Callback:
        def __init__(self, on_finalize) -> None:
            self.on_finalize = on_finalize

        async def __call__(self, _websocket) -> None:
            return None

        def __del__(self) -> None:
            self.on_finalize()

    def on_finalize() -> None:
        finalized.append("old")
        server.add_websocket_route("/from-finalizer", replacement)

    callback = Callback(on_finalize)
    server.add_websocket_route("/replace-finalizer", callback)
    del callback

    errors: list[BaseException] = []

    def replace() -> None:
        try:
            server.add_websocket_route("/replace-finalizer", replacement)
        except BaseException as error:  # pragma: no cover - assertion aid
            errors.append(error)

    thread = threading.Thread(target=replace, daemon=True)
    thread.start()
    thread.join(2)
    assert not thread.is_alive(), "callback finalizer re-entered a held route lock"
    assert errors == []
    assert finalized == ["old"]


def test_bound_method_callback_cycle_is_visible_to_python_gc() -> None:
    from turboapi import turbonet

    class Service:
        def __init__(self) -> None:
            self.server = turbonet.TurboServer("127.0.0.1", _free_port())
            self.server.add_websocket_route("/bound", self.handle, self.guard)

        async def handle(self, _websocket) -> None:
            return None

        def guard(self, _request) -> bool:
            return True

    service = Service()
    service_ref = weakref.ref(service)
    server_ref = weakref.ref(service.server)

    del service
    gc.collect()
    assert service_ref() is None
    assert server_ref() is None


def test_closure_callback_cycle_capturing_server_and_app_is_collectable() -> None:
    from turboapi import turbonet

    class App:
        pass

    def make_cycle():
        app = App()
        server = turbonet.TurboServer("127.0.0.1", _free_port())
        app.server = server

        async def handler(_websocket) -> None:
            _ = (server, app)

        def guard(_request) -> bool:
            return bool(server and app)

        server.add_websocket_route("/closure", handler, guard)
        return (
            weakref.ref(server),
            weakref.ref(app),
            weakref.ref(handler),
            weakref.ref(guard),
        )

    refs = make_cycle()
    gc.collect()
    assert all(ref() is None for ref in refs)
