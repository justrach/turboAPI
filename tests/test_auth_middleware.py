#!/usr/bin/env python3
"""
Integration tests for auth middleware flowing through the Zig HTTP server.

Validates that:
- OAuth2PasswordBearer extracts tokens via Depends() through the Zig→Python pipeline
- HTTPBearer returns proper 401 when missing/invalid auth
- HTTPBasic decodes credentials correctly
- APIKeyHeader / APIKeyQuery work end-to-end
- Chained dependencies (get_current_user → oauth2_scheme) resolve correctly
- Auth failures return the correct HTTP status code (401/403), not 500
"""

import time
import threading
import requests
import pytest
from turboapi import TurboAPI
from turboapi.security import (
    Depends,
    OAuth2PasswordBearer,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
    HTTPAuthorizationCredentials,
    APIKeyHeader,
    APIKeyQuery,
    HTTPException,
)
import base64


_port_counter = 11400


def _next_port():
    global _port_counter
    _port_counter += 1
    return _port_counter


def _start_app(app, port):
    t = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port), daemon=True)
    t.start()
    time.sleep(2)
    return t


# ── OAuth2PasswordBearer via Depends ─────────────────────────────────────────


def test_oauth2_bearer_valid_token():
    """Valid Bearer token is extracted and passed to handler."""
    port = _next_port()
    app = TurboAPI(title="OAuth2 Test")
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

    @app.get("/users/me")
    def get_me(token: str = Depends(oauth2_scheme)):
        return {"token": token, "authenticated": True}

    _start_app(app, port)

    resp = requests.get(
        f"http://127.0.0.1:{port}/users/me",
        headers={"Authorization": "Bearer my-secret-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"] == "my-secret-token"
    assert data["authenticated"] is True


def test_oauth2_bearer_missing_token():
    """Missing Authorization header returns 401, not 500."""
    port = _next_port()
    app = TurboAPI(title="OAuth2 Missing Test")
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

    @app.get("/protected")
    def protected(token: str = Depends(oauth2_scheme)):
        return {"token": token}

    _start_app(app, port)

    resp = requests.get(f"http://127.0.0.1:{port}/protected")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"


def test_oauth2_bearer_wrong_scheme():
    """Non-Bearer scheme returns 401."""
    port = _next_port()
    app = TurboAPI(title="OAuth2 Wrong Scheme")
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

    @app.get("/protected")
    def protected(token: str = Depends(oauth2_scheme)):
        return {"token": token}

    _start_app(app, port)

    resp = requests.get(
        f"http://127.0.0.1:{port}/protected",
        headers={"Authorization": "Basic abc123"},
    )
    assert resp.status_code == 401


# ── HTTPBearer ───────────────────────────────────────────────────────────────


def test_http_bearer_valid():
    """HTTPBearer extracts credentials correctly."""
    port = _next_port()
    app = TurboAPI(title="HTTPBearer Test")
    security = HTTPBearer()

    @app.get("/secure")
    def secure(creds: HTTPAuthorizationCredentials = Depends(security)):
        return {"scheme": creds.scheme, "token": creds.credentials}

    _start_app(app, port)

    resp = requests.get(
        f"http://127.0.0.1:{port}/secure",
        headers={"Authorization": "Bearer jwt-token-xyz"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["scheme"] == "Bearer"
    assert data["token"] == "jwt-token-xyz"


def test_http_bearer_missing():
    """Missing auth with HTTPBearer returns 401."""
    port = _next_port()
    app = TurboAPI(title="HTTPBearer Missing")
    security = HTTPBearer()

    @app.get("/secure")
    def secure(creds: HTTPAuthorizationCredentials = Depends(security)):
        return {"ok": True}

    _start_app(app, port)

    resp = requests.get(f"http://127.0.0.1:{port}/secure")
    assert resp.status_code == 401


# ── HTTPBasic ────────────────────────────────────────────────────────────────


def test_http_basic_valid():
    """HTTPBasic extracts username and password."""
    port = _next_port()
    app = TurboAPI(title="HTTPBasic Test")
    security = HTTPBasic()

    @app.get("/login")
    def login(creds: HTTPBasicCredentials = Depends(security)):
        return {"user": creds.username, "pass": creds.password}

    _start_app(app, port)

    resp = requests.get(
        f"http://127.0.0.1:{port}/login",
        auth=("admin", "secret"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"] == "admin"
    assert data["pass"] == "secret"


def test_http_basic_missing():
    """Missing Basic auth returns 401."""
    port = _next_port()
    app = TurboAPI(title="HTTPBasic Missing")
    security = HTTPBasic()

    @app.get("/login")
    def login(creds: HTTPBasicCredentials = Depends(security)):
        return {"ok": True}

    _start_app(app, port)

    resp = requests.get(f"http://127.0.0.1:{port}/login")
    assert resp.status_code == 401


def test_http_basic_invalid_encoding():
    """Malformed Base64 in Basic auth returns 401."""
    port = _next_port()
    app = TurboAPI(title="HTTPBasic Invalid")
    security = HTTPBasic()

    @app.get("/login")
    def login(creds: HTTPBasicCredentials = Depends(security)):
        return {"ok": True}

    _start_app(app, port)

    resp = requests.get(
        f"http://127.0.0.1:{port}/login",
        headers={"Authorization": "Basic !!!invalid!!!"},
    )
    assert resp.status_code == 401


# ── APIKeyHeader ─────────────────────────────────────────────────────────────


def test_api_key_header_valid():
    """API key extracted from custom header."""
    port = _next_port()
    app = TurboAPI(title="APIKey Header Test")
    api_key = APIKeyHeader(name="X-API-Key")

    @app.get("/data")
    def get_data(key: str = Depends(api_key)):
        return {"api_key": key}

    _start_app(app, port)

    resp = requests.get(
        f"http://127.0.0.1:{port}/data",
        headers={"X-API-Key": "sk-12345"},
    )
    assert resp.status_code == 200
    assert resp.json()["api_key"] == "sk-12345"


def test_api_key_header_missing():
    """Missing API key header returns 403."""
    port = _next_port()
    app = TurboAPI(title="APIKey Header Missing")
    api_key = APIKeyHeader(name="X-API-Key")

    @app.get("/data")
    def get_data(key: str = Depends(api_key)):
        return {"api_key": key}

    _start_app(app, port)

    resp = requests.get(f"http://127.0.0.1:{port}/data")
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"


# ── Chained dependencies ────────────────────────────────────────────────────


def test_chained_dependency_get_current_user():
    """oauth2 → get_current_user → handler chain resolves correctly."""
    port = _next_port()
    app = TurboAPI(title="Chained Deps Test")
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

    FAKE_USERS = {"alice-token": "alice", "bob-token": "bob"}

    def get_current_user(token: str = Depends(oauth2_scheme)):
        user = FAKE_USERS.get(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user

    @app.get("/me")
    def me(user: str = Depends(get_current_user)):
        return {"user": user}

    _start_app(app, port)

    # Valid token
    resp = requests.get(
        f"http://127.0.0.1:{port}/me",
        headers={"Authorization": "Bearer alice-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["user"] == "alice"

    # Invalid token
    resp = requests.get(
        f"http://127.0.0.1:{port}/me",
        headers={"Authorization": "Bearer bad-token"},
    )
    assert resp.status_code == 401

    # No token
    resp = requests.get(f"http://127.0.0.1:{port}/me")
    assert resp.status_code == 401


# ── Auth with POST body ─────────────────────────────────────────────────────


def test_auth_with_post_body():
    """Auth dependency + JSON body parsing both work in same request."""
    port = _next_port()
    app = TurboAPI(title="Auth + Body Test")
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

    @app.post("/items")
    def create_item(data: dict, token: str = Depends(oauth2_scheme)):
        return {"item": data, "created_by_token": token}

    _start_app(app, port)

    resp = requests.post(
        f"http://127.0.0.1:{port}/items",
        json={"name": "widget", "price": 9.99},
        headers={"Authorization": "Bearer create-token"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["item"]["name"] == "widget"
    assert result["created_by_token"] == "create-token"


def test_auth_with_post_body_no_token():
    """POST with body but missing auth returns 401, not 500."""
    port = _next_port()
    app = TurboAPI(title="Auth + Body Missing")
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

    @app.post("/items")
    def create_item(data: dict, token: str = Depends(oauth2_scheme)):
        return {"item": data}

    _start_app(app, port)

    resp = requests.post(
        f"http://127.0.0.1:{port}/items",
        json={"name": "widget"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"


# ── Async auth handler ───────────────────────────────────────────────────────


def test_async_handler_with_auth():
    """Async handler with Depends(oauth2) works end-to-end."""
    port = _next_port()
    app = TurboAPI(title="Async Auth Test")
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

    @app.get("/async-protected")
    async def protected(token: str = Depends(oauth2_scheme)):
        return {"token": token, "async": True}

    _start_app(app, port)

    resp = requests.get(
        f"http://127.0.0.1:{port}/async-protected",
        headers={"Authorization": "Bearer async-tok"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"] == "async-tok"
    assert data["async"] is True

    # Missing token on async handler
    resp = requests.get(f"http://127.0.0.1:{port}/async-protected")
    assert resp.status_code == 401
