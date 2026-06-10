#!/usr/bin/env python3
"""
Tests for issue #142: Three HTML-serving rough edges in 1.0.29

Bug 1 — HTMLResponse.media_type doesn't reach the wire.
Bug 2 — noargs response cache drops custom headers / Content-Type.
Bug 3 — `from __future__ import annotations` silently breaks path-parameter binding.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from turboapi import TurboAPI  # noqa: E402
from turboapi.responses import HTMLResponse  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_app(app: TurboAPI) -> int:
    port = _free_port()
    t = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port), daemon=True)
    t.start()
    # Poll until ready
    for _ in range(50):
        try:
            requests.get(f"http://127.0.0.1:{port}/__healthz_probe__", timeout=0.1)
            break
        except Exception:
            time.sleep(0.05)
    time.sleep(0.2)
    return port


def test_bug1_html_response_content_type_on_first_request():
    """Bug 1: HTMLResponse on a noargs handler must emit text/html on the wire."""
    app = TurboAPI(title="bug1")

    @app.get("/")
    def home():
        return HTMLResponse("<h1>Hello</h1>")

    port = _start_app(app)
    r = requests.get(f"http://127.0.0.1:{port}/", timeout=2)
    ct = r.headers.get("Content-Type", "")
    assert "text/html" in ct, f"first request Content-Type is {ct!r}"
    assert r.text == "<h1>Hello</h1>"


def test_bug2_noargs_cache_preserves_content_type_on_replay():
    """Bug 2: cached noargs replays must keep the original Content-Type."""
    app = TurboAPI(title="bug2")

    @app.get("/page")
    def page():
        return HTMLResponse("<p>hi</p>")

    port = _start_app(app)
    # Hit the route a few times — second+ requests are served from the
    # noargs cache. All of them must report text/html.
    cts = []
    for _ in range(5):
        r = requests.get(f"http://127.0.0.1:{port}/page", timeout=2)
        cts.append(r.headers.get("Content-Type", ""))
        assert r.text == "<p>hi</p>"
    for i, ct in enumerate(cts):
        assert "text/html" in ct, f"request #{i} got Content-Type={ct!r}"


def test_bug3_future_annotations_path_param_str():
    """Bug 3: ``from __future__ import annotations`` must not break path binding."""
    app = TurboAPI(title="bug3-str")

    @app.get("/item/{item_id}")
    def get_item(item_id: str):
        return {"id": item_id}

    port = _start_app(app)
    r = requests.get(f"http://127.0.0.1:{port}/item/42", timeout=2)
    assert r.status_code == 200, r.text
    assert r.json() == {"id": "42"}


def test_bug3_future_annotations_path_param_int():
    """Bug 3: int path params must coerce correctly under PEP 563."""
    app = TurboAPI(title="bug3-int")

    @app.get("/n/{n}")
    def get_n(n: int):
        return {"n": n, "type": type(n).__name__}

    port = _start_app(app)
    r = requests.get(f"http://127.0.0.1:{port}/n/123", timeout=2)
    assert r.status_code == 200, r.text
    assert r.json() == {"n": 123, "type": "int"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
