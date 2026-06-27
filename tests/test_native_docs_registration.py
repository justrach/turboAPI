import json

from turboapi import TurboAPI


class FakeTurboServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.static_routes = []
        self.fast_routes = []
        self.native_routes = []
        self.db_routes = []

    def add_static_route(self, method, path, status, content_type, body):
        self.static_routes.append((method, path, status, content_type, body))

    def add_route_fast(self, *args):
        self.fast_routes.append(args)

    def add_route_async_fast(self, *args):
        self.fast_routes.append(args)

    def add_native_route(self, *args):
        self.native_routes.append(args)

    def add_db_route(self, *args):
        self.db_routes.append(args)

    def enable_response_cache(self):
        pass


def test_native_server_registers_docs_and_openapi(monkeypatch):
    import turboapi.zig_integration as zi

    monkeypatch.setattr(zi, "NATIVE_CORE_AVAILABLE", True)
    monkeypatch.setattr(zi.turbonet, "TurboServer", FakeTurboServer)

    app = TurboAPI(title="Native Docs Test", version="9.9.9")

    @app.get("/items/{item_id}")
    def get_item(item_id: int):
        return {"item_id": item_id}

    assert app._initialize_zig_server("127.0.0.1", 0) is True

    routes = {path: (method, status, content_type, body) for method, path, status, content_type, body in app.zig_server.static_routes}
    assert "/openapi.json" in routes
    assert "/docs" in routes
    assert "/redoc" in routes

    _, status, content_type, body = routes["/openapi.json"]
    assert status == 200
    assert content_type == "application/json"
    schema = json.loads(body)
    assert schema["info"]["title"] == "Native Docs Test"
    assert schema["info"]["version"] == "9.9.9"

    assert "SwaggerUIBundle" in routes["/docs"][3]
    assert "/openapi.json" in routes["/docs"][3]
    assert "redoc" in routes["/redoc"][3].lower()


def test_native_server_respects_disabled_docs_urls(monkeypatch):
    import turboapi.zig_integration as zi

    monkeypatch.setattr(zi, "NATIVE_CORE_AVAILABLE", True)
    monkeypatch.setattr(zi.turbonet, "TurboServer", FakeTurboServer)

    app = TurboAPI(docs_url=None, redoc_url=None, openapi_url=None)
    assert app._initialize_zig_server("127.0.0.1", 0) is True

    assert app.zig_server.static_routes == []
