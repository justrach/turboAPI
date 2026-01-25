"""Comprehensive tests verifying TurboAPI has FastAPI feature parity.

Tests cover: routing, params, responses, security, middleware, background tasks,
WebSocket, exception handling, OpenAPI, TestClient, static files, lifespan, etc.
"""

import json
import os
import tempfile
import pytest

from turboapi import (
    TurboAPI, APIRouter, Request,
    Body, Cookie, File, Form, Header, Path, Query, UploadFile,
    FileResponse, HTMLResponse, JSONResponse, PlainTextResponse,
    RedirectResponse, Response, StreamingResponse,
    Depends, Security, HTTPException, HTTPBasic, HTTPBearer, HTTPBasicCredentials,
    OAuth2PasswordBearer, OAuth2AuthorizationCodeBearer,
    APIKeyHeader, APIKeyQuery, APIKeyCookie, SecurityScopes,
    BackgroundTasks, WebSocket, WebSocketDisconnect,
    RequestValidationError, WebSocketException,
    CORSMiddleware, GZipMiddleware, TrustedHostMiddleware, HTTPSRedirectMiddleware, Middleware,
    jsonable_encoder, status,
)
from turboapi.testclient import TestClient
from turboapi.staticfiles import StaticFiles
from turboapi.openapi import generate_openapi_schema


# ============================================================
# Test: Core Routing
# ============================================================

class TestRouting:
    def setup_method(self):
        self.app = TurboAPI(title="TestApp", version="1.0.0")

    def test_get_route(self):
        @self.app.get("/")
        def root():
            return {"message": "Hello"}

        client = TestClient(self.app)
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"message": "Hello"}

    def test_post_route(self):
        @self.app.post("/items")
        def create_item(name: str, price: float):
            return {"name": name, "price": price}

        client = TestClient(self.app)
        response = client.post("/items", json={"name": "Widget", "price": 9.99})
        assert response.status_code == 200
        assert response.json()["name"] == "Widget"
        assert response.json()["price"] == 9.99

    def test_put_route(self):
        @self.app.put("/items/{item_id}")
        def update_item(item_id: int, name: str):
            return {"item_id": item_id, "name": name}

        client = TestClient(self.app)
        response = client.put("/items/42", json={"name": "Updated"})
        assert response.status_code == 200
        assert response.json()["item_id"] == 42

    def test_delete_route(self):
        @self.app.delete("/items/{item_id}")
        def delete_item(item_id: int):
            return {"deleted": item_id}

        client = TestClient(self.app)
        response = client.delete("/items/5")
        assert response.status_code == 200
        assert response.json()["deleted"] == 5

    def test_patch_route(self):
        @self.app.patch("/items/{item_id}")
        def patch_item(item_id: int, name: str):
            return {"item_id": item_id, "name": name}

        client = TestClient(self.app)
        response = client.patch("/items/3", json={"name": "Patched"})
        assert response.status_code == 200
        assert response.json()["name"] == "Patched"


# ============================================================
# Test: Path Parameters
# ============================================================

class TestPathParams:
    def setup_method(self):
        self.app = TurboAPI(title="PathParamTest")

    def test_int_path_param(self):
        @self.app.get("/users/{user_id}")
        def get_user(user_id: int):
            return {"user_id": user_id, "type": type(user_id).__name__}

        client = TestClient(self.app)
        response = client.get("/users/123")
        assert response.json()["user_id"] == 123
        assert response.json()["type"] == "int"

    def test_str_path_param(self):
        @self.app.get("/users/{username}")
        def get_user_by_name(username: str):
            return {"username": username}

        client = TestClient(self.app)
        response = client.get("/users/alice")
        assert response.json()["username"] == "alice"

    def test_multiple_path_params(self):
        @self.app.get("/users/{user_id}/posts/{post_id}")
        def get_post(user_id: int, post_id: int):
            return {"user_id": user_id, "post_id": post_id}

        client = TestClient(self.app)
        response = client.get("/users/1/posts/42")
        assert response.json() == {"user_id": 1, "post_id": 42}


