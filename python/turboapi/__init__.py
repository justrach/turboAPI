"""
TurboAPI - Revolutionary Python web framework
FastAPI-compatible API with SIMD-accelerated Rust backend.
Requires Python 3.13+ free-threading for maximum performance.
"""

# Core application
from .rust_integration import TurboAPI
from .routing import APIRouter, Router
from .models import TurboRequest, TurboResponse

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
    SecurityScopes,
)

# Background tasks
from .background import BackgroundTasks

# WebSocket
from .websockets import WebSocket, WebSocketDisconnect

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
    "SecurityScopes",
    # Background tasks
    "BackgroundTasks",
    # WebSocket
    "WebSocket",
    "WebSocketDisconnect",
    # Utils
    "check_free_threading_support",
    "get_python_threading_info",
]
