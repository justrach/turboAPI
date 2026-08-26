"""Process-lifetime regression tests for the native WebSocket worker pool."""

from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import textwrap
import time

import pytest

websockets = pytest.importorskip("websockets")


def _wait_for_marker(
    log_path: pathlib.Path,
    process: subprocess.Popen,
    prefix: str,
    *,
    timeout: float = 15.0,
) -> object:
    deadline = time.monotonic() + timeout
    output = ""
    while time.monotonic() < deadline:
        output = log_path.read_text(errors="replace")
        for line in output.splitlines():
            if line.startswith(prefix):
                return json.loads(line.removeprefix(prefix))
        if process.poll() is not None:
            break
        time.sleep(0.05)
    raise AssertionError(
        f"process did not emit {prefix!r} (exit={process.poll()}):\n{output}"
    )


def _thread_count(pid: int) -> int:
    proc_status = pathlib.Path(f"/proc/{pid}/status")
    if proc_status.exists():
        for line in proc_status.read_text().splitlines():
            if line.startswith("Threads:"):
                return int(line.split(":", 1)[1])
    output = subprocess.check_output(["ps", "-M", "-p", str(pid)], text=True)
    # BSD/macOS ps emits one header followed by one line per native thread.
    return max(0, len(output.splitlines()) - 1)


def _rss_kib(pid: int) -> int:
    output = subprocess.check_output(
        ["ps", "-o", "rss=", "-p", str(pid)], text=True
    ).strip()
    return int(output)


@pytest.fixture(scope="module")
def repeated_ws_servers(tmp_path_factory: pytest.TempPathFactory):
    server_count = 6
    script = textwrap.dedent(
        f"""
        import asyncio
        import json
        import os
        import socket
        import sys
        import threading
        import time

        from turboapi import TurboAPI
        from turboapi.websockets import WebSocket

        def free_port():
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                return listener.getsockname()[1]

        def wait_ready(port):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        return
                except OSError:
                    time.sleep(0.02)
            raise RuntimeError(f"server {{port}} did not start")

        def start_server(index):
            port = free_port()
            app = TurboAPI(title=f"ws-pool-lifecycle-{{index}}", version="0")

            @app.websocket("/ws-lifecycle")
            async def lifecycle(ws: WebSocket):
                await ws.accept()
                metrics = ws.transport_metrics
                await ws.send_json({{
                    "worker_count": metrics["worker_count"],
                    "max_active": metrics["max_active"],
                    "native_message_limit": metrics["message_limit"],
                    "python_message_limit": ws._zig_inbound.maxsize,
                    "native_byte_limit": metrics["byte_limit"],
                    "python_byte_limit": ws._queue_bytes,
                    "native_write_timeout_ms": metrics["write_timeout_ms"],
                    "python_write_timeout_ms": int(ws._write_timeout_s * 1000),
                }})
                message = await ws.receive_text()
                await ws.send_text(message)
                await ws.close()

            thread = threading.Thread(
                target=lambda: app.run(host="127.0.0.1", port=port),
                daemon=True,
            )
            thread.start()
            wait_ready(port)
            return port

        ports = [start_server(0)]
        print("WS_POOL_STAGE1 " + json.dumps(ports), flush=True)
        if not sys.stdin.readline():
            raise RuntimeError("lifecycle test control pipe closed")

        # The first successful start owns process-global settings. These later
        # values must not resize native bounds or the Python bridge.
        os.environ["TURBO_WS_QUEUE_MESSAGES"] = "99"
        os.environ["TURBO_WS_QUEUE_BYTES"] = "999"
        os.environ["TURBO_WS_WRITE_TIMEOUT_MS"] = "999"
        ports.extend(start_server(index) for index in range(1, {server_count}))
        print("WS_POOL_STAGE2 " + json.dumps(ports), flush=True)
        while True:
            time.sleep(1)
        """
    )
    env = os.environ.copy()
    env.update(
        {
            "TURBO_THREAD_POOL_SIZE": "1",
            "TURBO_WS_WORKER_POOL_SIZE": "3",
            "TURBO_MAX_WEBSOCKETS": "3",
            "TURBO_WS_QUEUE_MESSAGES": "3",
            "TURBO_WS_QUEUE_BYTES": "4096",
            "TURBO_WS_WRITE_TIMEOUT_MS": "750",
        }
    )
    log_path = tmp_path_factory.mktemp("ws-pool-lifecycle") / "server.log"
    with log_path.open("wb") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            env=env,
            stdin=subprocess.PIPE,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
    _wait_for_marker(log_path, process, "WS_POOL_STAGE1 ")
    threads_stage1 = _thread_count(process.pid)
    rss_stage1 = _rss_kib(process.pid)
    assert process.stdin is not None
    process.stdin.write("continue\n")
    process.stdin.flush()
    stage2_ports = _wait_for_marker(log_path, process, "WS_POOL_STAGE2 ")
    threads_stage2 = _thread_count(process.pid)
    rss_stage2 = _rss_kib(process.pid)

    try:
        yield {
            "ports": stage2_ports,
            "server_count": server_count,
            "threads_stage1": threads_stage1,
            "threads_stage2": threads_stage2,
            "rss_stage1": rss_stage1,
            "rss_stage2": rss_stage2,
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def test_repeated_app_runs_do_not_multiply_websocket_workers(
    repeated_ws_servers,
) -> None:
    result = repeated_ws_servers
    additional_servers = result["server_count"] - 1
    # Each additional listener has one Python accept-loop thread. Both native
    # worker pools are process-global; allow three housekeeping threads, but
    # no per-listener HTTP or WebSocket worker multiplication.
    assert result["threads_stage2"] - result["threads_stage1"] <= (
        additional_servers + 3
    )
    assert result["rss_stage2"] - result["rss_stage1"] < 64 * 1024


@pytest.mark.asyncio
async def test_repeated_app_runs_share_frozen_pool_and_remain_usable(
    repeated_ws_servers,
) -> None:
    expected_metrics = {
        "worker_count": 3,
        "max_active": 3,
        "native_message_limit": 3,
        "python_message_limit": 3,
        "native_byte_limit": 4096,
        "python_byte_limit": 4096,
        "native_write_timeout_ms": 750,
        "python_write_timeout_ms": 750,
    }
    for port in repeated_ws_servers["ports"]:
        async with websockets.connect(
            f"ws://127.0.0.1:{port}/ws-lifecycle",
            compression=None,
        ) as websocket:
            assert json.loads(await websocket.recv()) == expected_metrics
            await websocket.send("still-works")
            assert await websocket.recv() == "still-works"


def test_zero_websocket_workers_is_a_clean_startup_error() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    script = textwrap.dedent(
        f"""
        from turboapi import TurboAPI

        app = TurboAPI(title="ws-zero-workers", version="0")
        app.run(host="127.0.0.1", port={port})
        """
    )
    env = os.environ.copy()
    env["TURBO_WS_WORKER_POOL_SIZE"] = "0"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode != 0
    assert "WebSocket worker pool could not start any workers" in (
        completed.stdout + completed.stderr
    )
