"""Test Annotated[Type, Depends(...)] pattern — issue #51."""
from typing import Annotated

from turboapi import TurboAPI
from turboapi.security import Depends, get_depends
from turboapi.testclient import TestClient


def get_db():
    return {"connection": "fake_db"}


def get_current_user():
    return {"user": "alice"}


# Type aliases — the FastAPI-recommended pattern
DB = Annotated[dict, Depends(get_db)]
CurrentUser = Annotated[dict, Depends(get_current_user)]


# ── get_depends helper tests ────────────────────────────────────────────────


def test_get_depends_classic():
    """Classic pattern: def f(db = Depends(get_db))."""
    import inspect

    sig = inspect.signature(lambda db=Depends(get_db): None)
    param = list(sig.parameters.values())[0]
    dep = get_depends(param)
    assert dep is not None
    assert dep.dependency is get_db


def test_get_depends_annotated():
    """Annotated pattern: def f(db: Annotated[dict, Depends(get_db)])."""
    import inspect

    def handler(db: DB):
        pass

    sig = inspect.signature(handler)
    param = list(sig.parameters.values())[0]
    dep = get_depends(param)
    assert dep is not None
    assert dep.dependency is get_db


def test_get_depends_none():
    """No Depends at all."""
    import inspect

    sig = inspect.signature(lambda x: None)
    param = list(sig.parameters.values())[0]
    dep = get_depends(param)
    assert dep is None


# ── Integration: Annotated Depends resolves in handlers ──────────────────────


def test_annotated_depends_handler():
    """Handler with Annotated[Type, Depends(...)] should receive resolved value."""
    app = TurboAPI(title="test")

    @app.get("/items")
    def read_items(db: DB):
        return {"db": db}

    client = TestClient(app)
    resp = client.get("/items")
    assert resp.status_code == 200
    assert resp.json()["db"] == {"connection": "fake_db"}


def test_annotated_depends_multiple():
    """Multiple Annotated Depends in same handler."""
    app = TurboAPI(title="test")

    @app.get("/me")
    def read_me(db: DB, user: CurrentUser):
        return {"db": db, "user": user}

    client = TestClient(app)
    resp = client.get("/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["db"] == {"connection": "fake_db"}
    assert data["user"] == {"user": "alice"}


def test_annotated_depends_mixed():
    """Mix of classic Depends and Annotated Depends."""
    app = TurboAPI(title="test")

    @app.get("/mixed")
    def mixed(db: DB, user: dict = Depends(get_current_user)):
        return {"db": db, "user": user}

    client = TestClient(app)
    resp = client.get("/mixed")
    assert resp.status_code == 200
    data = resp.json()
    assert data["db"] == {"connection": "fake_db"}
    assert data["user"] == {"user": "alice"}


def test_classic_depends_still_works():
    """Classic pattern must not regress."""
    app = TurboAPI(title="test")

    @app.get("/classic")
    def classic(db: dict = Depends(get_db)):
        return {"db": db}

    client = TestClient(app)
    resp = client.get("/classic")
    assert resp.status_code == 200
    assert resp.json()["db"] == {"connection": "fake_db"}


# ── Route registration: Annotated Depends should NOT be classified as query params ──


def test_annotated_depends_not_in_query_params():
    """Annotated[Type, Depends(...)] should NOT appear in route's query_params."""
    app = TurboAPI(title="test")
    router = app  # TurboAPI is also a Router

    @router.get("/items")
    def read_items(db: DB):
        return {"db": db}

    # Find the registered route
    routes = app.routes
    assert len(routes) == 1
    route = routes[0]

    # db should NOT be in query_params
    assert "db" not in route.query_params, (
        f"Expected 'db' not in query_params, but got: {route.query_params}"
    )


def test_classic_depends_not_in_query_params():
    """Classic Depends() should also NOT appear in route's query_params."""
    app = TurboAPI(title="test")
    router = app

    @router.get("/items")
    def read_items(db: dict = Depends(get_db)):
        return {"db": db}

    routes = app.routes
    assert len(routes) == 1
    route = routes[0]

    assert "db" not in route.query_params


def test_router_with_prefix_and_annotated_depends():
    """Router prefix + Annotated Depends should work together."""
    from turboapi import Router

    app = TurboAPI(title="test")
    router = Router(prefix="/api")

    @router.get("/items")
    def read_items(db: DB):
        return {"db": db}

    app.include_router(router)

    routes = app.routes
    assert len(routes) == 1
    route = routes[0]
    assert route.path == "/api/items"
    assert "db" not in route.query_params
