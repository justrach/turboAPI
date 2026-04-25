"""Repro tests for issues #100–#104.

Each test encodes the exact gap described in the issue and must go
red-to-green when the corresponding fix lands.
"""

import asyncio
import os
import tempfile

from turboapi import (
    APIRouter,
    Depends,
    HTTPException,
    JSONResponse,
    TurboAPI,
)
from turboapi.staticfiles import StaticFiles
from turboapi.testclient import TestClient

# ------------------------------------------------------------------
# Issue #100 — custom exception handlers ignored by TestClient
# ------------------------------------------------------------------


class _Kaboom(Exception):
    pass


def test_custom_exception_handler_runs_in_testclient():
    """Registered exception handler must intercept a matching raise."""
    app = TurboAPI(title="ExcHandlerRepro")

    @app.exception_handler(_Kaboom)
    async def handle_kaboom(request, exc):
        return JSONResponse(status_code=418, content={"detail": f"handled: {exc}"})

    @app.get("/boom")
    def boom():
        raise _Kaboom("kaboom")

    client = TestClient(app)
    resp = client.get("/boom")
    assert resp.status_code == 418, f"Expected 418, got {resp.status_code}"
    assert resp.json() == {"detail": "handled: kaboom"}


# ------------------------------------------------------------------
# Issue #101 — lifespan callable stored but not executed
# ------------------------------------------------------------------


def test_lifespan_callable_runs_for_startup_and_shutdown():
    """The lifespan async-generator must execute startup/shutdown phases."""
    events = []

    async def lifespan(app):
        events.append("startup")
        yield
        events.append("shutdown")

    app = TurboAPI(title="LifespanRepro", lifespan=lifespan)

    # Drive the ASGI lifespan protocol manually
    async def _drive():
        msg_queue = asyncio.Queue()
        sent = []

        await msg_queue.put({"type": "lifespan.startup"})
        await msg_queue.put({"type": "lifespan.shutdown"})

        async def receive():
            return await msg_queue.get()

        async def send(message):
            sent.append(message)

        await app({"type": "lifespan"}, receive, send)
        return sent

    sent = asyncio.run(_drive())
    assert "startup" in events, f"startup not fired, events={events}"
    assert "shutdown" in events, f"shutdown not fired, events={events}"
    types = [m["type"] for m in sent]
    assert "lifespan.startup.complete" in types
    assert "lifespan.shutdown.complete" in types


# ------------------------------------------------------------------
# Issue #102 — /docs and /openapi.json not served over HTTP
# ------------------------------------------------------------------


def test_docs_and_openapi_urls_are_served():
    """GET /docs and GET /openapi.json should return 200."""
    app = TurboAPI(title="DocsRepro", version="1.0.0")

    @app.get("/health")
    def health():
        return {"ok": True}

    client = TestClient(app)

    openapi_resp = client.get("/openapi.json")
    assert openapi_resp.status_code == 200, f"/openapi.json returned {openapi_resp.status_code}"
    schema = openapi_resp.json()
    assert schema["info"]["title"] == "DocsRepro"

    docs_resp = client.get("/docs")
    assert docs_resp.status_code == 200, f"/docs returned {docs_resp.status_code}"
    assert "text/html" in docs_resp.headers.get("content-type", "")


# ------------------------------------------------------------------
# Issue #103 — router-level dependencies accepted but not enforced
# ------------------------------------------------------------------


def _require_auth():
    raise HTTPException(status_code=401, detail="Not authenticated")


def test_router_level_dependencies_are_enforced():
    """Router-level deps must execute and may block the request."""
    app = TurboAPI(title="RouterDepRepro")
    router = APIRouter(prefix="/guarded", dependencies=[Depends(_require_auth)])

    @router.get("/resource")
    def resource():
        return {"data": "secret"}

    app.include_router(router, prefix="/api")

    client = TestClient(app)
    resp = client.get("/api/guarded/resource")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
    assert resp.json()["detail"] == "Not authenticated"


# ------------------------------------------------------------------
# Issue #104 — mounted StaticFiles stored but not served
# ------------------------------------------------------------------


def test_mounted_static_files_are_served():
    """GET /static/hello.txt should return file contents."""
    with tempfile.TemporaryDirectory() as tmpdir:
        hello = os.path.join(tmpdir, "hello.txt")
        with open(hello, "w") as f:
            f.write("hello world")

        app = TurboAPI(title="StaticRepro")
        app.mount("/static", StaticFiles(directory=tmpdir), name="static")

        client = TestClient(app)
        resp = client.get("/static/hello.txt")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert resp.text == "hello world"
