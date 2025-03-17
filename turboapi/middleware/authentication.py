"""
Authentication middleware for TurboAPI.

This module provides middleware for authentication in TurboAPI applications.
"""

import typing

from starlette.middleware.authentication import AuthenticationMiddleware as StarletteAuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..authentication import BaseAuthentication, AuthCredentials, UnauthenticatedUser


class AuthenticationMiddleware(StarletteAuthenticationMiddleware):
    """
    Middleware for authentication.
    
    This middleware authenticates incoming requests and attaches
    authentication information to the request.
    """
    def __init__(
        self,
        app,
        backend: BaseAuthentication,
        on_error: typing.Callable[[Request, Exception], Response] = None
    ):
        """
        Initialize the authentication middleware.
        
        Args:
            app: The ASGI application.
            backend: The authentication backend to use.
            on_error: Optional callback for handling authentication errors.
        """
        super().__init__(app, backend, on_error)


# Custom authentication middleware implementations

class JWTAuthMiddleware(AuthenticationMiddleware):
    """
    JWT Authentication middleware.
    
    This middleware authenticates incoming requests using JWT tokens
    and attaches authentication information to the request.
    """
    def __init__(
        self,
        app,
        secret_key: str,
        algorithm: str = "HS256",
        auth_header_name: str = "Authorization",
        auth_header_type: str = "Bearer",
        user_model = None,
        token_getter = None,
        on_error: typing.Callable[[Request, Exception], Response] = None,
        excluded_paths: typing.List[str] = None
    ):
        """
        Initialize the JWT authentication middleware.
        
        Args:
            app: The ASGI application.
            secret_key: The secret key used to sign JWT tokens.
            algorithm: The algorithm used to sign JWT tokens.
            auth_header_name: The name of the header that contains the token.
            auth_header_type: The type of the authentication header.
            user_model: The user model to use for authenticated users.
            token_getter: Optional function to extract token from request.
            on_error: Optional callback for handling authentication errors.
            excluded_paths: List of paths to exclude from authentication.
        """
        from ..authentication import JWTAuthentication
        
        backend = JWTAuthentication(
            secret_key=secret_key,
            algorithm=algorithm,
            auth_header_name=auth_header_name,
            auth_header_type=auth_header_type,
            user_model=user_model,
            token_getter=token_getter
        )
        
        self.excluded_paths = excluded_paths or []
        super().__init__(app, backend, on_error)
    
    async def dispatch(self, request: Request, call_next: typing.Callable) -> Response:
        """
        Dispatch the request and authenticate if needed.
        
        Args:
            request: The request to authenticate.
            call_next: The next middleware or application to call.
            
        Returns:
            The response from the next middleware or application.
        """
        # Skip authentication for excluded paths
        path = request.url.path
        if any(path.startswith(excluded) for excluded in self.excluded_paths):
            return await call_next(request)
        
        return await super().dispatch(request, call_next)


class BasicAuthMiddleware(AuthenticationMiddleware):
    """
    Basic Authentication middleware.
    
    This middleware authenticates incoming requests using HTTP Basic Authentication
    and attaches authentication information to the request.
    """
    def __init__(
        self,
        app,
        credentials: typing.Dict[str, str],
        realm: str = "TurboAPI",
        on_error: typing.Callable[[Request, Exception], Response] = None,
        excluded_paths: typing.List[str] = None
    ):
        """
        Initialize the Basic authentication middleware.
        
        Args:
            app: The ASGI application.
            credentials: A dictionary mapping usernames to passwords.
            realm: The authentication realm.
            on_error: Optional callback for handling authentication errors.
            excluded_paths: List of paths to exclude from authentication.
        """
        from base64 import b64decode
        
        class BasicAuthBackend(BaseAuthentication):
            async def authenticate(self, request: Request):
                auth = request.headers.get("Authorization")
                if not auth or not auth.startswith("Basic "):
                    return AuthCredentials(), UnauthenticatedUser()
                
                try:
                    # Extract and decode the basic auth credentials
                    auth_decoded = b64decode(auth[6:]).decode("latin1")
                    username, password = auth_decoded.split(":", 1)
                    
                    # Check if credentials are valid
                    if username in credentials and credentials[username] == password:
                        return AuthCredentials(["authenticated"]), username
                except Exception:
                    pass
                
                return AuthCredentials(), UnauthenticatedUser()
        
        self.excluded_paths = excluded_paths or []
        super().__init__(app, BasicAuthBackend(), on_error)
    
    async def dispatch(self, request: Request, call_next: typing.Callable) -> Response:
        """
        Dispatch the request and authenticate if needed.
        
        Args:
            request: The request to authenticate.
            call_next: The next middleware or application to call.
            
        Returns:
            The response from the next middleware or application.
        """
        # Skip authentication for excluded paths
        path = request.url.path
        if any(path.startswith(excluded) for excluded in self.excluded_paths):
            return await call_next(request)
        
        return await super().dispatch(request, call_next) 