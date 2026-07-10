#!/usr/bin/env python3
"""Prove an installed Linux arm64 CPython 3.14t wheel serves with Zig."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import platform
import socket
import subprocess
import sys
import sysconfig
import time
import urllib.error
import urllib.request

EXPECTED = {"native": True, "runtime": "linux-aarch64-cp314t"}


def verify_runtime() -> pathlib.Path:
    assert platform.system() == "Linux", platform.system()
    assert platform.machine() == "aarch64", platform.machine()
    assert sys.version_info[:2] == (3, 14), sys.version
    assert sysconfig.get_config_var("Py_GIL_DISABLED") == 1
    assert hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()
    assert "314t" in (sysconfig.get_config_var("SOABI") or "")

    spec = importlib.util.find_spec("turboapi.turbonet")
    assert spec is not None, "turbonet extension is absent"
    assert isinstance(spec.loader, importlib.machinery.ExtensionFileLoader), spec.loader
    assert spec.origin, "turbonet extension has no origin"

    extension = pathlib.Path(spec.origin).resolve()
    assert extension.is_file(), extension
    assert "site-packages" in extension.parts, (
        "expected wheel-installed extension in site-packages",
        extension,
    )

    import turboapi.native_integration as native
    import turboapi.turbonet as turbonet

    assert hasattr(turbonet, "TurboServer")
    assert hasattr(turbonet, "ResponseView")
    assert native.NATIVE_CORE_AVAILABLE is True
    assert native._BACKEND == "zig"
    assert native.turbonet is turbonet
    return extension


def reserve_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve_and_request() -> None:
    port = reserve_port()
    app = f"""
from turboapi import TurboAPI

app = TurboAPI(title="wheel-smoke")

@app.get("/__turboapi_native_smoke__")
def smoke():
    return {EXPECTED!r}

app.run(host="127.0.0.1", port={port})
"""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-c", app],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    body = None
    error: Exception | None = None
    try:
        deadline = time.monotonic() + 30
        url = f"http://127.0.0.1:{port}/__turboapi_native_smoke__"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    assert response.status == 200
                    body = json.loads(response.read())
                    break
            except (OSError, urllib.error.URLError) as exc:
                error = exc
                time.sleep(0.2)
        assert body == EXPECTED, (body, EXPECTED, error)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        output = process.communicate(timeout=5)[0]
        print(output)


if __name__ == "__main__":
    native_extension = verify_runtime()
    print(f"Verified native extension: {native_extension}")
    serve_and_request()
    print("TurboAPI native wheel HTTP smoke passed")
