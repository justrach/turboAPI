"""
Authentication module for TurboAPI.

This module provides authentication classes and utilities for TurboAPI applications.
"""

from typing import List, Optional, Sequence, Tuple, Union, Any

from starlette.authentication import AuthCredentials as StarletteAuthCredentials
from starlette.authentication import AuthenticationBackend as StarletteAuthenticationBackend
from starlette.authentication import BaseUser as StarletteBaseUser
from starlette.authentication import UnauthenticatedUser as StarletteUnauthenticatedUser
from starlette.authentication import SimpleUser as StarletteSimpleUser
from starlette.requests import Request

# Re-export Starlette's authentication classes with TurboAPI wrappers for consistency
class AuthCredentials(StarletteAuthCredentials):
    """
    Authentication credentials for a request.
    
    Attributes:
        scopes: A list of scopes (permissions) that the user has.
    """
    def __init__(self, scopes: Sequence[str] = None):
        """Initialize the authentication credentials."""
        super().__init__(scopes or [])


class BaseUser(StarletteBaseUser):
    """
    Base user class for authentication.
    
    This class should be subclassed to create custom user models.
    """
    @property
    def is_authenticated(self) -> bool:
        """Return True if the user is authenticated."""
        return True
    
    @property
    def display_name(self) -> str:
        """Return a string representation of the user."""
        return "User"
    
    @property
    def identity(self) -> str:
        """Return a unique identifier for the user."""
        return ""


class UnauthenticatedUser(StarletteUnauthenticatedUser, BaseUser):
    """
    User class for unauthenticated users.
    """
    @property
    def is_authenticated(self) -> bool:
        """Return False for unauthenticated users."""
        return False
    
    @property
    def display_name(self) -> str:
        """Return 'Guest' for unauthenticated users."""
        return "Guest"


class SimpleUser(StarletteSimpleUser, BaseUser):
    """
    Simple user class that only has a username.
    
    This class can be used for basic authentication scenarios.
    """
    def __init__(self, username: str):
        """Initialize the simple user with a username."""
        super().__init__(username)
    
    @property
    def identity(self) -> str:
        """Return the username as the identity."""
        return self.username


class BaseAuthentication(StarletteAuthenticationBackend):
    """
    Base authentication backend.
    
    This class should be subclassed to create custom authentication backends.
    """
    async def authenticate(self, request: Request) -> Tuple[AuthCredentials, BaseUser]:
        """
        Authenticate the request.
        
        Args:
            request: The request to authenticate.
            
        Returns:
            A tuple of (AuthCredentials, BaseUser).
        """
        return AuthCredentials(), UnauthenticatedUser()


