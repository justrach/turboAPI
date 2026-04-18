"""FastAPI-compatible shim: ``from turboapi.middleware.cors import CORSMiddleware``."""

from .core import CORSMiddleware

__all__ = ["CORSMiddleware"]
