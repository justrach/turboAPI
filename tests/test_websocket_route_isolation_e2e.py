"""Native WebSocket route registries stay scoped to their TurboServer."""

from __future__ import annotations

import asyncio
import gc
import socket
import subprocess
import sys
import textwrap
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
        import socket
        import sys
        import threading
        import time

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

        server_a = turbonet.TurboServer("127.0.0.1", port_a)
        server_a.add_websocket_route("/same", a_same)
        server_a.add_websocket_route("/replace", old_replace)

        async def replace_control(ws: WebSocket):
            server_a.add_websocket_route("/replace", new_replace)
            await ws.accept()
            await ws.send_text("swapped")
            await ws.close()

        server_a.add_websocket_route("/replace-control", replace_control)
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


def test_native_registry_releases_callbacks_on_server_teardown() -> None:
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
