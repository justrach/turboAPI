"""
FastAPI-compatible Security and Authentication for TurboAPI.

Includes:
- OAuth2 (Password Bearer, Authorization Code)
- HTTP Basic Authentication
- HTTP Bearer Authentication  
- API Key Authentication (Header, Query, Cookie)
- Security scopes and dependencies
"""

from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass
import secrets
import base64


# ============================================================================
# Base Security Classes
# ============================================================================

class SecurityBase:
    """Base class for all security schemes."""
    
    def __init__(self, *, scheme_name: Optional[str] = None, auto_error: bool = True):
        self.scheme_name = scheme_name
        self.auto_error = auto_error


# ============================================================================
# OAuth2 Authentication
# ============================================================================

class OAuth2PasswordBearer(SecurityBase):
    """
    OAuth2 password bearer token authentication.
    
    Usage:
        oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
        
        @app.get("/users/me")
        async def get_user(token: str = Depends(oauth2_scheme)):
            return {"token": token}
    """
    
    def __init__(
        self,
        tokenUrl: str,
        scheme_name: Optional[str] = None,
        scopes: Optional[Dict[str, str]] = None,
        description: Optional[str] = None,
        auto_error: bool = True,
    ):
        super().__init__(scheme_name=scheme_name, auto_error=auto_error)
        self.tokenUrl = tokenUrl
        self.scopes = scopes or {}
        self.description = description
        self.model = {
            "type": "oauth2",
            "flows": {
                "password": {
                    "tokenUrl": tokenUrl,
                    "scopes": self.scopes,
                }
            },
        }
    
    def __call__(self, authorization: Optional[str] = None) -> Optional[str]:
        """Extract token from Authorization header."""
        if not authorization:
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None
        
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer":
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid authentication credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None
        
        return token


@dataclass
class OAuth2PasswordRequestForm:
    """
    OAuth2 password request form data.
    
    Automatically parses form data for OAuth2 password flow.
    """
    username: str
    password: str
    scope: str = ""
    grant_type: Optional[str] = "password"
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


class OAuth2AuthorizationCodeBearer(SecurityBase):
    """
    OAuth2 authorization code flow with bearer token.
    
    Usage:
        oauth2_scheme = OAuth2AuthorizationCodeBearer(
            authorizationUrl="https://example.com/oauth/authorize",
            tokenUrl="https://example.com/oauth/token"
        )
    """
    
    def __init__(
        self,
        authorizationUrl: str,
        tokenUrl: str,
        refreshUrl: Optional[str] = None,
        scheme_name: Optional[str] = None,
        scopes: Optional[Dict[str, str]] = None,
        description: Optional[str] = None,
        auto_error: bool = True,
    ):
        super().__init__(scheme_name=scheme_name, auto_error=auto_error)
        self.authorizationUrl = authorizationUrl
        self.tokenUrl = tokenUrl
        self.refreshUrl = refreshUrl
        self.scopes = scopes or {}
        self.description = description
        self.model = {
            "type": "oauth2",
            "flows": {
                "authorizationCode": {
                    "authorizationUrl": authorizationUrl,
                    "tokenUrl": tokenUrl,
                    "refreshUrl": refreshUrl,
                    "scopes": self.scopes,
                }
            },
        }
    
    def __call__(self, authorization: Optional[str] = None) -> Optional[str]:
        """Extract token from Authorization header."""
        if not authorization:
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None
        
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer":
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid authentication credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None
        
        return token


# ============================================================================
# HTTP Basic Authentication
# ============================================================================

@dataclass
class HTTPBasicCredentials:
    """HTTP Basic authentication credentials."""
    username: str
    password: str


class HTTPBasic(SecurityBase):
    """
    HTTP Basic authentication.
    
    Usage:
        security = HTTPBasic()
        
        @app.get("/users/me")
        def get_user(credentials: HTTPBasicCredentials = Depends(security)):
            return {"username": credentials.username}
    """
    
    def __init__(
        self,
        *,
        scheme_name: Optional[str] = None,
        realm: Optional[str] = None,
        auto_error: bool = True,
    ):
        super().__init__(scheme_name=scheme_name, auto_error=auto_error)
        self.realm = realm
        self.model = {"type": "http", "scheme": "basic"}
    
    def __call__(self, authorization: Optional[str] = None) -> Optional[HTTPBasicCredentials]:
        """Extract and decode Basic auth credentials."""
        if not authorization:
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": f'Basic realm="{self.realm}"' if self.realm else "Basic"},
                )
            return None
        
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() != "basic":
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid authentication credentials",
                    headers={"WWW-Authenticate": f'Basic realm="{self.realm}"' if self.realm else "Basic"},
                )
            return None
        
        try:
            decoded = base64.b64decode(credentials).decode("utf-8")
            username, _, password = decoded.partition(":")
            return HTTPBasicCredentials(username=username, password=password)
        except Exception:
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid authentication credentials",
                    headers={"WWW-Authenticate": f'Basic realm="{self.realm}"' if self.realm else "Basic"},
                )
            return None


# ============================================================================
# HTTP Bearer Authentication
# ============================================================================

@dataclass
class HTTPAuthorizationCredentials:
    """HTTP authorization credentials."""
    scheme: str
    credentials: str


class HTTPBearer(SecurityBase):
    """
    HTTP Bearer token authentication.
    
    Usage:
        security = HTTPBearer()
        
        @app.get("/users/me")
        def get_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
            return {"token": credentials.credentials}
    """
    
    def __init__(
        self,
        *,
        scheme_name: Optional[str] = None,
        auto_error: bool = True,
    ):
        super().__init__(scheme_name=scheme_name, auto_error=auto_error)
        self.model = {"type": "http", "scheme": "bearer"}
    
    def __call__(self, authorization: Optional[str] = None) -> Optional[HTTPAuthorizationCredentials]:
        """Extract Bearer token."""
        if not authorization:
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None
        
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() != "bearer":
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid authentication credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None
        
        return HTTPAuthorizationCredentials(scheme=scheme, credentials=credentials)


