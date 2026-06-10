"""
TurboAPI Route Registration System
FastAPI-compatible decorators with revolutionary performance
"""

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .version_check import CHECK_MARK


class HTTPMethod(Enum):
    """HTTP methods supported by TurboAPI."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


@dataclass
class PathParameter:
    """Path parameter definition."""

    name: str
    type: type
    default: Any = None
    required: bool = True


@dataclass
class RouteDefinition:
    """Complete route definition."""

    path: str
    method: HTTPMethod
    handler: Callable
    path_params: list[PathParameter]
    query_params: dict[str, type]
    request_model: type | None = None
    response_model: type | None = None
    tags: list[str] = None
    summary: str | None = None
    description: str | None = None
    dependencies: list = None


class RouteRegistry:
    """Registry for all routes in the application."""

    def __init__(self):
        self.routes: list[RouteDefinition] = []
        self.path_patterns: dict[str, re.Pattern] = {}

    def register_route(self, route: RouteDefinition) -> None:
        """Register a new route."""
        self.routes.append(route)

        # Compile path pattern for fast matching
        pattern = self._compile_path_pattern(route.path)
        self.path_patterns[route.path] = pattern

        print(f"{CHECK_MARK} Registered route: {route.method.value} {route.path}")

    def _compile_path_pattern(self, path: str) -> re.Pattern:
        """Compile path with parameters into regex pattern."""
        # Convert FastAPI-style {param} to regex groups
        pattern = path

        # Find all path parameters
        param_matches = re.findall(r"\{([^}]+)\}", path)

        for param in param_matches:
            # Replace {param} with named regex group
            pattern = pattern.replace(f"{{{param}}}", f"(?P<{param}>[^/]+)")

        # Ensure exact match
        pattern = f"^{pattern}$"

        return re.compile(pattern)

    def match_route(self, method: str, path: str) -> tuple | None:
        """Match incoming request to registered route."""
        for route in self.routes:
            if route.method.value != method:
                continue

            pattern = self.path_patterns.get(route.path)
            if not pattern:
                continue

            match = pattern.match(path)
            if match:
                # Extract path parameters
                path_params = match.groupdict()
                return route, path_params

        return None

    def get_routes(self) -> list[RouteDefinition]:
        """Get all registered routes."""
        return self.routes.copy()


class Router:
    """FastAPI-compatible router with decorators."""

    def __init__(self, prefix: str = "", tags: list[str] = None, dependencies: list = None):
        self.prefix = prefix
        self.tags = tags or []
        self.dependencies = dependencies or []
        self.registry = RouteRegistry()

    def _create_route_decorator(self, method: HTTPMethod):
        """Create a route decorator for the given HTTP method."""

        def decorator(
            path: str,
            *,
            response_model: type | None = None,
            tags: list[str] = None,
            summary: str | None = None,
            description: str | None = None,
            **kwargs,
        ):
            def wrapper(func: Callable) -> Callable:
                # Analyze function signature
                sig = inspect.signature(func)

                # Resolve PEP 563 stringified annotations (``from __future__ import
                # annotations``) so ``inspect.isclass(...)`` and identity checks on
                # the annotation don't silently skip path/query binding.
                try:
                    import typing as _typing

                    resolved_hints = _typing.get_type_hints(func)
                except Exception:
                    resolved_hints = {}

                _str_aliases = {
                    "int": int,
                    "float": float,
                    "bool": bool,
                    "str": str,
                    "bytes": bytes,
                }

                def _resolved_ann(p_name, p):
                    ann = resolved_hints.get(p_name, p.annotation)
                    if isinstance(ann, str):
                        ann = _str_aliases.get(ann, ann)
                    return ann

                path_params = []
                query_params = {}
                request_model = None

                for param_name, param in sig.parameters.items():
                    raw_ann = param.annotation
                    ann = _resolved_ann(param_name, param)
                    if f"{{{param_name}}}" in path:
                        # Path parameter
                        path_param = PathParameter(
                            name=param_name,
                            type=ann if raw_ann != inspect.Parameter.empty else str,
                            default=param.default
                            if param.default != inspect.Parameter.empty
                            else None,
                            required=param.default == inspect.Parameter.empty,
                        )
                        path_params.append(path_param)
                    elif raw_ann != inspect.Parameter.empty:
                        # Check if it's a request model (class type)
                        if inspect.isclass(ann):
                            request_model = ann
                        else:
                            # Query parameter
                            query_params[param_name] = ann

                # Create route definition
                full_path = self.prefix + path
                route = RouteDefinition(
                    path=full_path,
                    method=method,
                    handler=func,
                    path_params=path_params,
                    query_params=query_params,
                    request_model=request_model,
                    response_model=response_model,
                    tags=(tags or []) + self.tags,
                    summary=summary,
                    description=description,
                )

                # Register the route
                self.registry.register_route(route)

                # Return the original function (for direct calling)
                return func

            return wrapper

        return decorator

    def get(self, path: str, **kwargs):
        """GET route decorator."""
        return self._create_route_decorator(HTTPMethod.GET)(path, **kwargs)

    def post(self, path: str, **kwargs):
        """POST route decorator."""
        return self._create_route_decorator(HTTPMethod.POST)(path, **kwargs)

    def put(self, path: str, **kwargs):
        """PUT route decorator."""
        return self._create_route_decorator(HTTPMethod.PUT)(path, **kwargs)

    def delete(self, path: str, **kwargs):
        """DELETE route decorator."""
        return self._create_route_decorator(HTTPMethod.DELETE)(path, **kwargs)

    def patch(self, path: str, **kwargs):
        """PATCH route decorator."""
        return self._create_route_decorator(HTTPMethod.PATCH)(path, **kwargs)

    def head(self, path: str, **kwargs):
        """HEAD route decorator."""
        return self._create_route_decorator(HTTPMethod.HEAD)(path, **kwargs)

    def options(self, path: str, **kwargs):
        """OPTIONS route decorator."""
        return self._create_route_decorator(HTTPMethod.OPTIONS)(path, **kwargs)

    def include_router(self, router: Router, prefix: str = "", tags: list[str] = None):
        """Include another router's routes."""
        router_deps = list(router.dependencies) if router.dependencies else []
        for route in router.registry.get_routes():
            merged_deps = router_deps + (route.dependencies or [])
            new_route = RouteDefinition(
                path=prefix + route.path,
                method=route.method,
                handler=route.handler,
                path_params=route.path_params,
                query_params=route.query_params,
                request_model=route.request_model,
                response_model=route.response_model,
                tags=(tags or []) + (route.tags or []),
                summary=route.summary,
                description=route.description,
                dependencies=merged_deps if merged_deps else None,
            )
            self.registry.register_route(new_route)


# Global router instance for the main app
APIRouter = Router
