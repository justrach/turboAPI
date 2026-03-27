"""
FastAPI-compatible Security and Authentication for TurboAPI.

Includes:
- OAuth2 (Password Bearer, Authorization Code)
- HTTP Basic Authentication
- HTTP Bearer Authentication
- API Key Authentication (Header, Query, Cookie)
- Security scopes and dependencies
"""

import base64
import inspect
from collections.abc import Callable
from dataclasses import dataclass

# ============================================================================
# Base Security Classes
# ============================================================================


class SecurityBase:
    """Base class for all security schemes."""

    def __init__(self, *, scheme_name: str | None = None, auto_error: bool = True):
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
        scheme_name: str | None = None,
        scopes: dict[str, str] | None = None,
        description: str | None = None,
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

    def __call__(self, authorization: str | None = None) -> str | None:
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
    grant_type: str | None = "password"
    client_id: str | None = None
    client_secret: str | None = None


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
        refreshUrl: str | None = None,
        scheme_name: str | None = None,
        scopes: dict[str, str] | None = None,
        description: str | None = None,
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

    def __call__(self, authorization: str | None = None) -> str | None:
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
        scheme_name: str | None = None,
        realm: str | None = None,
        auto_error: bool = True,
    ):
        super().__init__(scheme_name=scheme_name, auto_error=auto_error)
        self.realm = realm
        self.model = {"type": "http", "scheme": "basic"}

    def __call__(self, authorization: str | None = None) -> HTTPBasicCredentials | None:
        """Extract and decode Basic auth credentials."""
        if not authorization:
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Not authenticated",
                    headers={
                        "WWW-Authenticate": f'Basic realm="{self.realm}"' if self.realm else "Basic"
                    },
                )
            return None

        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() != "basic":
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid authentication credentials",
                    headers={
                        "WWW-Authenticate": f'Basic realm="{self.realm}"' if self.realm else "Basic"
                    },
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
                    headers={
                        "WWW-Authenticate": f'Basic realm="{self.realm}"' if self.realm else "Basic"
                    },
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
        scheme_name: str | None = None,
        auto_error: bool = True,
    ):
        super().__init__(scheme_name=scheme_name, auto_error=auto_error)
        self.model = {"type": "http", "scheme": "bearer"}

    def __call__(self, authorization: str | None = None) -> HTTPAuthorizationCredentials | None:
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
        scheme_name: str | None = None,
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
        scheme_name: str | None = None,
        description: str | None = None,
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
        scheme_name: str | None = None,
        description: str | None = None,
        auto_error: bool = True,
    ):
        super().__init__(
            name=name,
            scheme_name=scheme_name,
            description=description,
            auto_error=auto_error,
        )
        self.model = {"type": "apiKey", "in": "query", "name": name}

    def __call__(self, query_params: dict[str, str] | None = None) -> str | None:
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
        scheme_name: str | None = None,
        description: str | None = None,
        auto_error: bool = True,
    ):
        super().__init__(
            name=name,
            scheme_name=scheme_name,
            description=description,
            auto_error=auto_error,
        )
        self.model = {"type": "apiKey", "in": "header", "name": name}

    def __call__(self, headers: dict[str, str] | None = None) -> str | None:
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
        scheme_name: str | None = None,
        description: str | None = None,
        auto_error: bool = True,
    ):
        super().__init__(
            name=name,
            scheme_name=scheme_name,
            description=description,
            auto_error=auto_error,
        )
        self.model = {"type": "apiKey", "in": "cookie", "name": name}

    def __call__(self, cookies: dict[str, str] | None = None) -> str | None:
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

    def __init__(self, scopes: list[str] | None = None):
        self.scopes = scopes or []
        self.scope_str = " ".join(self.scopes)


# ============================================================================
# Helper Functions
# ============================================================================


# Re-export the canonical HTTPException from exceptions.py so all modules
# that raise or catch it use the same class.
from .exceptions import HTTPException  # noqa: F401, E402


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hash produced by get_password_hash().

    Uses PBKDF2-HMAC-SHA256 with the salt embedded in the stored hash.
    Format: ``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``
    """
    import hashlib
    import hmac as _hmac

    try:
        tag, iterations_str, salt_hex, stored_hex = hashed_password.split("$")
    except ValueError:
        return False
    if tag != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        stored = bytes.fromhex(stored_hex)
    except (ValueError, TypeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt, iterations)
    return _hmac.compare_digest(dk, stored)


def get_password_hash(password: str) -> str:
    """
    Hash a password using PBKDF2-HMAC-SHA256 with a random 16-byte salt.

    Returns a string in the format:
    ``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``

    Pure-stdlib implementation — no extra dependencies required.
    """
    import hashlib
    import os

    iterations = 260_000
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


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

    def __init__(self, dependency: Callable | None = None, *, use_cache: bool = True):
        self.dependency = dependency
        self.use_cache = use_cache



def get_depends(param: inspect.Parameter) -> Depends | None:
    """Extract a Depends instance from a parameter — supports both patterns:

    1. Classic:   def f(db: Session = Depends(get_db))
    2. Annotated: def f(db: Annotated[Session, Depends(get_db)])

    Returns the Depends instance or None.
    """
    # Classic pattern: Depends in default value
    if isinstance(param.default, Depends):
        return param.default

    # Annotated pattern: Depends in type metadata
    ann = param.annotation
    if ann is inspect.Parameter.empty:
        return None
    # Annotated types have __metadata__ with the extra args
    for metadata in getattr(ann, "__metadata__", ()):
        if isinstance(metadata, Depends):
            return metadata
    return None
class Security(Depends):
    """
    Security dependency with scopes (compatible with FastAPI).

    Similar to Depends but adds OAuth2 scope support.

    Usage:
        oauth2_scheme = OAuth2PasswordBearer(
            tokenUrl="token",
            scopes={"read": "Read access", "write": "Write access"}
        )

        @app.get("/items/")
        async def read_items(token: str = Security(oauth2_scheme, scopes=["read"])):
            return {"token": token}
    """

    def __init__(
        self,
        dependency: Callable | None = None,
        *,
        scopes: list[str] | None = None,
        use_cache: bool = True,
    ):
        super().__init__(dependency=dependency, use_cache=use_cache)
        self.scopes = scopes or []
        self.security_scopes = SecurityScopes(scopes=self.scopes)
