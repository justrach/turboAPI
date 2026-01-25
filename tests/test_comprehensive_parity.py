"""Comprehensive FastAPI Feature Parity Tests for TurboAPI.

Tests all major FastAPI features to ensure 1:1 compatibility.
"""

import pytest
import asyncio
from typing import Optional, List
from dataclasses import dataclass

# TurboAPI imports (should match FastAPI imports exactly)
from turboapi import (
    TurboAPI,
    APIRouter,
    Depends,
    Security,
    HTTPException,
    Query,
    Path,
    Body,
    Header,
    Cookie,
    Form,
    File,
    UploadFile,
)
from turboapi.responses import (
    JSONResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from turboapi.security import (
    OAuth2PasswordBearer,
    OAuth2PasswordRequestForm,
    OAuth2AuthorizationCodeBearer,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
    HTTPAuthorizationCredentials,
    APIKeyHeader,
    APIKeyQuery,
    APIKeyCookie,
    SecurityScopes,
)
from turboapi.middleware import (
    CORSMiddleware,
    GZipMiddleware,
    TrustedHostMiddleware,
    HTTPSRedirectMiddleware,
)
from turboapi.background import BackgroundTasks
from dhi import BaseModel


# ============================================================================
# TEST MODELS (using dhi which is FastAPI's pydantic equivalent)
# ============================================================================

class UserCreate(BaseModel):
    username: str
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str


class Item(BaseModel):
    name: str
    price: float
    description: Optional[str] = None
    tax: Optional[float] = None


class Token(BaseModel):
    access_token: str
    token_type: str


# ============================================================================
# 1. OAUTH2 & SECURITY TESTS
# ============================================================================

class TestOAuth2Security:
    """Test OAuth2 and security feature parity with FastAPI."""

    def test_oauth2_password_bearer_creation(self):
        """OAuth2PasswordBearer should be created like FastAPI."""
        oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
        assert oauth2_scheme.tokenUrl == "token"
        assert oauth2_scheme.auto_error is True

    def test_oauth2_password_bearer_with_scopes(self):
        """OAuth2PasswordBearer should support scopes like FastAPI."""
        oauth2_scheme = OAuth2PasswordBearer(
            tokenUrl="token",
            scopes={"read": "Read access", "write": "Write access"}
        )
        assert oauth2_scheme.scopes == {"read": "Read access", "write": "Write access"}

    def test_oauth2_password_bearer_token_extraction(self):
        """OAuth2PasswordBearer should extract tokens correctly."""
        oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
        token = oauth2_scheme(authorization="Bearer test_token_123")
        assert token == "test_token_123"

    def test_oauth2_password_bearer_invalid_scheme(self):
        """OAuth2PasswordBearer should reject non-Bearer schemes."""
        oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
        with pytest.raises(HTTPException) as exc_info:
            oauth2_scheme(authorization="Basic invalid")
        assert exc_info.value.status_code == 401

    def test_oauth2_auth_code_bearer(self):
        """OAuth2AuthorizationCodeBearer should work like FastAPI."""
        auth_code = OAuth2AuthorizationCodeBearer(
            authorizationUrl="https://auth.example.com/authorize",
            tokenUrl="https://auth.example.com/token",
            refreshUrl="https://auth.example.com/refresh",
            scopes={"openid": "OpenID Connect"}
        )
        assert auth_code.authorizationUrl == "https://auth.example.com/authorize"
        assert auth_code.tokenUrl == "https://auth.example.com/token"
        assert auth_code.refreshUrl == "https://auth.example.com/refresh"

    def test_http_basic_credentials(self):
        """HTTPBasic should decode Base64 credentials like FastAPI."""
        import base64
        http_basic = HTTPBasic()
        credentials = base64.b64encode(b"user:pass").decode()
        result = http_basic(authorization=f"Basic {credentials}")
        assert isinstance(result, HTTPBasicCredentials)
        assert result.username == "user"
        assert result.password == "pass"

    def test_http_bearer_token(self):
        """HTTPBearer should extract tokens like FastAPI."""
        http_bearer = HTTPBearer()
        result = http_bearer(authorization="Bearer my_token")
        assert isinstance(result, HTTPAuthorizationCredentials)
        assert result.scheme == "Bearer"
        assert result.credentials == "my_token"

    def test_api_key_header(self):
        """APIKeyHeader should extract keys from headers like FastAPI."""
        api_key = APIKeyHeader(name="X-API-Key")
        result = api_key(headers={"x-api-key": "secret123"})
        assert result == "secret123"

    def test_api_key_query(self):
        """APIKeyQuery should extract keys from query params like FastAPI."""
        api_key = APIKeyQuery(name="api_key")
        result = api_key(query_params={"api_key": "secret123"})
        assert result == "secret123"

    def test_api_key_cookie(self):
        """APIKeyCookie should extract keys from cookies like FastAPI."""
        api_key = APIKeyCookie(name="session")
        result = api_key(cookies={"session": "abc123"})
        assert result == "abc123"

    def test_security_scopes(self):
        """SecurityScopes should work like FastAPI."""
        scopes = SecurityScopes(scopes=["read", "write", "admin"])
        assert scopes.scopes == ["read", "write", "admin"]
        assert scopes.scope_str == "read write admin"

    def test_oauth2_password_request_form(self):
        """OAuth2PasswordRequestForm should have correct fields like FastAPI."""
        form = OAuth2PasswordRequestForm(
            username="testuser",
            password="testpass",
            scope="read write"
        )
        assert form.username == "testuser"
        assert form.password == "testpass"
        assert form.scope == "read write"


# ============================================================================
# 2. DEPENDENCY INJECTION TESTS
# ============================================================================

class TestDependencyInjection:
    """Test Depends() feature parity with FastAPI."""

    def test_depends_creation(self):
        """Depends should be created like FastAPI."""
        def get_db():
            return "db_connection"

        dep = Depends(get_db)
        assert dep.dependency == get_db
        assert dep.use_cache is True

    def test_depends_no_cache(self):
        """Depends with use_cache=False should work like FastAPI."""
        def get_timestamp():
            import time
            return time.time()

        dep = Depends(get_timestamp, use_cache=False)
        assert dep.use_cache is False

    def test_security_depends(self):
        """Security() should extend Depends with scopes like FastAPI."""
        oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
        security_dep = Security(oauth2_scheme, scopes=["read", "write"])
        assert security_dep.scopes == ["read", "write"]
        assert isinstance(security_dep.security_scopes, SecurityScopes)


# ============================================================================
# 3. PARAMETER TYPES TESTS
# ============================================================================

class TestParameterTypes:
    """Test Query, Path, Body, Header, Cookie, Form parameter types."""

    def test_query_with_validation(self):
        """Query should support validation like FastAPI."""
        query = Query(default=None, min_length=3, max_length=50)
        assert query.min_length == 3
        assert query.max_length == 50

    def test_path_with_validation(self):
        """Path should support validation like FastAPI."""
        path = Path(gt=0, le=100)
        assert path.gt == 0
        assert path.le == 100

    def test_body_with_embed(self):
        """Body should support embed parameter like FastAPI."""
        body = Body(embed=True)
        assert body.embed is True

    def test_header_with_convert_underscores(self):
        """Header should support convert_underscores like FastAPI."""
        header = Header(convert_underscores=True)
        assert header.convert_underscores is True

    def test_cookie_parameter(self):
        """Cookie should work like FastAPI."""
        cookie = Cookie(default=None)
        assert cookie.default is None

    def test_form_parameter(self):
        """Form should work like FastAPI."""
        form = Form(min_length=1)
        assert form.min_length == 1


# ============================================================================
# 4. RESPONSE TYPES TESTS
# ============================================================================

class TestResponseTypes:
    """Test response types feature parity with FastAPI."""

    def test_json_response(self):
        """JSONResponse should work like FastAPI."""
        response = JSONResponse(content={"key": "value"}, status_code=200)
        assert response.status_code == 200
        assert response.media_type == "application/json"
        assert b'"key"' in response.body

    def test_json_response_custom_status(self):
        """JSONResponse should support custom status codes."""
        response = JSONResponse(content={"created": True}, status_code=201)
        assert response.status_code == 201

    def test_html_response(self):
        """HTMLResponse should work like FastAPI."""
        response = HTMLResponse(content="<h1>Hello</h1>")
        assert response.media_type == "text/html"
        assert b"<h1>Hello</h1>" in response.body

    def test_plain_text_response(self):
        """PlainTextResponse should work like FastAPI."""
        response = PlainTextResponse(content="Hello, World!")
        assert response.media_type == "text/plain"
        assert b"Hello, World!" in response.body

    def test_redirect_response(self):
        """RedirectResponse should work like FastAPI."""
        response = RedirectResponse(url="/new-location")
        assert response.status_code == 307
        assert response.headers.get("location") == "/new-location"

    def test_redirect_response_permanent(self):
        """RedirectResponse should support permanent redirects."""
        response = RedirectResponse(url="/new-location", status_code=301)
        assert response.status_code == 301


# ============================================================================
# 5. MIDDLEWARE TESTS
# ============================================================================

class TestMiddleware:
    """Test middleware feature parity with FastAPI."""

    def test_cors_middleware_creation(self):
        """CORSMiddleware should be created like FastAPI."""
        cors = CORSMiddleware(
            allow_origins=["https://example.com"],
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
            allow_credentials=True,
            max_age=600
        )
        assert "https://example.com" in cors.allow_origins
        assert cors.allow_credentials is True
        assert cors.max_age == 600

    def test_cors_middleware_wildcard(self):
        """CORSMiddleware should support wildcard origins."""
        cors = CORSMiddleware(allow_origins=["*"])
        assert "*" in cors.allow_origins

    def test_gzip_middleware_creation(self):
        """GZipMiddleware should be created like FastAPI."""
        gzip = GZipMiddleware(minimum_size=500)
        assert gzip.minimum_size == 500

    def test_trusted_host_middleware(self):
        """TrustedHostMiddleware should work like FastAPI."""
        trusted = TrustedHostMiddleware(
            allowed_hosts=["example.com", "*.example.com"]
        )
        assert "example.com" in trusted.allowed_hosts

    def test_https_redirect_middleware(self):
        """HTTPSRedirectMiddleware should be available like FastAPI."""
        https_redirect = HTTPSRedirectMiddleware()
        assert https_redirect is not None


# ============================================================================
# 6. API ROUTER TESTS
# ============================================================================

class TestAPIRouter:
    """Test APIRouter feature parity with FastAPI."""

    def test_router_creation(self):
        """APIRouter should be created like FastAPI."""
        router = APIRouter(prefix="/api/v1", tags=["users"])
        assert router.prefix == "/api/v1"
        assert "users" in router.tags

    def test_router_route_registration(self):
        """APIRouter should register routes like FastAPI."""
        router = APIRouter()

        @router.get("/items")
        def get_items():
            return []

        routes = router.registry.get_routes()
        assert len(routes) > 0

    def test_router_with_dependencies(self):
        """APIRouter should support dependencies like FastAPI."""
        def verify_token():
            return "token"

        router = APIRouter(dependencies=[Depends(verify_token)])
        assert len(router.dependencies) == 1


# ============================================================================
# 7. APP CREATION TESTS
# ============================================================================

class TestAppCreation:
    """Test TurboAPI app creation parity with FastAPI."""

    def test_app_creation_basic(self):
        """TurboAPI should be created like FastAPI."""
        app = TurboAPI()
        assert app is not None

    def test_app_creation_with_metadata(self):
        """TurboAPI should accept metadata like FastAPI."""
        app = TurboAPI(
            title="My API",
            description="API Description",
            version="1.0.0"
        )
        assert app.title == "My API"
        assert app.description == "API Description"
        assert app.version == "1.0.0"

    def test_app_route_decorators(self):
        """TurboAPI should have route decorators like FastAPI."""
        app = TurboAPI()

        @app.get("/")
        def root():
            return {"message": "Hello"}

        @app.post("/items")
        def create_item():
            return {"created": True}

        @app.put("/items/{item_id}")
        def update_item(item_id: int):
            return {"updated": item_id}

        @app.delete("/items/{item_id}")
        def delete_item(item_id: int):
            return {"deleted": item_id}

        @app.patch("/items/{item_id}")
        def patch_item(item_id: int):
            return {"patched": item_id}

        routes = app.registry.get_routes()
        assert len(routes) >= 5

    def test_app_include_router(self):
        """TurboAPI should include routers like FastAPI."""
        app = TurboAPI()
        router = APIRouter(prefix="/api")

        @router.get("/health")
        def health():
            return {"status": "ok"}

        app.include_router(router)
        routes = app.registry.get_routes()
        paths = [r.path for r in routes]
        assert "/api/health" in paths


# ============================================================================
# 8. MODEL VALIDATION TESTS
# ============================================================================

class TestModelValidation:
    """Test dhi model validation (Pydantic equivalent)."""

    def test_model_creation(self):
        """dhi models should work like Pydantic models."""
        user = UserCreate(username="john", email="john@example.com", password="secret")
        assert user.username == "john"
        assert user.email == "john@example.com"

    def test_model_validation_error(self):
        """dhi models should validate like Pydantic."""
        with pytest.raises(Exception):  # dhi raises validation errors
            UserCreate(username=123, email="invalid", password=None)

    def test_model_dump(self):
        """dhi models should have model_dump() like Pydantic v2."""
        item = Item(name="Widget", price=9.99)
        data = item.model_dump()
        assert data["name"] == "Widget"
        assert data["price"] == 9.99

    def test_model_optional_fields(self):
        """dhi models should handle Optional fields like Pydantic."""
        item = Item(name="Widget", price=9.99)
        assert item.description is None
        assert item.tax is None

        item_with_desc = Item(name="Widget", price=9.99, description="A nice widget")
        assert item_with_desc.description == "A nice widget"


# ============================================================================
# 9. HTTP EXCEPTION TESTS
# ============================================================================

class TestHTTPException:
    """Test HTTPException feature parity with FastAPI."""

    def test_http_exception_creation(self):
        """HTTPException should be created like FastAPI."""
        exc = HTTPException(status_code=404, detail="Not found")
        assert exc.status_code == 404
        assert exc.detail == "Not found"

    def test_http_exception_with_headers(self):
        """HTTPException should support headers like FastAPI."""
        exc = HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"}
        )
        assert exc.headers == {"WWW-Authenticate": "Bearer"}


