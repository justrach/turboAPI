"""FastAPI-compatible shim: ``from turboapi.middleware.gzip import GZipMiddleware``."""

from .core import GZipMiddleware

__all__ = ["GZipMiddleware"]
