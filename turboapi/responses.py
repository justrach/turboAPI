"""
Responses module for TurboAPI.

This module provides response classes for returning different types of HTTP responses.
"""

from typing import Any, Dict, List, Optional, Union

from starlette.responses import (
    Response as StarletteResponse,
    JSONResponse as StarletteJSONResponse,
    HTMLResponse as StarletteHTMLResponse,
    PlainTextResponse as StarlettePlainTextResponse,
    RedirectResponse as StarletteRedirectResponse,
    StreamingResponse as StarletteStreamingResponse,
    FileResponse as StarletteFileResponse,
)


class Response(StarletteResponse):
    """
    Base response class.
    
    This is a simple wrapper around Starlette's Response class to provide
    a consistent API for turboapi users.
    """
    
    def __init__(self, content: Any = None, status_code: int = 200, headers: Dict[str, str] = None, media_type: str = None):
        """Initialize the response with the given parameters."""
        super().__init__(content, status_code, headers, media_type)


class JSONResponse(StarletteJSONResponse):
    """
    JSON response class.
    
    Returns a response with JSON-encoded content.
    """
    
    def __init__(self, content: Any, status_code: int = 200, headers: Dict[str, str] = None, media_type: str = None):
        """Initialize the JSON response with the given parameters."""
        super().__init__(content, status_code, headers, media_type)
        
        # If content is a satya model, use its to_dict method
        if hasattr(content, 'to_dict') and callable(content.to_dict):
            content = content.to_dict()


class HTMLResponse(StarletteHTMLResponse):
    """
    HTML response class.
    
    Returns a response with HTML content.
    """
    
    def __init__(self, content: str, status_code: int = 200, headers: Dict[str, str] = None):
        """Initialize the HTML response with the given parameters."""
        super().__init__(content, status_code, headers)


class PlainTextResponse(StarlettePlainTextResponse):
    """
    Plain text response class.
    
    Returns a response with plain text content.
    """
    
    def __init__(self, content: str, status_code: int = 200, headers: Dict[str, str] = None):
        """Initialize the plain text response with the given parameters."""
        super().__init__(content, status_code, headers)


class RedirectResponse(StarletteRedirectResponse):
    """
    Redirect response class.
    
    Returns a response that redirects to the given URL.
    """
    
    def __init__(self, url: str, status_code: int = 307, headers: Dict[str, str] = None):
        """Initialize the redirect response with the given parameters."""
        super().__init__(url, status_code, headers)


class StreamingResponse(StarletteStreamingResponse):
    """
    Streaming response class.
    
    Returns a response with streaming content.
    """
    
    def __init__(self, content: Any, status_code: int = 200, headers: Dict[str, str] = None, media_type: str = None):
        """Initialize the streaming response with the given parameters."""
        super().__init__(content, status_code, headers, media_type)


class FileResponse(StarletteFileResponse):
    """
    File response class.
    
    Returns a response with file content.
    """
    
    def __init__(self, path: str, filename: str = None, status_code: int = 200, headers: Dict[str, str] = None, media_type: str = None, method: str = None, stat_result=None):
        """Initialize the file response with the given parameters."""
        super().__init__(path, filename, status_code, headers, media_type, method, stat_result)
