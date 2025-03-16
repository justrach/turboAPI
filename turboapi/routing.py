"""
Routing module for TurboAPI.

This module provides routing functionality with integration for
satya-based validation and parameter extraction.
"""

import inspect
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Type, Union

from starlette.routing import Route, Router as StarletteRouter, Mount
from starlette.responses import JSONResponse, Response
from starlette.requests import Request
from starlette.exceptions import HTTPException as StarletteHTTPException

from .dependencies import solve_dependencies
from .params import Depends
from .exceptions import HTTPException

# Configure logging
logger = logging.getLogger(__name__)


class APIRoute(Route):
    """
    A customized route class that handles satya model validation
    and dependency injection.
    """
    
    def __init__(
        self,
        path: str,
        endpoint: Callable,
        *,
        response_model=None,
        status_code: int = 200,
        tags: List[str] = None,
        summary: str = None,
        description: str = None,
        response_description: str = "Successful Response",
        deprecated: bool = False,
        operation_id: str = None,
        include_in_schema: bool = True,
        methods: Optional[List[str]] = None,
        name: Optional[str] = None,
    ):
        """Initialize the API route with endpoint and metadata."""
        methods = methods or ["GET"]
        self.path = path
        self.endpoint = endpoint
        self.response_model = response_model
        self.status_code = status_code
        self.tags = tags or []
        self.summary = summary
        self.description = description or self.endpoint.__doc__
        self.response_description = response_description
        self.deprecated = deprecated
        self.operation_id = operation_id
        self.include_in_schema = include_in_schema
        
        # Analyze the function signature to extract parameters
        self.signature = inspect.signature(endpoint)
        self.dependencies = self._extract_dependencies()
        
        # Wrap the endpoint with the validation logic
        wrapped_endpoint = self._create_validated_endpoint(endpoint)
        
        super().__init__(
            path,
            wrapped_endpoint,
            methods=methods,
            name=name,
            include_in_schema=include_in_schema,
        )
    
    def _extract_dependencies(self) -> List[tuple]:
        """Extract dependencies from the function signature.
        
        Returns a list of tuples (param_name, dependency).
        """
        deps = []
        for param_name, param in self.signature.parameters.items():
            if param.default and isinstance(param.default, Depends):
                deps.append((param_name, param.default))
        return deps
    
    def _create_validated_endpoint(self, endpoint: Callable) -> Callable:
        """
        Wrap the endpoint with validation logic to:
        - Extract and validate path parameters
        - Extract and validate query parameters
        - Extract and validate request body
        - Solve dependencies
        - Apply response validation
        """
        async def validated_endpoint(request):
            """Validate and process the request before calling the endpoint."""
            # Extract path parameters from the request
            path_params = request.path_params

            # Extract query parameters
            query_params = dict(request.query_params)

            # Prepare kwargs for the endpoint
            kwargs = {}

            # Add path parameters
            for param_name, value in path_params.items():
                if param_name in self.signature.parameters:
                    kwargs[param_name] = value

            # Handle body parameters
            if request.method in ("POST", "PUT", "PATCH"):
                try:
                    body = await request.json()
                    if isinstance(body, dict):
                        # Find any parameters that need to be extracted from the body
                        for param_name, param in self.signature.parameters.items():
                            if param_name not in kwargs and param_name != "request" and param_name != "body":
                                if param_name in body:
                                    kwargs[param_name] = body[param_name]

                        # Add the entire body if there's a 'body' parameter
                        if "body" in self.signature.parameters:
                            kwargs["body"] = body
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Invalid JSON body: {str(e)}")

            # Add the query parameters
            for param_name, param in self.signature.parameters.items():
                if param_name in query_params and param_name not in kwargs:
                    kwargs[param_name] = query_params[param_name]

            # Add the request object if it's in the signature
            if "request" in self.signature.parameters:
                kwargs["request"] = request

            # Solve dependencies
            if self.dependencies:
                dependency_values = await solve_dependencies(request, self.dependencies)
                kwargs.update(dependency_values)

            # Call the endpoint
            response = await endpoint(**kwargs) if inspect.iscoroutinefunction(endpoint) else endpoint(**kwargs)

            # Convert response to Response object if needed
            if isinstance(response, Response):
                return response
            elif isinstance(response, dict):
                # Validate response if response_model is set
                if self.response_model and response is not None:
                    try:
                        response_obj = self.response_model(**response)
                        if hasattr(response_obj, "to_dict"):
                            response = response_obj.to_dict()
                    except Exception as e:
                        logger.error(f"Response validation error: {str(e)}")
                        raise HTTPException(status_code=500, detail="Internal server error")
                return JSONResponse(content=response, status_code=self.status_code or 200)
            else:
                return JSONResponse(content=response, status_code=self.status_code or 200)
        
        return validated_endpoint


