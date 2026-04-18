"""FastAPI-compatible shim: ``from turboapi.middleware.sessions import SessionMiddleware``.

Note: FastAPI re-exports Starlette's SessionMiddleware from ``fastapi.middleware.sessions``;
this shim gives users the same import path on TurboAPI.
"""

from .core import SessionMiddleware

__all__ = ["SessionMiddleware"]
