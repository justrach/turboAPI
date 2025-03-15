"""
Middleware module for Tatsat.

This module provides middleware components for Tatsat applications.
"""

from typing import Callable, Optional, Sequence

from starlette.middleware import Middleware as StarletteMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware


class Middleware:
    """
    Tatsat middleware class.
    
    This is a simple wrapper around Starlette's Middleware class to provide
    a consistent API for tatsat users.
    """
    def __new__(cls, middleware_class: type, **options):
        """Create a new middleware instance."""
        return StarletteMiddleware(middleware_class, **options)


class TatsatMiddleware:
    """
    Collection of built-in middleware generators.
    
    This class provides factory methods for creating common middleware configurations.
    """
    
    @staticmethod
    def cors(
        allow_origins: Sequence[str] = ("*",),
        allow_methods: Sequence[str] = ("GET",),
        allow_headers: Sequence[str] = (),
        allow_credentials: bool = False,
        allow_origin_regex: Optional[str] = None,
        expose_headers: Sequence[str] = (),
        max_age: int = 600,
    ) -> Middleware:
        """
        Create a CORS middleware.
        
        This middleware enables Cross-Origin Resource Sharing for your application.
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
    def trusted_host(
        allowed_hosts: Sequence[str],
        www_redirect: bool = True,
    ) -> Middleware:
        """
        Create a TrustedHost middleware.
        
        This middleware validates that the Host header in incoming requests
        matches one of the allowed hosts.
        """
        return Middleware(
            TrustedHostMiddleware,
            allowed_hosts=allowed_hosts,
            www_redirect=www_redirect,
        )
    
    @staticmethod
    def gzip(
        minimum_size: int = 500,
        compresslevel: int = 9,
    ) -> Middleware:
        """
        Create a GZip middleware.
        
        This middleware compresses responses using gzip compression.
        """
        return Middleware(
            GZipMiddleware,
            minimum_size=minimum_size,
            compresslevel=compresslevel,
        )
    
    @staticmethod
    def https_redirect() -> Middleware:
        """
        Create an HTTPSRedirect middleware.
        
        This middleware redirects HTTP requests to HTTPS.
        """
        return Middleware(HTTPSRedirectMiddleware)
