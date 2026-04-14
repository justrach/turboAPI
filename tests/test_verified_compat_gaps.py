"""Focused regression reproducers for currently incomplete compatibility paths.

These tests are intentionally marked xfail so they document gaps without
breaking the main suite. When the underlying behavior is implemented, they
should xpass and be converted into normal passing tests.
"""

import os
import tempfile

import pytest
from turboapi import APIRouter, Depends, HTTPException, JSONResponse, TurboAPI
from turboapi.staticfiles import StaticFiles
from turboapi.testclient import TestClient


@pytest.mark.xfail(reason="Custom exception handlers are registered but not executed at runtime")
def test_custom_exception_handler_runs_in_testclient():
    app = TurboAPI(title="ExceptionHandlerRuntime")

    @app.exception_handler(ValueError)
    async def handle_value_error(request, exc):
        return JSONResponse(status_code=418, content={"detail": f"handled: {exc}"})

    @app.get("/boom")
    def boom():
        raise ValueError("kaboom")

    response = TestClient(app).get("/boom")

    assert response.status_code == 418
    assert response.json() == {"detail": "handled: kaboom"}


@pytest.mark.asyncio
@pytest.mark.xfail(reason="lifespan= is stored but not executed during ASGI lifespan events")
async def test_lifespan_callable_runs_for_startup_and_shutdown():
    events = []

    async def lifespan(_app):
        events.append("startup")
        yield
        events.append("shutdown")

    app = TurboAPI(title="LifespanRuntime", lifespan=lifespan)
    messages = iter(
        [
            {"type": "lifespan.startup"},
            {"type": "lifespan.shutdown"},
        ]
    )
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message["type"])

    await app({"type": "lifespan"}, receive, send)

    assert events == ["startup", "shutdown"]
    assert sent == ["lifespan.startup.complete", "lifespan.shutdown.complete"]


@pytest.mark.xfail(reason="Docs/OpenAPI URLs are configured but not served as routes")
def test_docs_and_openapi_urls_are_served():
    app = TurboAPI(title="DocsRuntime")

    @app.get("/")
    def root():
        return {"ok": True}

    client = TestClient(app)

    docs_response = client.get("/docs")
    openapi_response = client.get("/openapi.json")

    assert docs_response.status_code == 200
    assert openapi_response.status_code == 200
    assert openapi_response.json()["info"]["title"] == "DocsRuntime"


@pytest.mark.xfail(reason="Router-level dependencies are accepted but not enforced")
def test_router_level_dependencies_are_enforced():
    router = APIRouter(dependencies=[Depends(lambda: (_ for _ in ()).throw(HTTPException(401, "blocked")))])

    @router.get("/items")
    def list_items():
        return {"ok": True}

    app = TurboAPI(title="RouterDependencies")
    app.include_router(router)

    response = TestClient(app).get("/items")

    assert response.status_code == 401
    assert response.json() == {"detail": "blocked"}


@pytest.mark.xfail(reason="Mounted StaticFiles are stored but not dispatched end-to-end")
def test_mounted_static_files_are_served():
    app = TurboAPI(title="StaticMountRuntime")

    with tempfile.TemporaryDirectory() as tmpdir:
        asset_path = os.path.join(tmpdir, "hello.txt")
        with open(asset_path, "w") as f:
            f.write("hello from static")

        app.mount("/static", StaticFiles(directory=tmpdir), name="static")
        response = TestClient(app).get("/static/hello.txt")

    assert response.status_code == 200
    assert response.text == "hello from static"
