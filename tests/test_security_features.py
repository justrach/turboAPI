#!/usr/bin/env python3
"""
Comprehensive tests for TurboAPI security features.

Tests:
- OAuth2 Password Bearer
- HTTP Basic Authentication
- HTTP Bearer Authentication
- API Key (Header, Query, Cookie)
- Security Scopes
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))

from turboapi.security import (
    OAuth2PasswordBearer,
    OAuth2PasswordRequestForm,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
    HTTPAuthorizationCredentials,
    APIKeyQuery,
    APIKeyHeader,
    APIKeyCookie,
    SecurityScopes,
    HTTPException,
)
import base64


def test_oauth2_password_bearer():
    """Test OAuth2 password bearer token extraction."""
    print("Testing OAuth2PasswordBearer...")
    
    oauth2 = OAuth2PasswordBearer(tokenUrl="token")
    
    # Valid token
    token = oauth2(authorization="Bearer my-secret-token")
    assert token == "my-secret-token", f"Expected 'my-secret-token', got {token}"
    
    # Invalid scheme
    try:
        oauth2(authorization="Basic invalid")
        assert False, "Should have raised HTTPException"
    except HTTPException as e:
        assert e.status_code == 401
    
    # No authorization
    try:
        oauth2(authorization=None)
        assert False, "Should have raised HTTPException"
    except HTTPException as e:
        assert e.status_code == 401
    
    print("✅ OAuth2PasswordBearer tests passed!")


def test_http_basic():
    """Test HTTP Basic authentication."""
    print("Testing HTTPBasic...")
    
    security = HTTPBasic()
    
    # Valid credentials
    credentials_str = base64.b64encode(b"user:pass").decode()
    creds = security(authorization=f"Basic {credentials_str}")
    assert isinstance(creds, HTTPBasicCredentials)
    assert creds.username == "user"
    assert creds.password == "pass"
    
    # Invalid scheme
    try:
        security(authorization="Bearer token")
        assert False, "Should have raised HTTPException"
    except HTTPException as e:
        assert e.status_code == 401
    
    # Invalid base64
    try:
        security(authorization="Basic invalid!!!!")
        assert False, "Should have raised HTTPException"
    except HTTPException as e:
        assert e.status_code == 401
    
    print("✅ HTTPBasic tests passed!")


def test_http_bearer():
    """Test HTTP Bearer authentication."""
    print("Testing HTTPBearer...")
    
    security = HTTPBearer()
    
    # Valid token
    creds = security(authorization="Bearer my-token-123")
    assert isinstance(creds, HTTPAuthorizationCredentials)
    assert creds.scheme == "Bearer"
    assert creds.credentials == "my-token-123"
    
    # Invalid scheme
    try:
        security(authorization="Basic invalid")
        assert False, "Should have raised HTTPException"
    except HTTPException as e:
        assert e.status_code == 401
    
    print("✅ HTTPBearer tests passed!")


def test_api_key_query():
    """Test API key in query parameters."""
    print("Testing APIKeyQuery...")
    
    api_key = APIKeyQuery(name="api_key")
    
    # Valid key
    key = api_key(query_params={"api_key": "secret-key-123"})
    assert key == "secret-key-123"
    
    # Missing key
    try:
        api_key(query_params={})
        assert False, "Should have raised HTTPException"
    except HTTPException as e:
        assert e.status_code == 403
    
    print("✅ APIKeyQuery tests passed!")


def test_api_key_header():
    """Test API key in headers."""
    print("Testing APIKeyHeader...")
    
    api_key = APIKeyHeader(name="X-API-Key")
    
    # Valid key (case insensitive)
    key = api_key(headers={"x-api-key": "secret-key-123"})
    assert key == "secret-key-123"
    
    # Valid key (exact case)
    key = api_key(headers={"X-API-Key": "another-key"})
    assert key == "another-key"
    
    # Missing key
    try:
        api_key(headers={})
        assert False, "Should have raised HTTPException"
    except HTTPException as e:
        assert e.status_code == 403
    
    print("✅ APIKeyHeader tests passed!")


def test_api_key_cookie():
    """Test API key in cookies."""
    print("Testing APIKeyCookie...")
    
    api_key = APIKeyCookie(name="session")
    
    # Valid key
    key = api_key(cookies={"session": "session-token-123"})
    assert key == "session-token-123"
    
    # Missing key
    try:
        api_key(cookies={})
        assert False, "Should have raised HTTPException"
    except HTTPException as e:
        assert e.status_code == 403
    
    print("✅ APIKeyCookie tests passed!")


def test_security_scopes():
    """Test security scopes."""
    print("Testing SecurityScopes...")
    
    # Empty scopes
    scopes = SecurityScopes()
    assert scopes.scopes == []
    assert scopes.scope_str == ""
    
    # With scopes
    scopes = SecurityScopes(scopes=["read:users", "write:users"])
    assert scopes.scopes == ["read:users", "write:users"]
    assert scopes.scope_str == "read:users write:users"
    
    print("✅ SecurityScopes tests passed!")


def test_oauth2_password_request_form():
    """Test OAuth2 password request form."""
    print("Testing OAuth2PasswordRequestForm...")
    
    form = OAuth2PasswordRequestForm(
        username="testuser",
        password="testpass",
        scope="read write",
        client_id="my-client"
    )
    
    assert form.username == "testuser"
    assert form.password == "testpass"
    assert form.scope == "read write"
    assert form.grant_type == "password"
    assert form.client_id == "my-client"
    
    print("✅ OAuth2PasswordRequestForm tests passed!")


def run_all_tests():
    """Run all security tests."""
    print("\n" + "="*60)
    print("🔒 TurboAPI Security Features Test Suite")
    print("="*60 + "\n")
    
    test_oauth2_password_bearer()
    test_http_basic()
    test_http_bearer()
    test_api_key_query()
    test_api_key_header()
    test_api_key_cookie()
    test_security_scopes()
    test_oauth2_password_request_form()
    
    print("\n" + "="*60)
    print("✅ ALL SECURITY TESTS PASSED!")
    print("="*60 + "\n")


if __name__ == "__main__":
    run_all_tests()
