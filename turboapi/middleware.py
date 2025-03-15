"""
Middleware module for TurboAPI.

This module provides middleware components for TurboAPI applications.
"""

from typing import Callable, Optional, Sequence

from starlette.middleware import Middleware as StarletteMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware


class Middleware:
    """
    TurboAPI middleware class.
    
    This is a simple wrapper around Starlette's Middleware class to provide
    a consistent API for turboapi users.
    """
    def __new__(cls, middleware_class: type, **options):
        """Create a new middleware instance."""
        return StarletteMiddleware(middleware_class, **options)


class TurboAPIMiddleware:
    """
    Collection of built-in middleware generators.
    
    This class provides factory methods for common middleware configurations.
    """
    
    @staticmethod
    def cors(
        allow_origins: Sequence[str] = (),
        allow_methods: Sequence[str] = ("GET",),
        allow_headers: Sequence[str] = (),
        allow_credentials: bool = False,
        allow_origin_regex: Optional[str] = None,
        expose_headers: Sequence[str] = (),
        max_age: int = 600,
    ) -> Middleware:
        """
        Create CORS middleware for cross-origin resource sharing.
        
        Args:
            allow_origins: A list of origins that should be permitted to make cross-origin requests.
            allow_methods: A list of HTTP methods that should be allowed for cross-origin requests.
            allow_headers: A list of HTTP headers that should be allowed for cross-origin requests.
            allow_credentials: Indicate that cookies should be supported for cross-origin requests.
            allow_origin_regex: A regex string to match against origins that should be permitted.
            expose_headers: Indicate which headers are available for browsers to access.
            max_age: Maximum cache time for preflight requests (in seconds).
        
        Returns:
            Middleware instance configured for CORS.
        """
        return Middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_methods=allow_methods,
            allow_headers=allow_headers,
            allow_credentials=allow_credentials,
            allow_origin_regex=allow_origin_regex,
            expose_headers=expose_headers,
            max_age=max_age,
        )
    
    @staticmethod
    def trusted_host(allowed_hosts: Sequence[str], www_redirect: bool = True) -> Middleware:
        """
        Create trusted host middleware to protect against host header attacks.
        
        Args:
            allowed_hosts: A list of host/domain names that this site can serve.
            www_redirect: If True, redirects to the same URL, but with the www. prefix.
        
        Returns:
            Middleware instance configured for trusted hosts.
        """
        return Middleware(
            TrustedHostMiddleware,
            allowed_hosts=allowed_hosts,
            www_redirect=www_redirect,
        )
    
    @staticmethod
    def gzip(minimum_size: int = 500, compresslevel: int = 9) -> Middleware:
        """
        Create gzip middleware for response compression.
        
        Args:
            minimum_size: Minimum response size (in bytes) to apply compression.
            compresslevel: Compression level from 0 to 9 (higher value = more compression).
        
        Returns:
            Middleware instance configured for gzip compression.
        """
        return Middleware(
            GZipMiddleware,
            minimum_size=minimum_size,
            compresslevel=compresslevel,
        )
    
    @staticmethod
    def https_redirect() -> Middleware:
        """
        Create middleware to redirect all HTTP connections to HTTPS.
        
        Returns:
            Middleware instance configured for HTTPS redirection.
        """
        return Middleware(HTTPSRedirectMiddleware)
