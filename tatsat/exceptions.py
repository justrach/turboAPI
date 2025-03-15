"""
Exceptions module for Tatsat.

This module provides exception classes for handling HTTP errors.
"""

from typing import Any, Dict, Optional, Union

from starlette.exceptions import HTTPException as StarletteHTTPException


class HTTPException(StarletteHTTPException):
    """
    HTTP exception class.
    
    This exception is used to return HTTP error responses from route handlers.
    It extends Starlette's HTTPException with additional functionality like
    support for structured error details.
    """
    
    def __init__(
        self,
        status_code: int,
        detail: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        """Initialize the HTTP exception with the given parameters."""
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers or {}


class ValidationError(Exception):
    """
    Validation error exception.
    
    This exception is raised when request validation fails.
    """
    
    def __init__(self, errors: Any):
        """Initialize the validation error with the given errors."""
        self.errors = errors
        super().__init__(f"Validation error: {errors}")


def http_exception_handler(request, exc):
    """
    HTTP exception handler.
    
    This handler converts HTTPException instances to JSONResponse objects.
    """
    from .responses import JSONResponse
    
    headers = getattr(exc, "headers", None)
    if headers:
        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers=headers,
        )
    else:
        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
        )


def validation_exception_handler(request, exc):
    """
    Validation exception handler.
    
    This handler converts ValidationError instances to JSONResponse objects.
    """
    from .responses import JSONResponse
    
    return JSONResponse(
        {"detail": exc.errors},
        status_code=422,
    )
