"""
TurboAPI: A high-performance web framework with elegant syntax and powerful validation.

Built on Starlette and using satya for data validation.
"""

__version__ = "0.1.0"

from .applications import TurboAPI
from .routing import APIRouter
from .params import Path, Query, Header, Cookie, Body, Depends, Security
from .responses import JSONResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.requests import Request
from .middleware import Middleware, AuthenticationMiddleware, JWTAuthMiddleware, BasicAuthMiddleware
from .exceptions import HTTPException
from .background import BackgroundTasks
from .authentication import (
    AuthCredentials, 
    BaseUser, 
    SimpleUser, 
    UnauthenticatedUser,
    BaseAuthentication,
    JWTAuthentication,
    OAuth2PasswordRequestForm,
    OAuth2PasswordBearer
)

# For WebSocket support
from starlette.websockets import WebSocket