# ============================================================
# Test: Query Parameters
# ============================================================

class TestQueryParams:
    def setup_method(self):
        self.app = TurboAPI(title="QueryParamTest")

    def test_required_query_param(self):
        @self.app.get("/search")
        def search(q: str):
            return {"query": q}

        client = TestClient(self.app)
        response = client.get("/search", params={"q": "hello"})
        assert response.json()["query"] == "hello"

    def test_optional_query_param_with_default(self):
        @self.app.get("/items")
        def list_items(skip: int = 0, limit: int = 10):
            return {"skip": skip, "limit": limit}

        client = TestClient(self.app)
        response = client.get("/items", params={"skip": "5", "limit": "20"})
        assert response.json() == {"skip": 5, "limit": 20}

    def test_query_param_type_coercion(self):
        @self.app.get("/filter")
        def filter_items(price: float, active: bool):
            return {"price": price, "active": active}

        client = TestClient(self.app)
        response = client.get("/filter", params={"price": "19.99", "active": "true"})
        assert response.json()["price"] == 19.99
        assert response.json()["active"] is True


# ============================================================
# Test: Response Types
# ============================================================

class TestResponses:
    def test_json_response(self):
        resp = JSONResponse(content={"key": "value"})
        assert resp.status_code == 200
        assert resp.media_type == "application/json"
        assert json.loads(resp.body) == {"key": "value"}

    def test_html_response(self):
        resp = HTMLResponse(content="<h1>Hello</h1>")
        assert resp.status_code == 200
        assert resp.media_type == "text/html"
        assert resp.body == b"<h1>Hello</h1>"

    def test_plain_text_response(self):
        resp = PlainTextResponse(content="Hello World")
        assert resp.status_code == 200
        assert resp.media_type == "text/plain"

    def test_redirect_response(self):
        resp = RedirectResponse(url="/new-path")
        assert resp.status_code == 307
        assert resp.headers["location"] == "/new-path"

    def test_redirect_response_custom_status(self):
        resp = RedirectResponse(url="/moved", status_code=301)
        assert resp.status_code == 301

    def test_streaming_response(self):
        async def generate():
            for i in range(3):
                yield f"chunk{i}"

        resp = StreamingResponse(generate(), media_type="text/event-stream")
        assert resp.status_code == 200
        assert resp.media_type == "text/event-stream"

    def test_file_response(self):
        # Create a temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("file content")
            path = f.name

        try:
            resp = FileResponse(path, filename="download.txt")
            assert resp.status_code == 200
            assert resp.body == b"file content"
            assert "attachment" in resp.headers["content-disposition"]
            assert "download.txt" in resp.headers["content-disposition"]
        finally:
            os.unlink(path)

    def test_response_set_cookie(self):
        resp = Response(content="Hello")
        resp.set_cookie("session", "abc123", httponly=True)
        assert "session=abc123" in resp.headers["set-cookie"]
        assert "HttpOnly" in resp.headers["set-cookie"]

    def test_response_handler_returns_response(self):
        app = TurboAPI(title="ResponseTest")

        @app.get("/html")
        def html_page():
            return HTMLResponse(content="<p>Hello</p>")

        client = TestClient(app)
        response = client.get("/html")
        assert response.status_code == 200
        assert response.content == b"<p>Hello</p>"


# ============================================================
# Test: Background Tasks
# ============================================================

