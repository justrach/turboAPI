"""Docs endpoints are registered and served out of the box (FastAPI parity)."""

from turboapi import TurboAPI


def _registered_paths(app):
    return {(r.method.value, r.path) for r in app.registry.get_routes()}


def test_docs_routes_registered_by_default():
    app = TurboAPI(title="Docs")
    paths = _registered_paths(app)
    assert ("GET", "/openapi.json") in paths
    assert ("GET", "/docs") in paths
    assert ("GET", "/redoc") in paths


def test_docs_routes_can_be_disabled():
    app = TurboAPI(title="NoDocs", docs_url=None, redoc_url=None, openapi_url=None)
    assert _registered_paths(app) == set()


def test_docs_and_redoc_require_openapi_url():
    app = TurboAPI(title="NoSchema", openapi_url=None)
    assert _registered_paths(app) == set()


def test_docs_routes_excluded_from_schema():
    app = TurboAPI(title="Docs")

    @app.get("/ping")
    def ping():
        return {"ok": True}

    schema = app.openapi()
    assert "/ping" in schema["paths"]
    assert "/openapi.json" not in schema["paths"]
    assert "/docs" not in schema["paths"]
    assert "/redoc" not in schema["paths"]


def test_docs_handlers_return_content():
    app = TurboAPI(title="Docs")
    handlers = {r.path: r.handler for r in app.registry.get_routes()}

    schema = handlers["/openapi.json"]()
    assert schema["info"]["title"] == "Docs"

    swagger = handlers["/docs"]()
    assert "swagger" in str(getattr(swagger, "content", swagger)).lower()

    redoc = handlers["/redoc"]()
    assert "redoc" in str(getattr(redoc, "content", redoc)).lower()
