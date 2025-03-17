"""
Middleware package for TurboAPI.

This package provides middleware components for TurboAPI applications.
"""

from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

from .authentication import (
    AuthenticationMiddleware, 
    JWTAuthMiddleware,
    BasicAuthMiddleware
)

class TurboAPIMiddleware:
    """
    Collection of built-in middleware generators.
    
    This class provides factory methods for common middleware configurations.
    """
    
    @staticmethod
    def cors(
        allow_origins=(),
        allow_methods=("GET",),
        allow_headers=(),
        allow_credentials=False,
        allow_origin_regex=None,
        expose_headers=(),
        max_age=600,
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
    def trusted_host(allowed_hosts, www_redirect=True) -> Middleware:
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
    def gzip(minimum_size=500, compresslevel=9) -> Middleware:
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
    
    @staticmethod
    def authentication(backend) -> Middleware:
        """
        Create authentication middleware.
        
        Args:
            backend: The authentication backend to use.
            
        Returns:
            Middleware instance configured for authentication.
        """
        return Middleware(AuthenticationMiddleware, backend=backend)
    
    @staticmethod
    def jwt_auth(
        secret_key,
        algorithm="HS256",
        excluded_paths=None,
        user_model=None
    ) -> Middleware:
        """
        Create JWT authentication middleware.
        
        Args:
            secret_key: The secret key to use for JWT token validation.
            algorithm: The algorithm to use for JWT token validation.
            excluded_paths: A list of paths to exclude from authentication.
            user_model: The user model to use for authenticated users.
            
        Returns:
            Middleware instance configured for JWT authentication.
        """
        return Middleware(
            JWTAuthMiddleware, 
            secret_key=secret_key, 
            algorithm=algorithm,
            excluded_paths=excluded_paths,
            user_model=user_model
        )
    
    @staticmethod
    def basic_auth(
        credentials,
        realm="TurboAPI",
        excluded_paths=None
    ) -> Middleware:
        """
        Create Basic authentication middleware.
        
        Args:
            credentials: A dictionary mapping usernames to passwords.
            realm: The authentication realm.
            excluded_paths: A list of paths to exclude from authentication.
            
        Returns:
            Middleware instance configured for Basic authentication.
        """
        return Middleware(
            BasicAuthMiddleware,
            credentials=credentials,
            realm=realm,
            excluded_paths=excluded_paths
        )

__all__ = [
    "Middleware",
    "CORSMiddleware",
    "TrustedHostMiddleware",
    "GZipMiddleware",
    "HTTPSRedirectMiddleware",
    "AuthenticationMiddleware",
    "JWTAuthMiddleware",
    "BasicAuthMiddleware",
    "TurboAPIMiddleware",
] 