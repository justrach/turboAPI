"""
FastAPI-compatible exception classes for TurboAPI.
"""

from typing import Any, Dict, List, Optional, Sequence, Union


class HTTPException(Exception):
    """
    HTTP exception for API errors.

    Usage:
        raise HTTPException(status_code=404, detail="Item not found")
    """

    def __init__(
        self,
        status_code: int,
        detail: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.status_code = status_code
        self.detail = detail
        self.headers = headers


class RequestValidationError(Exception):
    """
    Request validation error (FastAPI-compatible).

    Raised when request data fails validation.

    Usage:
        from turboapi import RequestValidationError

        @app.exception_handler(RequestValidationError)
        async def validation_exception_handler(request, exc):
            return JSONResponse(
                status_code=422,
                content={"detail": exc.errors()}
            )
    """

    def __init__(
        self,
        errors: Sequence[Any],
        *,
        body: Any = None,
    ):
        self._errors = errors
        self.body = body

    def errors(self) -> List[Dict[str, Any]]:
        """Return list of validation errors."""
        return list(self._errors)


class WebSocketException(Exception):
    """
    WebSocket exception (FastAPI-compatible).

    Raised when a WebSocket error occurs.

    Usage:
        raise WebSocketException(code=1008, reason="Policy violation")
    """

    def __init__(
        self,
        code: int = 1000,
        reason: Optional[str] = None,
    ):
        self.code = code
        self.reason = reason


class ValidationError(Exception):
    """
    Generic validation error.

    Provides a base for validation-related exceptions.
    """

    def __init__(
        self,
        errors: List[Dict[str, Any]],
    ):
        self._errors = errors

    def errors(self) -> List[Dict[str, Any]]:
        """Return list of validation errors."""
        return self._errors


class StarletteHTTPException(HTTPException):
    """
    Starlette-compatible HTTP exception alias.

    Some applications expect this for compatibility.
    """

    pass


__all__ = [
    "HTTPException",
    "RequestValidationError",
    "WebSocketException",
    "ValidationError",
    "StarletteHTTPException",
]
