"""
TurboAPI - Revolutionary Python web framework
FastAPI-compatible API with SIMD-accelerated Rust backend.
Requires Python 3.13+ free-threading for maximum performance.
"""

# Core application
from .rust_integration import TurboAPI
from .routing import APIRouter, Router
from .models import TurboRequest, TurboResponse, Request

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

# Exceptions
from .exceptions import (
    RequestValidationError,
    WebSocketException,
)

# Middleware
from .middleware import (
    CORSMiddleware,
    GZipMiddleware,
    HTTPSRedirectMiddleware,
    Middleware,
    TrustedHostMiddleware,
)

# Background tasks
from .background import BackgroundTasks

# WebSocket
from .websockets import WebSocket, WebSocketDisconnect

# Encoders
from .encoders import jsonable_encoder

# Status codes module (import as 'status')
from . import status

# Version check
from .version_check import check_free_threading_support, get_python_threading_info

__version__ = "2.0.0"
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
    # Encoders
    "jsonable_encoder",
    # Status module
    "status",
    # Utils
    "check_free_threading_support",
    "get_python_threading_info",
]
