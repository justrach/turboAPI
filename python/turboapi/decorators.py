"""
Standalone decorators for TurboAPI routes.
"""

from typing import Callable
from .app import TurboAPI

# Global app instance for standalone decorators
_global_app: TurboAPI = None


def _get_global_app() -> TurboAPI:
    """Get or create the global app instance."""
    global _global_app
    if _global_app is None:
        _global_app = TurboAPI()
    return _global_app


def get(path: str):
    """Decorator for GET routes using global app."""
    def decorator(handler: Callable):
        app = _get_global_app()
        app.add_route("GET", path, handler)
        return handler
    return decorator


def post(path: str):
    """Decorator for POST routes using global app."""
    def decorator(handler: Callable):
        app = _get_global_app()
        app.add_route("POST", path, handler)
        return handler
    return decorator


def put(path: str):
    """Decorator for PUT routes using global app."""
    def decorator(handler: Callable):
        app = _get_global_app()
        app.add_route("PUT", path, handler)
        return handler
    return decorator


def delete(path: str):
    """Decorator for DELETE routes using global app."""
    def decorator(handler: Callable):
        app = _get_global_app()
        app.add_route("DELETE", path, handler)
        return handler
    return decorator


def patch(path: str):
    """Decorator for PATCH routes using global app."""
    def decorator(handler: Callable):
        app = _get_global_app()
        app.add_route("PATCH", path, handler)
        return handler
    return decorator


def run(host: str = "127.0.0.1", port: int = 8000):
    """Run the global app."""
    app = _get_global_app()
    app.run(host, port)
