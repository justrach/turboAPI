"""
Application module for Tatsat.

This module defines the main Tatsat application class that serves as the
entry point for creating web applications with the tatsat framework.
"""

from typing import Any, Callable, Dict, List, Optional, Sequence, Type, Union
import inspect

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import BaseRoute, Route
from starlette.types import ASGIApp

from .routing import APIRouter
from .middleware import TatsatMiddleware
from .openapi import OpenAPIGenerator


class Tatsat:
    """
    The main Tatsat application class.
    
    This class is the primary entry point for creating web applications with Tatsat.
    It builds on Starlette and provides enhanced functionality for API development
    with satya-based validation.
    
    Example:
        ```python
        from tatsat import Tatsat
        
        app = Tatsat(title="My API", version="1.0.0")
        
        @app.get("/")
        def read_root():
            return {"Hello": "World"}
        ```
    """
    
    def __init__(
        self,
        *,
        debug: bool = False,
        routes: Optional[List[BaseRoute]] = None,
        title: str = "Tatsat API",
        description: str = "",
        version: str = "0.1.0",
        openapi_url: Optional[str] = "/openapi.json",
        docs_url: Optional[str] = "/docs",
        redoc_url: Optional[str] = "/redoc",
        swagger_ui_oauth2_redirect_url: Optional[str] = "/docs/oauth2-redirect",
        swagger_ui_init_oauth: Optional[Dict[str, Any]] = None,
        middleware: Optional[Sequence[Middleware]] = None,
        exception_handlers: Optional[Dict[Union[int, Type[Exception]], Callable]] = None,
        on_startup: Optional[Sequence[Callable]] = None,
        on_shutdown: Optional[Sequence[Callable]] = None,
        terms_of_service: Optional[str] = None,
        contact: Optional[Dict[str, str]] = None,
        license_info: Optional[Dict[str, str]] = None,
    ):
        """Initialize the Tatsat application."""
        # Create our API router
        self.router = APIRouter()
        
        # Store API metadata
        self.title = title
        self.description = description
        self.version = version
        self.openapi_url = openapi_url
        self.docs_url = docs_url
        self.redoc_url = redoc_url
        
        # Collect routes from the router
        all_routes = list(routes or [])
        
        # Add OpenAPI and documentation routes if enabled
        self.openapi_generator = None
        openapi_routes = []
        if self.openapi_url:
            self.openapi_generator = OpenAPIGenerator(
                title=title,
                description=description,
                version=version,
                openapi_url=openapi_url,
                terms_of_service=terms_of_service,
                contact=contact,
                license_info=license_info,
            )
            # Add OpenAPI endpoint
            from starlette.routing import Route
            from starlette.responses import JSONResponse
            
            async def get_openapi(request):
                return JSONResponse(self.openapi_generator.get_openapi())
            
            all_routes.append(Route(self.openapi_url, get_openapi))
        
        # Setup documentation UI routes if enabled
        if self.docs_url and self.openapi_url:
            from starlette.responses import HTMLResponse
            from starlette.routing import Route
            
            async def swagger_ui_html(request):
                return HTMLResponse(
                    OpenAPIGenerator.get_swagger_ui_html(
                        openapi_url=self.openapi_url,
                        title=self.title + " - Swagger UI",
                    )
                )
            
            all_routes.append(Route(self.docs_url, swagger_ui_html))
        
        if self.redoc_url and self.openapi_url:
            from starlette.responses import HTMLResponse
            from starlette.routing import Route
            
            async def redoc_html(request):
                return HTMLResponse(
                    OpenAPIGenerator.get_redoc_html(
                        openapi_url=self.openapi_url,
                        title=self.title + " - ReDoc",
                    )
                )
            
            all_routes.append(Route(self.redoc_url, redoc_html))
        
        # Create the Starlette app
        self.app = Starlette(
            debug=debug,
            routes=all_routes,
            middleware=middleware,
            exception_handlers=exception_handlers,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
        )
    

    
    def include_router(self, router: APIRouter, *, prefix: str = "", tags: List[str] = None):
        """Include routes from another router with an optional prefix."""
        self.router.include_router(router, prefix=prefix, tags=tags or [])
        # Update the app's routes
        self._update_routes()
    
    def _update_routes(self):
        """Update the application's routes with routes from the router."""
        # Prevent duplicate routes
        existing_paths = {route.path for route in self.app.routes if hasattr(route, 'path')}
        new_routes = [route for route in self.router.routes if not hasattr(route, 'path') or route.path not in existing_paths]
        if new_routes:
            self.app.routes.extend(new_routes)
    
    def get(self, path: str, *, response_model=None, status_code: int = 200, 
            tags: List[str] = None, summary: str = None, description: str = None, 
            response_description: str = "Successful Response", 
            deprecated: bool = False, operation_id: str = None):
        """Decorator for adding a GET route handler."""
        def decorator(func):
            route = self.router.add_api_route(
                path,
                func,
                methods=["GET"],
                response_model=response_model,
                status_code=status_code,
                tags=tags or [],
                summary=summary,
                description=description,
                response_description=response_description,
                deprecated=deprecated,
                operation_id=operation_id,
            )
            self._update_routes()
            return func
        return decorator
    
    def post(self, path: str, *, response_model=None, status_code: int = 200, 
             tags: List[str] = None, summary: str = None, description: str = None, 
             response_description: str = "Successful Response", 
             deprecated: bool = False, operation_id: str = None):
        """Decorator for adding a POST route handler."""
        def decorator(func):
            route = self.router.add_api_route(
                path,
                func,
                methods=["POST"],
                response_model=response_model,
                status_code=status_code,
                tags=tags or [],
                summary=summary,
                description=description,
                response_description=response_description,
                deprecated=deprecated,
                operation_id=operation_id,
            )
            self._update_routes()
            return func
        return decorator
    
    def put(self, path: str, *, response_model=None, status_code: int = 200, 
            tags: List[str] = None, summary: str = None, description: str = None, 
            response_description: str = "Successful Response", 
            deprecated: bool = False, operation_id: str = None):
        """Decorator for adding a PUT route handler."""
        def decorator(func):
            route = self.router.add_api_route(
                path,
                func,
                methods=["PUT"],
                response_model=response_model,
                status_code=status_code,
                tags=tags or [],
                summary=summary,
                description=description,
                response_description=response_description,
                deprecated=deprecated,
                operation_id=operation_id,
            )
            self._update_routes()
            return func
        return decorator
    
    def delete(self, path: str, *, response_model=None, status_code: int = 200, 
               tags: List[str] = None, summary: str = None, description: str = None, 
               response_description: str = "Successful Response", 
               deprecated: bool = False, operation_id: str = None):
        """Decorator for adding a DELETE route handler."""
        def decorator(func):
            route = self.router.add_api_route(
                path,
                func,
                methods=["DELETE"],
                response_model=response_model,
                status_code=status_code,
                tags=tags or [],
                summary=summary,
                description=description,
                response_description=response_description,
                deprecated=deprecated,
                operation_id=operation_id,
            )
            self._update_routes()
            return func
        return decorator
    
    def patch(self, path: str, *, response_model=None, status_code: int = 200, 
              tags: List[str] = None, summary: str = None, description: str = None, 
              response_description: str = "Successful Response", 
              deprecated: bool = False, operation_id: str = None):
        """Decorator for adding a PATCH route handler."""
        def decorator(func):
            route = self.router.add_api_route(
                path,
                func,
                methods=["PATCH"],
                response_model=response_model,
                status_code=status_code,
                tags=tags or [],
                summary=summary,
                description=description,
                response_description=response_description,
                deprecated=deprecated,
                operation_id=operation_id,
            )
            self._update_routes()
            return func
        return decorator
    
    def options(self, path: str, *, response_model=None, status_code: int = 200, 
                tags: List[str] = None, summary: str = None, description: str = None, 
                response_description: str = "Successful Response", 
                deprecated: bool = False, operation_id: str = None):
        """Decorator for adding an OPTIONS route handler."""
        def decorator(func):
            route = self.router.add_api_route(
                path,
                func,
                methods=["OPTIONS"],
                response_model=response_model,
                status_code=status_code,
                tags=tags or [],
                summary=summary,
                description=description,
                response_description=response_description,
                deprecated=deprecated,
                operation_id=operation_id,
            )
            self._update_routes()
            return func
        return decorator
    
    def head(self, path: str, *, response_model=None, status_code: int = 200, 
             tags: List[str] = None, summary: str = None, description: str = None, 
             response_description: str = "Successful Response", 
             deprecated: bool = False, operation_id: str = None):
        """Decorator for adding a HEAD route handler."""
        def decorator(func):
            route = self.router.add_api_route(
                path,
                func,
                methods=["HEAD"],
                response_model=response_model,
                status_code=status_code,
                tags=tags or [],
                summary=summary,
                description=description,
                response_description=response_description,
                deprecated=deprecated,
                operation_id=operation_id,
            )
            self._update_routes()
            return func
        return decorator
    
    def mount(self, path: str, app: ASGIApp, name: Optional[str] = None):
        """Mount another ASGI app at a given path prefix."""
        self.app.mount(path, app, name=name)
        
    def add_middleware(self, middleware_class, **options):
        """Add middleware to the application."""
        self.app.add_middleware(middleware_class, **options)
    
    def add_exception_handler(self, exc_class_or_status_code, handler):
        """Add an exception handler to the application."""
        self.app.add_exception_handler(exc_class_or_status_code, handler)
    
    def add_event_handler(self, event_type: str, func: Callable):
        """Add an event handler to the application."""
        self.app.add_event_handler(event_type, func)
    
    def on_event(self, event_type: str):
        """Register an event handler decorator."""
        return self.app.on_event(event_type)
    
    def middleware(self, middleware_type: str):
        """Register a middleware decorator."""
        return self.app.middleware(middleware_type)
    
    def exception_handler(self, exc_class_or_status_code):
        """Register an exception handler decorator."""
        return self.app.exception_handler(exc_class_or_status_code)
    
    def __call__(self, scope, receive=None, send=None):
        """Handle ASGI requests.
        Supports both ASGI 2.0 (single scope argument returning a callable) and
        ASGI 3.0 (scope, receive, send) protocol specifications.
        """
        self._update_routes()
        if receive is None and send is None:
            return lambda receive, send: self.app(scope, receive, send)
        return self.app(scope, receive, send)