class TestBackgroundTasks:
    def test_background_task_runs(self):
        results = []

        app = TurboAPI(title="BGTest")

        @app.post("/notify")
        def notify(background_tasks: BackgroundTasks):
            background_tasks.add_task(results.append, "task_ran")
            return {"message": "Notification queued"}

        client = TestClient(app)
        response = client.post("/notify", json={})
        assert response.status_code == 200
        assert response.json()["message"] == "Notification queued"
        assert "task_ran" in results

    def test_background_task_with_kwargs(self):
        results = {}

        def store_result(key: str, value: str):
            results[key] = value

        tasks = BackgroundTasks()
        tasks.add_task(store_result, key="name", value="Alice")
        tasks.run_tasks()
        assert results == {"name": "Alice"}


# ============================================================
# Test: Dependency Injection
# ============================================================

class TestDependencyInjection:
    def test_depends_class(self):
        def get_db():
            return {"connection": "active"}

        dep = Depends(get_db)
        assert dep.dependency is get_db
        assert dep.use_cache is True

    def test_depends_no_cache(self):
        def get_config():
            return {}

        dep = Depends(get_config, use_cache=False)
        assert dep.use_cache is False


# ============================================================
# Test: Security
# ============================================================

class TestSecurity:
    def test_oauth2_password_bearer(self):
        oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")
        assert oauth2_scheme.tokenUrl == "/token"

    def test_oauth2_authorization_code_bearer(self):
        oauth2_scheme = OAuth2AuthorizationCodeBearer(
            authorizationUrl="/authorize",
            tokenUrl="/token",
        )
        assert oauth2_scheme.authorizationUrl == "/authorize"
        assert oauth2_scheme.tokenUrl == "/token"

    def test_http_basic(self):
        basic = HTTPBasic(scheme_name="HTTPBasic")
        assert basic.scheme_name == "HTTPBasic"

    def test_http_bearer(self):
        bearer = HTTPBearer(scheme_name="HTTPBearer")
        assert bearer.scheme_name == "HTTPBearer"

    def test_api_key_header(self):
        api_key = APIKeyHeader(name="X-API-Key")
        assert api_key.name == "X-API-Key"

    def test_api_key_query(self):
        api_key = APIKeyQuery(name="api_key")
        assert api_key.name == "api_key"

    def test_api_key_cookie(self):
        api_key = APIKeyCookie(name="session")
        assert api_key.name == "session"

    def test_security_scopes(self):
        scopes = SecurityScopes(scopes=["read", "write"])
        assert "read" in scopes.scopes
        assert "write" in scopes.scopes

    def test_http_basic_credentials(self):
        creds = HTTPBasicCredentials(username="admin", password="secret")
        assert creds.username == "admin"
        assert creds.password == "secret"


# ============================================================
# Test: HTTPException
# ============================================================

class TestHTTPException:
    def test_exception_creation(self):
        exc = HTTPException(status_code=404, detail="Not found")
        assert exc.status_code == 404
        assert exc.detail == "Not found"

    def test_exception_with_headers(self):
        exc = HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
        assert exc.headers["WWW-Authenticate"] == "Bearer"

    def test_exception_in_handler(self):
        app = TurboAPI(title="ExcTest")

        @app.get("/protected")
        def protected():
            raise HTTPException(status_code=403, detail="Forbidden")

        client = TestClient(app)
        response = client.get("/protected")
        assert response.status_code == 403
        assert response.json()["detail"] == "Forbidden"


# ============================================================
# Test: Middleware
# ============================================================

class TestMiddleware:
    def test_add_cors_middleware(self):
        from turboapi.middleware import CORSMiddleware
        app = TurboAPI(title="CORSTest")
        app.add_middleware(CORSMiddleware, origins=["http://localhost:3000"])
        assert len(app.middleware_stack) == 1

    def test_add_gzip_middleware(self):
        from turboapi.middleware import GZipMiddleware
        app = TurboAPI(title="GZipTest")
        app.add_middleware(GZipMiddleware, minimum_size=500)
        assert len(app.middleware_stack) == 1

    def test_add_trusted_host_middleware(self):
        from turboapi.middleware import TrustedHostMiddleware
        app = TurboAPI(title="THTest")
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["example.com"])
        assert len(app.middleware_stack) == 1


