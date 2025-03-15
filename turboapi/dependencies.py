"""
Dependencies module for TurboAPI.

This module handles dependency injection for route handlers.
"""

import inspect
from typing import Any, Callable, Dict, List, Tuple

from starlette.requests import Request

from .params import Depends


async def solve_dependencies(request: Request, dependencies: List[Depends]) -> Dict[str, Any]:
    """
    Solve dependencies for a request.
    
    This function resolves all dependencies for a request and returns
    a dictionary of dependency values that can be passed to a route handler.
    """
    dependency_cache: Dict[Tuple[Callable, Tuple[Any, ...]], Any] = {}
    results = {}
    
    for param_name, depends in dependencies:
        if depends.dependency:
            result = await solve_dependency(request, depends, dependency_cache)
            
            # Use the parameter name from the route handler
            results[param_name] = result
    
    return results


async def solve_dependency(
    request: Request, depends: Depends, dependency_cache: Dict[Tuple[Callable, Tuple[Any, ...]], Any]
) -> Any:
    """
    Solve a single dependency.
    
    This function resolves a single dependency for a request. It handles both
    synchronous and asynchronous dependencies and caches the results if requested.
    """
    dependency = depends.dependency
    
    # Get the signature of the dependency
    signature = inspect.signature(dependency)
    dependency_params = signature.parameters
    
    # Check if this dependency is cached
    cache_key = (dependency, ())
    if depends.use_cache and cache_key in dependency_cache:
        return dependency_cache[cache_key]
    
    # Prepare the kwargs for calling the dependency
    kwargs = {}
    
    # Handle special parameters like Request
    for param_name, param in dependency_params.items():
        if param_name == "request":
            kwargs["request"] = request
        elif isinstance(param.default, Depends):
            # Recursively solve nested dependencies
            sub_depends = param.default
            kwargs[param_name] = await solve_dependency(request, sub_depends, dependency_cache)
    
    # Call the dependency (handle both async and sync)
    if inspect.iscoroutinefunction(dependency):
        result = await dependency(**kwargs)
    else:
        result = dependency(**kwargs)
    
    # Cache the result if requested
    if depends.use_cache:
        dependency_cache[cache_key] = result
    
    return result