# JWT Authentication backend example
class JWTAuthentication(BaseAuthentication):
    """
    JSON Web Token (JWT) authentication backend.
    
    This class provides a JWT-based authentication backend that validates
    tokens in the Authorization header.
    """
    def __init__(
        self, 
        secret_key: str, 
        algorithm: str = "HS256",
        auth_header_name: str = "Authorization",
        auth_header_type: str = "Bearer",
        user_model = None,
        auth_scheme: str = "bearer",
        token_getter = None
    ):
        """
        Initialize the JWT authentication backend.
        
        Args:
            secret_key: The secret key used to sign JWT tokens.
            algorithm: The algorithm used to sign JWT tokens.
            auth_header_name: The name of the header that contains the token.
            auth_header_type: The type of the authentication header.
            user_model: The user model to use for authenticated users.
            auth_scheme: The authentication scheme to use.
            token_getter: Optional function to extract token from request.
        """
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.auth_header_name = auth_header_name
        self.auth_header_type = auth_header_type
        self.user_model = user_model
        self.auth_scheme = auth_scheme
        self.token_getter = token_getter or self._default_token_getter
    
    async def _default_token_getter(self, request: Request) -> Optional[str]:
        """
        Extract the token from the request.
        
        Args:
            request: The request to extract the token from.
            
        Returns:
            The token or None if not found.
        """
        auth_header = request.headers.get(self.auth_header_name)
        if not auth_header:
            return None
        
        # Check for scheme
        parts = auth_header.split()
        if len(parts) != 2:
            return None
        
        scheme, token = parts
        if scheme.lower() != self.auth_scheme.lower():
            return None
        
        return token
    
    async def authenticate(self, request: Request) -> Tuple[AuthCredentials, BaseUser]:
        """
        Authenticate the request using JWT.
        
        Args:
            request: The request to authenticate.
            
        Returns:
            A tuple of (AuthCredentials, BaseUser).
        """
        # This is where you would validate the JWT token
        # For this example, we'll just return an unauthenticated user
        # In a real implementation, you would:
        # 1. Extract the token using self.token_getter
        # 2. Validate the token using something like jose.jwt.decode
        # 3. Find the user based on token claims
        # 4. Return AuthCredentials with appropriate scopes and the user
        
        try:
            token = await self.token_getter(request)
            if not token:
                return AuthCredentials(), UnauthenticatedUser()
            
            # In a real implementation, decode and validate the token here
            # For example:
            # from jose import jwt, JWTError
            # try:
            #     payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            #     username = payload.get("sub")
            #     if not username:
            #         return AuthCredentials(), UnauthenticatedUser()
            #     
            #     # Get the user from the user model
            #     user = await self.user_model.get(username)
            #     if not user:
            #         return AuthCredentials(), UnauthenticatedUser()
            #     
            #     # Create auth credentials from scopes in the token
            #     scopes = payload.get("scopes", [])
            #     return AuthCredentials(scopes), user
            # except JWTError:
            #     return AuthCredentials(), UnauthenticatedUser()
            
            # For this example, we'll simulate a successful authentication
            return AuthCredentials(["authenticated"]), SimpleUser("example_user")
        except Exception:
            return AuthCredentials(), UnauthenticatedUser()


# OAuth2 Authentication utilities
class OAuth2PasswordRequestForm:
    """
    OAuth2 password request form.
    
    This class represents a form submitted for OAuth2 password flow.
    """
    def __init__(
        self,
        username: str,
        password: str,
        scope: str = "",
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        """Initialize the OAuth2 password request form."""
        self.username = username
        self.password = password
        self.scope = scope
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scope.split() if scope else []

    @classmethod
    async def from_request(cls, request: Request) -> "OAuth2PasswordRequestForm":
        """
        Create an OAuth2PasswordRequestForm from a request.
        
        Args:
            request: The request to create the form from.
            
        Returns:
            An OAuth2PasswordRequestForm instance.
        """
        form = await request.form()
        return cls(
            username=form.get("username", ""),
            password=form.get("password", ""),
            scope=form.get("scope", ""),
            client_id=form.get("client_id"),
            client_secret=form.get("client_secret"),
        )


class OAuth2PasswordBearer:
    """
    OAuth2 password bearer security scheme.
    
    This class represents an OAuth2 password bearer security scheme for
    securing endpoints using OAuth2 with the password flow.
    """
    def __init__(
        self,
        tokenUrl: str,
        scheme_name: Optional[str] = None,
        scopes: Optional[dict] = None,
        auto_error: bool = True,
    ):
        """
        Initialize the OAuth2 password bearer security scheme.
        
        Args:
            tokenUrl: The URL to the token endpoint.
            scheme_name: The name of the security scheme.
            scopes: A dictionary of available scopes.
            auto_error: Whether to raise an exception when authentication fails.
        """
        self.tokenUrl = tokenUrl
        self.scheme_name = scheme_name or "oauth2"
        self.scopes = scopes or {}
        self.auto_error = auto_error
    
    async def __call__(self, request: Request) -> Optional[str]:
        """
        Extract the token from the request.
        
        Args:
            request: The request to extract the token from.
            
        Returns:
            The token or None if not found.
        """
        authorization = request.headers.get("Authorization")
        if not authorization:
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None
        
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid authentication credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None
        
        return token 