# ============================================================
# Test: APIRouter
# ============================================================

class TestAPIRouter:
    def test_router_creation(self):
        router = APIRouter()
        assert router is not None

    def test_router_with_routes(self):
        router = APIRouter()

        @router.get("/items")
        def list_items():
            return [{"id": 1}]

        @router.post("/items")
        def create_item(name: str):
            return {"name": name}

        assert len(router.registry.get_routes()) == 2

    def test_include_router(self):
        app = TurboAPI(title="RouterTest")
        router = APIRouter()

        @router.get("/items")
        def list_items():
            return []

        app.include_router(router, prefix="/api/v1")
        routes = app.registry.get_routes()
        paths = [r.path for r in routes]
        assert "/api/v1/items" in paths


# ============================================================
# Test: Lifecycle Events
# ============================================================

class TestLifecycleEvents:
    def test_startup_event(self):
        app = TurboAPI(title="LifecycleTest")
        started = []

        @app.on_event("startup")
        def on_startup():
            started.append(True)

        assert len(app.startup_handlers) == 1

    def test_shutdown_event(self):
        app = TurboAPI(title="LifecycleTest")
        stopped = []

        @app.on_event("shutdown")
        def on_shutdown():
            stopped.append(True)

        assert len(app.shutdown_handlers) == 1

    def test_lifespan_parameter(self):
        async def lifespan(app):
            yield

        app = TurboAPI(title="LifespanTest", lifespan=lifespan)
        assert app._lifespan is lifespan


# ============================================================
# Test: OpenAPI Schema
# ============================================================

class TestOpenAPI:
    def test_openapi_schema_generation(self):
        app = TurboAPI(title="OpenAPITest", version="2.0.0")

        @app.get("/items/{item_id}")
        def get_item(item_id: int, q: str = None):
            return {"item_id": item_id}

        schema = generate_openapi_schema(app)
        assert schema["openapi"] == "3.1.0"
        assert schema["info"]["title"] == "OpenAPITest"
        assert schema["info"]["version"] == "2.0.0"
        assert "/items/{item_id}" in schema["paths"]

    def test_openapi_with_post(self):
        app = TurboAPI(title="OpenAPIPost")

        @app.post("/items")
        def create_item(name: str, price: float):
            return {"name": name, "price": price}

        schema = generate_openapi_schema(app)
        assert "post" in schema["paths"]["/items"]
        operation = schema["paths"]["/items"]["post"]
        assert "requestBody" in operation

    def test_app_openapi_method(self):
        app = TurboAPI(title="AppOpenAPI")

        @app.get("/")
        def root():
            return {}

        schema = app.openapi()
        assert schema["info"]["title"] == "AppOpenAPI"
        # Cached
        assert app.openapi() is schema


# ============================================================
# Test: WebSocket
# ============================================================

class TestWebSocket:
    def test_websocket_decorator(self):
        app = TurboAPI(title="WSTest")

        @app.websocket("/ws")
        async def ws_endpoint(websocket: WebSocket):
            await websocket.accept()

        assert "/ws" in app._websocket_routes

    def test_websocket_disconnect_exception(self):
        exc = WebSocketDisconnect(code=1001, reason="Going away")
        assert exc.code == 1001
        assert exc.reason == "Going away"

    @pytest.mark.asyncio
    async def test_websocket_send_receive(self):
        ws = WebSocket()
        await ws.accept()
        assert ws.client_state == "connected"

        await ws._receive_queue.put({"type": "text", "data": "hello"})
        msg = await ws.receive_text()
        assert msg == "hello"

    @pytest.mark.asyncio
    async def test_websocket_send_json(self):
        ws = WebSocket()
        await ws.accept()
        await ws.send_json({"key": "value"})

        sent = await ws._send_queue.get()
        assert sent["type"] == "text"
        assert json.loads(sent["data"]) == {"key": "value"}


