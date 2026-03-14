#!/usr/bin/env python3
"""
Tests for Content-Length-aware body reading in the Zig HTTP server.

The Zig server reads headers first, then uses Content-Length to allocate
and read the full body from the stream. These tests exercise various
payload sizes and edge cases.
"""

import json
import threading
import time

import requests
from turboapi import TurboAPI

# Each test uses a unique port to avoid conflicts
_port_counter = 11200


def _next_port():
    global _port_counter
    _port_counter += 1
    return _port_counter


def _start_app(app, port):
    """Start app in a daemon thread and wait for it to be ready."""
    t = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port), daemon=True)
    t.start()
    time.sleep(2)
    return t


# ── Payload size tests ───────────────────────────────────────────────────────


def test_body_just_under_8kb():
    """Body that fits in a single 8KB read (no extra reads needed)."""
    port = _next_port()
    app = TurboAPI(title="Test <8KB")

    @app.post("/echo")
    def echo(data: dict):
        return {"keys": len(data), "ok": True}

    _start_app(app, port)

    # ~7KB payload
    payload = {f"key_{i}": "x" * 50 for i in range(100)}
    resp = requests.post(f"http://127.0.0.1:{port}/echo", json=payload)
    assert resp.status_code == 200
    result = resp.json()
    assert result["keys"] == 100
    assert result["ok"] is True


def test_body_exactly_8kb():
    """Body right around the 8KB boundary (edge case for buffer split)."""
    port = _next_port()
    app = TurboAPI(title="Test ~8KB")

    @app.post("/echo")
    def echo(data: dict):
        return {"size": len(json.dumps(data)), "ok": True}

    _start_app(app, port)

    # Build payload close to 8192 bytes
    payload = {"data": "A" * 7800}
    resp = requests.post(f"http://127.0.0.1:{port}/echo", json=payload)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_body_16kb():
    """16KB body — requires reading beyond the initial header buffer."""
    port = _next_port()
    app = TurboAPI(title="Test 16KB")

    @app.post("/echo")
    def echo(data: dict):
        return {"received_len": len(data.get("payload", "")), "ok": True}

    _start_app(app, port)

    payload = {"payload": "B" * 16000}
    resp = requests.post(f"http://127.0.0.1:{port}/echo", json=payload)
    assert resp.status_code == 200
    result = resp.json()
    assert result["received_len"] == 16000
    assert result["ok"] is True


def test_body_64kb():
    """64KB body — well beyond the old 8KB limit."""
    port = _next_port()
    app = TurboAPI(title="Test 64KB")

    @app.post("/echo")
    def echo(data: dict):
        return {"received_len": len(data.get("payload", "")), "ok": True}

    _start_app(app, port)

    payload = {"payload": "C" * 65000}
    resp = requests.post(f"http://127.0.0.1:{port}/echo", json=payload)
    assert resp.status_code == 200
    result = resp.json()
    assert result["received_len"] == 65000


def test_body_1mb():
    """1MB body — stress test for large payloads."""
    port = _next_port()
    app = TurboAPI(title="Test 1MB")

    @app.post("/echo")
    def echo(data: dict):
        return {"received_len": len(data.get("payload", "")), "ok": True}

    _start_app(app, port)

    payload = {"payload": "D" * (1024 * 1024)}
    resp = requests.post(f"http://127.0.0.1:{port}/echo", json=payload)
    assert resp.status_code == 200
    result = resp.json()
    assert result["received_len"] == 1024 * 1024


# ── Structured large payloads ────────────────────────────────────────────────


def test_large_json_array():
    """Large JSON array with many objects — tests body integrity end-to-end."""
    port = _next_port()
    app = TurboAPI(title="Test Large Array")

    @app.post("/process")
    def process(items: list):
        return {
            "count": len(items),
            "first_id": items[0]["id"] if items else None,
            "last_id": items[-1]["id"] if items else None,
        }

    _start_app(app, port)

    items = [{"id": i, "name": f"item_{i}", "value": i * 1.5} for i in range(5000)]
    resp = requests.post(f"http://127.0.0.1:{port}/process", json=items)
    assert resp.status_code == 200
    result = resp.json()
    assert result["count"] == 5000
    assert result["first_id"] == 0
    assert result["last_id"] == 4999


