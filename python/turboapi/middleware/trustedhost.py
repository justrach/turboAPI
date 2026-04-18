"""FastAPI-compatible shim: ``from turboapi.middleware.trustedhost import TrustedHostMiddleware``."""

from .core import TrustedHostMiddleware

__all__ = ["TrustedHostMiddleware"]