# ============================================================
# Test: Static Files
# ============================================================

class TestStaticFiles:
    def test_static_files_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            static = StaticFiles(directory=tmpdir)
            assert static.directory is not None

    def test_static_files_get_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file
            test_file = os.path.join(tmpdir, "test.txt")
            with open(test_file, "w") as f:
                f.write("hello static")

            static = StaticFiles(directory=tmpdir)
            result = static.get_file("test.txt")
            assert result is not None
            content, content_type, size = result
            assert content == b"hello static"
            assert "text" in content_type

    def test_static_files_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            static = StaticFiles(directory=tmpdir)
            assert static.get_file("nonexistent.txt") is None

    def test_static_files_path_traversal_protection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            static = StaticFiles(directory=tmpdir)
            assert static.get_file("../../etc/passwd") is None

    def test_mount_static_files(self):
        app = TurboAPI(title="MountTest")
        with tempfile.TemporaryDirectory() as tmpdir:
            app.mount("/static", StaticFiles(directory=tmpdir), name="static")
            assert "/static" in app._mounts


# ============================================================
# Test: Exception Handlers
# ============================================================

class TestExceptionHandlers:
    def test_register_exception_handler(self):
        app = TurboAPI(title="ExcHandlerTest")

        @app.exception_handler(ValueError)
        async def handle_value_error(request, exc):
            return JSONResponse(status_code=400, content={"detail": str(exc)})

        assert ValueError in app._exception_handlers


# ============================================================
# Test: Parameter Marker Classes
# ============================================================

class TestParameterMarkers:
    def test_query_marker(self):
        q = Query(min_length=3, max_length=50)
        assert q.min_length == 3
        assert q.max_length == 50

    def test_path_marker(self):
        p = Path(gt=0, description="Item ID")
        assert p.gt == 0
        assert p.description == "Item ID"

    def test_body_marker(self):
        b = Body(embed=True)
        assert b.embed is True
        assert b.media_type == "application/json"

    def test_header_marker(self):
        h = Header(convert_underscores=True)
        assert h.convert_underscores is True

    def test_cookie_marker(self):
        c = Cookie(alias="session_id")
        assert c.alias == "session_id"

    def test_form_marker(self):
        f = Form(min_length=1)
        assert f.min_length == 1
        assert f.media_type == "application/x-www-form-urlencoded"

    def test_file_marker(self):
        f = File(max_length=1024 * 1024)
        assert f.max_length == 1024 * 1024
        assert f.media_type == "multipart/form-data"

    def test_upload_file(self):
        uf = UploadFile(filename="test.png", content_type="image/png")
        assert uf.filename == "test.png"
        assert uf.content_type == "image/png"


# ============================================================
# Test: TestClient
# ============================================================

class TestTestClient:
    def test_basic_get(self):
        app = TurboAPI(title="ClientTest")

        @app.get("/hello")
        def hello():
            return {"greeting": "Hello World"}

        client = TestClient(app)
        response = client.get("/hello")
        assert response.status_code == 200
        assert response.json()["greeting"] == "Hello World"
        assert response.is_success

    def test_post_with_json(self):
        app = TurboAPI(title="ClientTest")

        @app.post("/users")
        def create_user(name: str, age: int):
            return {"name": name, "age": age}

        client = TestClient(app)
        response = client.post("/users", json={"name": "Alice", "age": 30})
        assert response.status_code == 200
        assert response.json()["name"] == "Alice"
        assert response.json()["age"] == 30

    def test_404_for_missing_route(self):
        app = TurboAPI(title="ClientTest")
        client = TestClient(app)
        response = client.get("/nonexistent")
        assert response.status_code == 404

    def test_query_params(self):
        app = TurboAPI(title="ClientTest")

        @app.get("/search")
        def search(q: str, limit: int = 10):
            return {"q": q, "limit": limit}

        client = TestClient(app)
        response = client.get("/search", params={"q": "test", "limit": "5"})
        assert response.json()["q"] == "test"
        assert response.json()["limit"] == 5