def test_deeply_nested_json():
    """Deeply nested JSON object — tests body parsing integrity."""
    port = _next_port()
    app = TurboAPI(title="Test Nested")

    @app.post("/echo")
    def echo(data: dict):
        # Walk down to verify nesting survived
        node = data
        depth = 0
        while "child" in node:
            node = node["child"]
            depth += 1
        return {"depth": depth, "leaf": node.get("value")}

    _start_app(app, port)

    # Build 50-level deep nesting
    payload = {"value": "leaf"}
    for i in range(50):
        payload = {"level": i, "child": payload}

    resp = requests.post(f"http://127.0.0.1:{port}/echo", json=payload)
    assert resp.status_code == 200
    result = resp.json()
    assert result["depth"] == 50
    assert result["leaf"] == "leaf"


# ── Edge cases ───────────────────────────────────────────────────────────────


def test_empty_body_get():
    """GET with no body — Content-Length absent or 0."""
    port = _next_port()
    app = TurboAPI(title="Test Empty GET")

    @app.get("/hello")
    def hello():
        return {"message": "hello"}

    _start_app(app, port)

    resp = requests.get(f"http://127.0.0.1:{port}/hello")
    assert resp.status_code == 200
    assert resp.json()["message"] == "hello"


def test_empty_body_post():
    """POST with empty body — should not crash."""
    port = _next_port()
    app = TurboAPI(title="Test Empty POST")

    @app.post("/empty")
    def empty():
        return {"received": "nothing"}

    _start_app(app, port)

    resp = requests.post(f"http://127.0.0.1:{port}/empty")
    assert resp.status_code == 200
    assert resp.json()["received"] == "nothing"


def test_unicode_body():
    """Body with multi-byte UTF-8 characters — Content-Length is in bytes, not chars."""
    port = _next_port()
    app = TurboAPI(title="Test Unicode")

    @app.post("/echo")
    def echo(data: dict):
        return {"text": data.get("text", ""), "ok": True}

    _start_app(app, port)

    # Mix of ASCII, 2-byte, 3-byte, and 4-byte UTF-8
    text = "Hello 世界! 🚀🎉" * 500
    payload = {"text": text}
    resp = requests.post(f"http://127.0.0.1:{port}/echo", json=payload)
    assert resp.status_code == 200
    assert resp.json()["text"] == text


def test_concurrent_large_bodies():
    """Multiple concurrent requests with large bodies — tests thread safety."""
    import concurrent.futures

    port = _next_port()
    app = TurboAPI(title="Test Concurrent")

    @app.post("/echo")
    def echo(data: dict):
        return {"id": data.get("id"), "len": len(data.get("payload", ""))}

    _start_app(app, port)

    def send_request(req_id):
        payload = {"id": req_id, "payload": "X" * 20000}
        resp = requests.post(f"http://127.0.0.1:{port}/echo", json=payload)
        return resp.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(send_request, i) for i in range(16)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 16
    for r in results:
        assert r["len"] == 20000


def test_body_with_many_headers():
    """Request with many custom headers + large body — tests header buffer not overflowing."""
    port = _next_port()
    app = TurboAPI(title="Test Many Headers")

    @app.post("/echo")
    def echo(data: dict):
        return {"ok": True, "payload_len": len(data.get("payload", ""))}

    _start_app(app, port)

    headers = {f"X-Custom-{i}": f"value-{i}" for i in range(30)}
    headers["Content-Type"] = "application/json"
    payload = {"payload": "H" * 10000}
    resp = requests.post(f"http://127.0.0.1:{port}/echo", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["payload_len"] == 10000