# ============================================================================
# 10. BACKGROUND TASKS TESTS
# ============================================================================

class TestBackgroundTasks:
    """Test BackgroundTasks feature parity with FastAPI."""

    def test_background_tasks_creation(self):
        """BackgroundTasks should be created like FastAPI."""
        tasks = BackgroundTasks()
        assert tasks is not None

    def test_background_tasks_add_task(self):
        """BackgroundTasks should add tasks like FastAPI."""
        tasks = BackgroundTasks()
        results = []

        def my_task(value: str):
            results.append(value)

        tasks.add_task(my_task, "test")
        assert len(tasks.tasks) == 1


# ============================================================================
# SUMMARY
# ============================================================================

def test_feature_parity_summary():
    """Summary test to verify all major FastAPI features are available."""
    # All these imports should work without error
    from turboapi import (
        TurboAPI,
        APIRouter,
        Depends,
        Security,
        HTTPException,
        Query, Path, Body, Header, Cookie, Form, File, UploadFile,
        JSONResponse, HTMLResponse, PlainTextResponse, RedirectResponse,
        StreamingResponse, FileResponse,
        BackgroundTasks,
        Request,
    )
    from turboapi.security import (
        OAuth2PasswordBearer,
        OAuth2PasswordRequestForm,
        OAuth2AuthorizationCodeBearer,
        HTTPBasic, HTTPBasicCredentials,
        HTTPBearer, HTTPAuthorizationCredentials,
        APIKeyHeader, APIKeyQuery, APIKeyCookie,
        SecurityScopes,
    )
    from turboapi.middleware import (
        CORSMiddleware,
        GZipMiddleware,
        TrustedHostMiddleware,
        HTTPSRedirectMiddleware,
        Middleware,
    )
    from turboapi import status

    print("\n" + "=" * 60)
    print("TurboAPI FastAPI Feature Parity Summary")
    print("=" * 60)
    print("All FastAPI-compatible imports successful!")
    print("=" * 60)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