# ============================================================
# Test: Async Handlers
# ============================================================

class TestAsyncHandlers:
    def test_async_get_handler(self):
        app = TurboAPI(title="AsyncTest")

        @app.get("/async")
        async def async_handler():
            return {"async": True}

        client = TestClient(app)
        response = client.get("/async")
        assert response.status_code == 200
        assert response.json()["async"] is True

    def test_async_post_handler(self):
        app = TurboAPI(title="AsyncTest")

        @app.post("/async-create")
        async def async_create(name: str):
            return {"name": name, "created": True}

        client = TestClient(app)
        response = client.post("/async-create", json={"name": "Bob"})
        assert response.status_code == 200
        assert response.json()["name"] == "Bob"


# ============================================================
# Test: FastAPI 1:1 Export Parity
# ============================================================

class TestFastAPIExportParity:
    """Verify TurboAPI has all FastAPI exports for 1:1 compatibility."""

    # FastAPI core exports (from fastapi import X)
    FASTAPI_CORE_EXPORTS = {
        # Core - map FastAPI names to TurboAPI equivalents
        "FastAPI": "TurboAPI",
        "APIRouter": "APIRouter",
        "Request": "Request",
        "Response": "Response",
        "WebSocket": "WebSocket",
        "WebSocketDisconnect": "WebSocketDisconnect",
        # Parameters
        "Body": "Body",
        "Cookie": "Cookie",
        "Depends": "Depends",
        "File": "File",
        "Form": "Form",
        "Header": "Header",
        "Path": "Path",
        "Query": "Query",
        "Security": "Security",
        # Utilities
        "BackgroundTasks": "BackgroundTasks",
        "UploadFile": "UploadFile",
        # Exceptions
        "HTTPException": "HTTPException",
        "WebSocketException": "WebSocketException",
        # Status
        "status": "status",
    }

    def test_all_fastapi_core_exports_available(self):
        """Verify all FastAPI core exports exist in TurboAPI."""
        import turboapi

        missing = []
        for fastapi_name, turbo_name in self.FASTAPI_CORE_EXPORTS.items():
            if not hasattr(turboapi, turbo_name):
                missing.append(f"{fastapi_name} -> {turbo_name}")

        assert not missing, f"Missing FastAPI exports: {missing}"

    def test_security_dependency_with_scopes(self):
        """Test Security works like FastAPI's Security with scopes."""
        oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
        sec = Security(oauth2_scheme, scopes=["read", "write"])

        assert sec.dependency == oauth2_scheme
        assert sec.scopes == ["read", "write"]
        assert sec.security_scopes.scopes == ["read", "write"]
        assert sec.security_scopes.scope_str == "read write"

    def test_request_validation_error(self):
        """Test RequestValidationError matches FastAPI."""
        errors = [
            {"loc": ["body", "name"], "msg": "field required", "type": "value_error.missing"},
            {"loc": ["query", "page"], "msg": "must be > 0", "type": "value_error"},
        ]
        exc = RequestValidationError(errors=errors, body={"incomplete": "data"})

        assert exc.errors() == errors
        assert exc.body == {"incomplete": "data"}

    def test_websocket_exception(self):
        """Test WebSocketException matches FastAPI."""
        exc = WebSocketException(code=1008, reason="Policy violation")
        assert exc.code == 1008
        assert exc.reason == "Policy violation"

    def test_status_module_http_codes(self):
        """Test status module has all standard HTTP codes."""
        # Informational
        assert status.HTTP_100_CONTINUE == 100
        assert status.HTTP_101_SWITCHING_PROTOCOLS == 101

        # Success
        assert status.HTTP_200_OK == 200
        assert status.HTTP_201_CREATED == 201
        assert status.HTTP_202_ACCEPTED == 202
        assert status.HTTP_204_NO_CONTENT == 204

        # Redirection
        assert status.HTTP_301_MOVED_PERMANENTLY == 301
        assert status.HTTP_302_FOUND == 302
        assert status.HTTP_304_NOT_MODIFIED == 304
        assert status.HTTP_307_TEMPORARY_REDIRECT == 307
        assert status.HTTP_308_PERMANENT_REDIRECT == 308

        # Client errors
        assert status.HTTP_400_BAD_REQUEST == 400
        assert status.HTTP_401_UNAUTHORIZED == 401
        assert status.HTTP_403_FORBIDDEN == 403
        assert status.HTTP_404_NOT_FOUND == 404
        assert status.HTTP_405_METHOD_NOT_ALLOWED == 405
        assert status.HTTP_409_CONFLICT == 409
        assert status.HTTP_422_UNPROCESSABLE_ENTITY == 422
        assert status.HTTP_429_TOO_MANY_REQUESTS == 429

        # Server errors
        assert status.HTTP_500_INTERNAL_SERVER_ERROR == 500
        assert status.HTTP_502_BAD_GATEWAY == 502
        assert status.HTTP_503_SERVICE_UNAVAILABLE == 503
        assert status.HTTP_504_GATEWAY_TIMEOUT == 504

    def test_jsonable_encoder_basic_types(self):
        """Test jsonable_encoder handles basic types."""
        from datetime import datetime, date
        from uuid import UUID
        from enum import Enum

        class Color(Enum):
            RED = "red"

        data = {
            "string": "hello",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "date": date(2024, 1, 15),
            "datetime": datetime(2024, 1, 15, 10, 30, 0),
            "uuid": UUID("12345678-1234-5678-1234-567812345678"),
            "enum": Color.RED,
            "bytes": b"binary",
        }

        result = jsonable_encoder(data)

        assert result["string"] == "hello"
        assert result["int"] == 42
        assert result["date"] == "2024-01-15"
        assert result["datetime"] == "2024-01-15T10:30:00"
        assert result["uuid"] == "12345678-1234-5678-1234-567812345678"
        assert result["enum"] == "red"
        assert result["bytes"] == "binary"

    def test_jsonable_encoder_with_model(self):
        """Test jsonable_encoder with dhi BaseModel."""
        from dhi import BaseModel

        class User(BaseModel):
            name: str
            age: int

        user = User(name="Alice", age=30)
        result = jsonable_encoder(user)

        assert result["name"] == "Alice"
        assert result["age"] == 30

    def test_jsonable_encoder_exclude_none(self):
        """Test jsonable_encoder exclude_none parameter."""
        data = {"name": "Alice", "email": None, "age": 30}
        result = jsonable_encoder(data, exclude_none=True)

        assert "name" in result
        assert "email" not in result
        assert "age" in result


