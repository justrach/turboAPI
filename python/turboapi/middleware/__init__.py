"""FastAPI-compatible middleware package.

Both idiomatic imports are supported::

    from turboapi.middleware import GZipMiddleware, CORSMiddleware
    from turboapi.middleware.gzip import GZipMiddleware
    from turboapi.middleware.cors import CORSMiddleware
"""

from .core import (
    CORSMiddleware,
    CSRFMiddleware,
    CustomMiddleware,
    GZipMiddleware,
    HTTPSRedirect,
    HTTPSRedirectMiddleware,
    LoggingMiddleware,
    Middleware,
    RateLimitMiddleware,
    SessionMiddleware,
    TrustedHostMiddleware,
)

__all__ = [
    "CORSMiddleware",
    "CSRFMiddleware",
    "CustomMiddleware",
    "GZipMiddleware",
    "HTTPSRedirect",
    "HTTPSRedirectMiddleware",
    "LoggingMiddleware",
    "Middleware",
    "RateLimitMiddleware",
    "SessionMiddleware",
    "TrustedHostMiddleware",
]