class APIRouter(StarletteRouter):
    """
    A router for API routes with satya validation support.
    
    This router extends Starlette's Router with additional functionality
    specific to API routes, such as response model validation and
    OpenAPI schema generation.
    """
    
    def __init__(
        self,
        *,
        prefix: str = "",
        tags: List[str] = None,
        dependencies: List[Depends] = None,
        responses: Dict[Union[int, str], Dict[str, Any]] = None,
        default_response_class: Type[Response] = JSONResponse,
        routes: Optional[List[Union[Route, Mount]]] = None,
    ):
        """Initialize the API router."""
        self.prefix = prefix
        self.tags = tags or []
        self.dependencies = dependencies or []
        self.responses = responses or {}
        self.default_response_class = default_response_class
        
        super().__init__(routes=routes or [])
    
    def add_api_route(
        self,
        path: str,
        endpoint: Callable,
        *,
        methods: List[str] = None,
        name: Optional[str] = None,
        response_model=None,
        status_code: int = 200,
        tags: List[str] = None,
        summary: str = None,
        description: str = None,
        response_description: str = "Successful Response",
        deprecated: bool = False,
        operation_id: str = None,
        include_in_schema: bool = True,
    ):
        """Add an API route to the router."""
        methods = methods or ["GET"]
        path = self.prefix + path
        
        combined_tags = list(set(self.tags + (tags or [])))
        
        route = APIRoute(
            path,
            endpoint=endpoint,
            methods=methods,
            name=name,
            response_model=response_model,
            status_code=status_code,
            tags=combined_tags,
            summary=summary,
            description=description,
            response_description=response_description,
            deprecated=deprecated,
            operation_id=operation_id,
            include_in_schema=include_in_schema,
        )
        
        self.routes.append(route)
        return route
    
    def api_route(
        self,
        path: str,
        *,
        methods: List[str] = None,
        name: Optional[str] = None,
        response_model=None,
        status_code: int = 200,
        tags: List[str] = None,
        summary: str = None,
        description: str = None,
        response_description: str = "Successful Response",
        deprecated: bool = False,
        operation_id: str = None,
        include_in_schema: bool = True,
    ):
        """Decorator for adding API routes."""
        def decorator(endpoint):
            self.add_api_route(
                path,
                endpoint,
                methods=methods,
                name=name,
                response_model=response_model,
                status_code=status_code,
                tags=tags,
                summary=summary,
                description=description,
                response_description=response_description,
                deprecated=deprecated,
                operation_id=operation_id,
                include_in_schema=include_in_schema,
            )
            return endpoint
        
        return decorator
    
    def include_router(
        self,
        router: "APIRouter",
        *,
        prefix: str = "",
        tags: List[str] = None,
    ):
        """Include another router in this router."""
        for route in router.routes:
            if isinstance(route, APIRoute):
                # Update the path with the prefix
                path = prefix + route.path
                
                # Combine tags
                combined_tags = list(set((tags or []) + route.tags))
                
                # Create a new route with updated path and tags
                new_route = APIRoute(
                    path,
                    endpoint=route.endpoint,
                    methods=route.methods,
                    name=route.name,
                    response_model=route.response_model,
                    status_code=route.status_code,
                    tags=combined_tags,
                    summary=route.summary,
                    description=route.description,
                    response_description=route.response_description,
                    deprecated=route.deprecated,
                    operation_id=route.operation_id,
                    include_in_schema=route.include_in_schema,
                )
                
                self.routes.append(new_route)
            else:
                # For non-APIRoute objects, just add them as is
                self.routes.append(route)
    
    def get(
        self,
        path: str,
        *,
        response_model=None,
        status_code: int = 200,
        tags: List[str] = None,
        summary: str = None,
        description: str = None,
        response_description: str = "Successful Response",
        deprecated: bool = False,
        operation_id: str = None,
        include_in_schema: bool = True,
        name: Optional[str] = None,
    ):
        """Decorator for adding GET routes."""
        return self.api_route(
            path,
            methods=["GET"],
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            summary=summary,
            description=description,
            response_description=response_description,
            deprecated=deprecated,
            operation_id=operation_id,
            include_in_schema=include_in_schema,
            name=name,
        )
    
    def post(
        self,
        path: str,
        *,
        response_model=None,
        status_code: int = 200,
        tags: List[str] = None,
        summary: str = None,
        description: str = None,
        response_description: str = "Successful Response",
        deprecated: bool = False,
        operation_id: str = None,
        include_in_schema: bool = True,
        name: Optional[str] = None,
    ):
        """Decorator for adding POST routes."""
        return self.api_route(
            path,
            methods=["POST"],
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            summary=summary,
            description=description,
            response_description=response_description,
            deprecated=deprecated,
            operation_id=operation_id,
            include_in_schema=include_in_schema,
            name=name,
        )
    
    def put(
        self,
        path: str,
        *,
        response_model=None,
        status_code: int = 200,
        tags: List[str] = None,
        summary: str = None,
        description: str = None,
        response_description: str = "Successful Response",
        deprecated: bool = False,
        operation_id: str = None,
        include_in_schema: bool = True,
        name: Optional[str] = None,
    ):
        """Decorator for adding PUT routes."""
        return self.api_route(
            path,
            methods=["PUT"],
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            summary=summary,
            description=description,
            response_description=response_description,
            deprecated=deprecated,
            operation_id=operation_id,
            include_in_schema=include_in_schema,
            name=name,
        )
    
    def delete(
        self,
        path: str,
        *,
        response_model=None,
        status_code: int = 200,
        tags: List[str] = None,
        summary: str = None,
        description: str = None,
        response_description: str = "Successful Response",
        deprecated: bool = False,
        operation_id: str = None,
        include_in_schema: bool = True,
        name: Optional[str] = None,
    ):
        """Decorator for adding DELETE routes."""
        return self.api_route(
            path,
            methods=["DELETE"],
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            summary=summary,
            description=description,
            response_description=response_description,
            deprecated=deprecated,
            operation_id=operation_id,
            include_in_schema=include_in_schema,
            name=name,
        )
    
    def patch(
        self,
        path: str,
        *,
        response_model=None,
        status_code: int = 200,
        tags: List[str] = None,
        summary: str = None,
        description: str = None,
        response_description: str = "Successful Response",
        deprecated: bool = False,
        operation_id: str = None,
        include_in_schema: bool = True,
        name: Optional[str] = None,
    ):
        """Decorator for adding PATCH routes."""
        return self.api_route(
            path,
            methods=["PATCH"],
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            summary=summary,
            description=description,
            response_description=response_description,
            deprecated=deprecated,
            operation_id=operation_id,
            include_in_schema=include_in_schema,
            name=name,
        )
    
    def options(
        self,
        path: str,
        *,
        response_model=None,
        status_code: int = 200,
        tags: List[str] = None,
        summary: str = None,
        description: str = None,
        response_description: str = "Successful Response",
        deprecated: bool = False,
        operation_id: str = None,
        include_in_schema: bool = True,
        name: Optional[str] = None,
    ):
        """Decorator for adding OPTIONS routes."""
        return self.api_route(
            path,
            methods=["OPTIONS"],
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            summary=summary,
            description=description,
            response_description=response_description,
            deprecated=deprecated,
            operation_id=operation_id,
            include_in_schema=include_in_schema,
            name=name,
        )
    
    def head(
        self,
        path: str,
        *,
        response_model=None,
        status_code: int = 200,
        tags: List[str] = None,
        summary: str = None,
        description: str = None,
        response_description: str = "Successful Response",
        deprecated: bool = False,
        operation_id: str = None,
        include_in_schema: bool = True,
        name: Optional[str] = None,
    ):
        """Decorator for adding HEAD routes."""
        return self.api_route(
            path,
            methods=["HEAD"],
            response_model=response_model,
            status_code=status_code,
            tags=tags,
            summary=summary,
            description=description,
            response_description=response_description,
            deprecated=deprecated,
            operation_id=operation_id,
            include_in_schema=include_in_schema,
            name=name,
        )