class TestMiddlewareExportParity:
    """Test middleware exports match FastAPI/Starlette."""

    def test_middleware_classes_available(self):
        """Test all middleware classes are exported."""
        import turboapi

        middleware_classes = [
            "Middleware",
            "CORSMiddleware",
            "GZipMiddleware",
            "TrustedHostMiddleware",
            "HTTPSRedirectMiddleware",
        ]

        missing = []
        for name in middleware_classes:
            if not hasattr(turboapi, name):
                missing.append(name)

        assert not missing, f"Missing middleware: {missing}"

    def test_cors_middleware_params(self):
        """Test CORSMiddleware has FastAPI-compatible parameters."""
        cors = CORSMiddleware(
            allow_origins=["http://localhost:3000"],
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization"],
            expose_headers=["X-Custom-Header"],
            max_age=600,
        )

        assert cors.allow_origins == ["http://localhost:3000"]
        assert cors.allow_credentials is True
        assert "GET" in cors.allow_methods
        assert cors.max_age == 600

    def test_gzip_middleware_params(self):
        """Test GZipMiddleware has FastAPI-compatible parameters."""
        gzip = GZipMiddleware(minimum_size=1000, compresslevel=6)

        assert gzip.minimum_size == 1000
        assert gzip.compresslevel == 6

    def test_trusted_host_middleware_params(self):
        """Test TrustedHostMiddleware has FastAPI-compatible parameters."""
        trusted = TrustedHostMiddleware(
            allowed_hosts=["example.com", "*.example.com"],
            www_redirect=True,
        )

        assert "example.com" in trusted.allowed_hosts
        assert trusted.www_redirect is True


