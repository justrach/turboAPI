"""
TurboAPI - Revolutionary Python web framework
FastAPI-compatible API with a native backend.
Requires Python 3.14+ free-threading for maximum performance.
"""

# Core application
# Status codes module (import as 'status')
from . import status  # noqa: F401

# Background tasks
from .background import BackgroundTasks

# Parameter types (FastAPI-compatible)
from .datastructures import (
    Body,
    Cookie,
    File,
    Form,
    Header,
    Path,
    Query,
    UploadFile,
)

# Encoders
from .encoders import jsonable_encoder

# Exceptions
from .exceptions import (
    RequestValidationError,
    WebSocketException,
)

# JWT Authentication
from .jwt_auth import (
    JWTBearer,
    JWTSettings,
    TokenData,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

# Middleware
from .middleware import (
    CORSMiddleware,
    GZipMiddleware,
    HTTPSRedirectMiddleware,
    Middleware,
    TrustedHostMiddleware,
)
from .models import Request, TurboRequest, TurboResponse
from .native_integration import TurboAPI

# Response types
from .responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from .routing import APIRouter, Router

# Security
from .security import (
    APIKeyCookie,
    APIKeyHeader,
    APIKeyQuery,
    Depends,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
    HTTPException,
    OAuth2AuthorizationCodeBearer,
    OAuth2PasswordBearer,
    Security,
    SecurityScopes,
)

# SSE (Server-Sent Events)
from .sse import EventSourceResponse, ServerSentEvent, format_sse_event

# Version check
from .version_check import check_free_threading_support, get_python_threading_info

# WebSocket
from .websockets import WebSocket, WebSocketDisconnect

__version__ = "1.0.01"
__all__ = [
    # Core
    "TurboAPI",
    "APIRouter",
    "Router",
    "TurboRequest",
    "TurboResponse",
    "Request",
    # Parameters
    "Body",
    "Cookie",
    "File",
    "Form",
    "Header",
    "Path",
    "Query",
    "UploadFile",
    # Responses
    "FileResponse",
    "HTMLResponse",
    "JSONResponse",
    "PlainTextResponse",
    "RedirectResponse",
    "Response",
    "StreamingResponse",
    # Security
    "APIKeyCookie",
    "APIKeyHeader",
    "APIKeyQuery",
    "Depends",
    "HTTPBasic",
    "HTTPBasicCredentials",
    "HTTPBearer",
    "HTTPException",
    "OAuth2AuthorizationCodeBearer",
    "OAuth2PasswordBearer",
    "Security",
    "SecurityScopes",
    # Exceptions
    "RequestValidationError",
    "WebSocketException",
    # Middleware
    "CORSMiddleware",
    "GZipMiddleware",
    "HTTPSRedirectMiddleware",
    "Middleware",
    "TrustedHostMiddleware",
    # Background tasks
    "BackgroundTasks",
    # WebSocket
    "WebSocket",
    "WebSocketDisconnect",
    # SSE
    "EventSourceResponse",
    "ServerSentEvent",
    "format_sse_event",
    # Encoders
    "jsonable_encoder",
    # Utils
    "check_free_threading_support",
    "get_python_threading_info",
    # JWT Auth
    "JWTBearer",
    "JWTSettings",
    "TokenData",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_password",
    "verify_password",
]
