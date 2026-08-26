"""Wire-level coverage for native fast-response status and header metadata."""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import textwrap
import time

import pytest


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(params=(False, True), ids=("cache-disabled", "cache-enabled"))
def metadata_server(request: pytest.FixtureRequest, tmp_path):
    cache_enabled = bool(request.param)
    port = _free_port()
    log_path = tmp_path / "server.log"
    script = textwrap.dedent(
        f"""
        import asyncio

        from dhi import BaseModel
        from turboapi import JSONResponse, TurboAPI
        from turboapi.responses import (
            _NATIVE_HEADER_ERROR,
            _NATIVE_MAX_HEADER_BYTES,
            _NATIVE_MAX_HEADER_PAIRS,
        )

        app = TurboAPI(title="fast-response-metadata", version="0.0.1")
        calls = {{}}

        def response(name, payload, status):
            calls[name] = calls.get(name, 0) + 1
            return JSONResponse(
                {{"route": name, "payload": payload, "calls": calls[name]}},
                status_code=status,
                headers={{
                    "x-route-class": name,
                    "cache-control": "private, no-store",
                    "strict-transport-security": "max-age=31536000; includeSubDomains",
                    "content-security-policy": "default-src 'none'",
                }},
            )

        @app.get("/zero")
        def zero():
            return response("zero", "ok", 201)

        @app.get("/pos/{{item_id}}")
        def positional(item_id: int):
            return response("positional", item_id, 202)

        @app.post("/body")
        def body(name: str):
            return response("body", name, 203)

        @app.get("/async/{{item_id}}")
        async def async_positional(item_id: int):
            await asyncio.sleep(0)
            return response("async-positional", item_id, 206)

        @app.post("/async-body")
        async def async_body(name: str):
            await asyncio.sleep(0)
            return response("async-body", name, 207)

        class Widget(BaseModel):
            name: str

        @app.post("/model")
        def model(widget: Widget):
            return response("model", widget.name, 208)

        @app.get("/cookies")
        def cookies():
            result = JSONResponse({{"ok": True}}, status_code=209)
            result.set_cookie("first", "one", httponly=True)
            result.set_cookie("second", "two", secure=True)
            return result

        @app.get("/malformed")
        def malformed():
            calls["malformed"] = calls.get("malformed", 0) + 1
            return JSONResponse(
                {{"secret": "malformed-original", "calls": calls["malformed"]}},
                status_code=210,
                headers={{
                    "x-safe": "kept",
                    "x-bad-value": "safe\\r\\nX-Injected: value",
                    "x-bad-name\\r\\nX-Injected": "value",
                    "content-length": "99999",
                    "transfer-encoding": "chunked",
                }},
            )

        @app.get("/too-many")
        def too_many():
            calls["too-many"] = calls.get("too-many", 0) + 1
            headers = {{f"x-{{index:03d}}": "v" for index in range(_NATIVE_MAX_HEADER_PAIRS)}}
            headers["strict-transport-security"] = "max-age=31536000"
            return JSONResponse(
                {{"secret": "too-many-original", "calls": calls["too-many"]}},
                status_code=299,
                headers=headers,
            )

        @app.get("/too-large")
        def too_large():
            calls["too-large"] = calls.get("too-large", 0) + 1
            exact_value = "z" * (_NATIVE_MAX_HEADER_BYTES - len("x-fill") - 4)
            return JSONResponse(
                {{"secret": "too-large-original", "calls": calls["too-large"]}},
                status_code=298,
                headers={{"x-fill": exact_value, "cache-control": "no-store"}},
            )

        class OomHeaderValue:
            def __str__(self):
                raise MemoryError("simulated header normalization OOM")

        class InjectedMarkerResponse(JSONResponse):
            def _native_tuple(self):
                return (
                    self.status_code,
                    self.media_type,
                    self.body,
                    _NATIVE_HEADER_ERROR,
                )

        @app.get("/injected-marker")
        def injected_marker():
            calls["injected-marker"] = calls.get("injected-marker", 0) + 1
            return InjectedMarkerResponse(
                {{"secret": "injected-marker-original", "calls": calls["injected-marker"]}},
                status_code=296,
            )

        @app.get("/oom-marker")
        def oom_marker():
            calls["oom-marker"] = calls.get("oom-marker", 0) + 1
            return JSONResponse(
                {{"secret": "oom-marker-original", "calls": calls["oom-marker"]}},
                status_code=297,
                headers={{"x-oom": OomHeaderValue()}},
            )

        @app.get("/stats/{{name}}")
        def stats(name: str):
            return {{"calls": calls.get(name, 0)}}

        if __name__ == "__main__":
            app.run(host="127.0.0.1", port={port})
        """
    )
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TURBO_THREAD_POOL_SIZE"] = "4"
    if cache_enabled:
        env.pop("TURBO_DISABLE_RESPONSE_CACHE", None)
    else:
        env["TURBO_DISABLE_RESPONSE_CACHE"] = "1"

    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError(log_path.read_text(errors="replace"))
            time.sleep(0.05)
    else:
        proc.terminate()
        raise TimeoutError("metadata test server did not start")

    yield port, cache_enabled, log_path

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _request(port: int, method: str, path: str, payload: dict | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    body = None if payload is None else json.dumps(payload)
    headers = {} if body is None else {"content-type": "application/json"}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    response_body = response.read()
    result = response.status, response.getheaders(), response_body
    connection.close()
    return result


def _assert_metadata(status, headers, body, expected_status, route, payload):
    normalized = [(name.lower(), value) for name, value in headers]
    assert status == expected_status
    assert ("content-type", "application/json") in normalized
    assert ("x-route-class", route) in normalized
    assert ("cache-control", "private, no-store") in normalized
    assert (
        "strict-transport-security",
        "max-age=31536000; includeSubDomains",
    ) in normalized
    assert ("content-security-policy", "default-src 'none'") in normalized
    decoded = json.loads(body)
    assert decoded["route"] == route
    assert decoded["payload"] == payload
    return decoded["calls"]


def test_all_native_fast_classifications_preserve_response_metadata(metadata_server):
    port, cache_enabled, log_path = metadata_server
    cases = (
        ("GET", "/zero", None, 201, "zero", "ok"),
        ("GET", "/pos/42", None, 202, "positional", 42),
        ("POST", "/body", {"name": "sync"}, 203, "body", "sync"),
        ("GET", "/async/43", None, 206, "async-positional", 43),
        ("POST", "/async-body", {"name": "async"}, 207, "async-body", "async"),
        ("POST", "/model", {"name": "model"}, 208, "model", "model"),
    )

    for method, path, request_body, expected_status, route, expected_payload in cases:
        observed_calls = []
        for _ in range(3):
            observed_calls.append(
                _assert_metadata(
                    *_request(port, method, path, request_body),
                    expected_status,
                    route,
                    expected_payload,
                )
            )
        if cache_enabled and route in {"zero", "positional", "async-positional"}:
            assert observed_calls == [1, 1, 1]
        else:
            assert observed_calls == [1, 2, 3]

    log = log_path.read_text(errors="replace")
    for classification in (
        "[simple_sync_noargs]",
        "[simple_sync]",
        "[body_sync]",
        "[simple_async]",
        "[body_async]",
        "[model_sync+dhi]",
    ):
        assert classification in log


def test_duplicate_headers_survive_initial_response_and_cache_hit(metadata_server):
    port, _, _ = metadata_server

    for _ in range(2):
        status, headers, body = _request(port, "GET", "/cookies")
        assert status == 209
        set_cookies = [value for name, value in headers if name.lower() == "set-cookie"]
        assert len(set_cookies) == 2
        assert set_cookies[0].startswith("first=one;")
        assert set_cookies[1].startswith("second=two;")
        assert json.loads(body) == {"ok": True}


def test_invalid_over_limit_and_error_marker_responses_fail_closed(metadata_server):
    port, _, _ = metadata_server
    cases = (
        ("malformed", {"x-safe", "x-injected", "transfer-encoding"}),
        ("too-many", {"x-000", "strict-transport-security"}),
        ("too-large", {"x-fill", "cache-control"}),
        ("injected-marker", set()),
        ("oom-marker", set()),
    )

    for route, forbidden_headers in cases:
        for _ in range(2):
            status, headers, body = _request(port, "GET", f"/{route}")
            normalized = [(name.lower(), value) for name, value in headers]
            names = {name for name, _ in normalized}
            assert status == 500
            assert ("content-type", "application/json") in normalized
            assert ("content-length", str(len(body))) in normalized
            assert not names.intersection(forbidden_headers)
            assert body == b'{"error":"invalid native response metadata"}'
            assert b"original" not in body

        status, _, body = _request(port, "GET", f"/stats/{route}")
        assert status == 200
        assert json.loads(body) == {"calls": 2}
