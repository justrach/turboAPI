"""
Middleware system for TurboAPI.
"""

from typing import Callable, Any
from .models import Request, Response


class Middleware:
    """Base middleware class."""
    
    def before_request(self, request: Request) -> None:
        """Called before processing the request."""
        pass
    
    def after_request(self, request: Request, response: Response) -> Response:
        """Called after processing the request."""
        return response
    
    def on_error(self, request: Request, error: Exception) -> Response:
        """Called when an error occurs."""
        return Response(
            content={"error": "Internal Server Error"},
            status_code=500
        )


class CORSMiddleware(Middleware):
    """CORS middleware."""
    
    def __init__(
        self,
        allow_origins: list = None,
        allow_methods: list = None,
        allow_headers: list = None,
        allow_credentials: bool = False
    ):
        self.allow_origins = allow_origins or ["*"]
        self.allow_methods = allow_methods or ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
        self.allow_headers = allow_headers or ["*"]
        self.allow_credentials = allow_credentials
    
    def after_request(self, request: Request, response: Response) -> Response:
        """Add CORS headers to response."""
        response.set_header("Access-Control-Allow-Origin", ",".join(self.allow_origins))
        response.set_header("Access-Control-Allow-Methods", ",".join(self.allow_methods))
        response.set_header("Access-Control-Allow-Headers", ",".join(self.allow_headers))
        
        if self.allow_credentials:
            response.set_header("Access-Control-Allow-Credentials", "true")
        
        return response


class LoggingMiddleware(Middleware):
    """Request logging middleware."""
    
    def before_request(self, request: Request) -> None:
        """Log incoming request."""
        print(f"[REQUEST] {request.method} {request.path}")
    
    def after_request(self, request: Request, response: Response) -> Response:
        """Log response."""
        print(f"[RESPONSE] {request.method} {request.path} -> {response.status_code}")
        return response