class HTTPDigest(SecurityBase):
    """
    HTTP Digest authentication.
    
    Usage:
        security = HTTPDigest()
    """
    
    def __init__(
        self,
        *,
        scheme_name: Optional[str] = None,
        auto_error: bool = True,
    ):
        super().__init__(scheme_name=scheme_name, auto_error=auto_error)
        self.model = {"type": "http", "scheme": "digest"}


# ============================================================================
# API Key Authentication
# ============================================================================

class APIKeyBase(SecurityBase):
    """Base class for API key authentication."""
    
    def __init__(
        self,
        *,
        name: str,
        scheme_name: Optional[str] = None,
        description: Optional[str] = None,
        auto_error: bool = True,
    ):
        super().__init__(scheme_name=scheme_name, auto_error=auto_error)
        self.name = name
        self.description = description


class APIKeyQuery(APIKeyBase):
    """
    API Key authentication via query parameter.
    
    Usage:
        api_key = APIKeyQuery(name="api_key")
        
        @app.get("/items")
        def get_items(key: str = Depends(api_key)):
            return {"api_key": key}
    """
    
    def __init__(
        self,
        *,
        name: str,
        scheme_name: Optional[str] = None,
        description: Optional[str] = None,
        auto_error: bool = True,
    ):
        super().__init__(
            name=name,
            scheme_name=scheme_name,
            description=description,
            auto_error=auto_error,
        )
        self.model = {"type": "apiKey", "in": "query", "name": name}
    
    def __call__(self, query_params: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Extract API key from query parameters."""
        if not query_params or self.name not in query_params:
            if self.auto_error:
                raise HTTPException(
                    status_code=403,
                    detail="Not authenticated",
                )
            return None
        return query_params[self.name]


class APIKeyHeader(APIKeyBase):
    """
    API Key authentication via HTTP header.
    
    Usage:
        api_key = APIKeyHeader(name="X-API-Key")
        
        @app.get("/items")
        def get_items(key: str = Depends(api_key)):
            return {"api_key": key}
    """
    
    def __init__(
        self,
        *,
        name: str,
        scheme_name: Optional[str] = None,
        description: Optional[str] = None,
        auto_error: bool = True,
    ):
        super().__init__(
            name=name,
            scheme_name=scheme_name,
            description=description,
            auto_error=auto_error,
        )
        self.model = {"type": "apiKey", "in": "header", "name": name}
    
    def __call__(self, headers: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Extract API key from headers."""
        if not headers or self.name.lower() not in {k.lower(): v for k, v in headers.items()}:
            if self.auto_error:
                raise HTTPException(
                    status_code=403,
                    detail="Not authenticated",
                )
            return None
        
        # Case-insensitive header lookup
        for key, value in headers.items():
            if key.lower() == self.name.lower():
                return value
        return None


class APIKeyCookie(APIKeyBase):
    """
    API Key authentication via HTTP cookie.
    
    Usage:
        api_key = APIKeyCookie(name="session")
        
        @app.get("/items")
        def get_items(key: str = Depends(api_key)):
            return {"session": key}
    """
    
    def __init__(
        self,
        *,
        name: str,
        scheme_name: Optional[str] = None,
        description: Optional[str] = None,
        auto_error: bool = True,
    ):
        super().__init__(
            name=name,
            scheme_name=scheme_name,
            description=description,
            auto_error=auto_error,
        )
        self.model = {"type": "apiKey", "in": "cookie", "name": name}
    
    def __call__(self, cookies: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Extract API key from cookies."""
        if not cookies or self.name not in cookies:
            if self.auto_error:
                raise HTTPException(
                    status_code=403,
                    detail="Not authenticated",
                )
            return None
        return cookies[self.name]


# ============================================================================
# Security Scopes
# ============================================================================

class SecurityScopes:
    """
    Security scopes for OAuth2 and other scope-based auth.
    
    Usage:
        def get_current_user(
            security_scopes: SecurityScopes,
            token: str = Depends(oauth2_scheme)
        ):
            if security_scopes.scopes:
                authenticate_value = f'Bearer scope="{security_scopes.scope_str}"'
            else:
                authenticate_value = "Bearer"
            # Validate token and scopes...
    """
    
    def __init__(self, scopes: Optional[List[str]] = None):
        self.scopes = scopes or []
        self.scope_str = " ".join(self.scopes)


# ============================================================================
# Helper Functions
# ============================================================================

class HTTPException(Exception):
    """HTTP exception for authentication errors."""
    
    def __init__(
        self,
        status_code: int,
        detail: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.status_code = status_code
        self.detail = detail
        self.headers = headers


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hash.
    
    Note: This is a placeholder. Use a proper password hashing library like:
    - passlib with bcrypt
    - argon2-cffi
    """
    # TODO: Implement with proper password hashing
    return secrets.compare_digest(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash a password.
    
    Note: This is a placeholder. Use a proper password hashing library.
    """
    # TODO: Implement with proper password hashing
    return password  # INSECURE - just for demo!


# ============================================================================
# Dependency Injection Helper
# ============================================================================

class Depends:
    """
    Dependency injection marker (compatible with FastAPI).
    
    Usage:
        def get_current_user(token: str = Depends(oauth2_scheme)):
            return decode_token(token)
        
        @app.get("/users/me")
        def read_users_me(user = Depends(get_current_user)):
            return user
    """
    
    def __init__(self, dependency: Optional[Callable] = None, *, use_cache: bool = True):
        self.dependency = dependency
        self.use_cache = use_cache