class TestResponseTypesParity:
    """Test response types match FastAPI."""

    RESPONSE_TYPES = [
        "Response",
        "JSONResponse",
        "HTMLResponse",
        "PlainTextResponse",
        "RedirectResponse",
        "StreamingResponse",
        "FileResponse",
    ]

    def test_all_response_types_available(self):
        """Test all response types are available."""
        import turboapi

        missing = []
        for name in self.RESPONSE_TYPES:
            if not hasattr(turboapi, name):
                missing.append(name)

        assert not missing, f"Missing response types: {missing}"


class TestSecurityExportsParity:
    """Test security exports match FastAPI."""

    SECURITY_CLASSES = [
        "OAuth2PasswordBearer",
        "OAuth2AuthorizationCodeBearer",
        "HTTPBasic",
        "HTTPBasicCredentials",
        "HTTPBearer",
        "APIKeyHeader",
        "APIKeyQuery",
        "APIKeyCookie",
        "SecurityScopes",
        "Security",
        "Depends",
    ]

    def test_all_security_classes_available(self):
        """Test all security classes are available."""
        import turboapi

        missing = []
        for name in self.SECURITY_CLASSES:
            if not hasattr(turboapi, name):
                missing.append(name)

        assert not missing, f"Missing security classes: {missing}"


class TestCompleteExportCount:
    """Test total export count and list all exports."""

    def test_export_count(self):
        """Verify we have comprehensive exports."""
        import turboapi

        # Get all public exports (excluding private ones starting with _)
        exports = [x for x in dir(turboapi) if not x.startswith("_")]

        # FastAPI has ~20 core exports, we should have at least that many
        # Plus responses, security, middleware, encoders = ~40+
        assert len(exports) >= 35, f"Expected 35+ exports, got {len(exports)}: {exports}"

        # Print exports for visibility
        print(f"\n\nTurboAPI exports ({len(exports)} total):")
        for name in sorted(exports):
            print(f"  - {name}")

    def test_all_imports_work(self):
        """Test comprehensive import statement works."""
        # This is the typical FastAPI-style import
        from turboapi import (
            # Core (FastAPI equivalent)
            TurboAPI,
            APIRouter,
            Request,
            Response,
            # Parameters
            Body,
            Cookie,
            Depends,
            File,
            Form,
            Header,
            Path,
            Query,
            Security,
            # Utilities
            BackgroundTasks,
            UploadFile,
            # Exceptions
            HTTPException,
            RequestValidationError,
            WebSocketException,
            # WebSocket
            WebSocket,
            WebSocketDisconnect,
            # Responses
            JSONResponse,
            HTMLResponse,
            PlainTextResponse,
            RedirectResponse,
            StreamingResponse,
            FileResponse,
            # Security classes
            OAuth2PasswordBearer,
            OAuth2AuthorizationCodeBearer,
            HTTPBasic,
            HTTPBasicCredentials,
            HTTPBearer,
            APIKeyHeader,
            APIKeyQuery,
            APIKeyCookie,
            SecurityScopes,
            # Middleware
            Middleware,
            CORSMiddleware,
            GZipMiddleware,
            TrustedHostMiddleware,
            HTTPSRedirectMiddleware,
            # Encoders
            jsonable_encoder,
            # Status module
            status,
        )

        # All imports successful
        assert TurboAPI is not None
        assert status.HTTP_200_OK == 200
