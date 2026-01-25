"""
Enhanced Request Handler with dhi Integration
Provides FastAPI-compatible automatic JSON body parsing and validation
Supports query parameters, path parameters, headers, request body, and dependencies
"""

import inspect
import json
import urllib.parse
from typing import Any, get_args, get_origin

from dhi import BaseModel as Model


class DependencyResolver:
    """Resolve Depends() dependencies recursively."""

    @staticmethod
    def resolve_dependencies(handler_signature: inspect.Signature, context: dict[str, Any]) -> dict[str, Any]:
        """
        Resolve all Depends() parameters in a handler signature.

        Args:
            handler_signature: Signature of the handler function
            context: Context dict with headers, query_string, body, etc.

        Returns:
            Dictionary of resolved dependency values
        """
        from turboapi.security import Depends

        resolved = {}
        cache = {}  # Cache for use_cache=True dependencies

        for param_name, param in handler_signature.parameters.items():
            if isinstance(param.default, Depends):
                depends = param.default
                dependency_fn = depends.dependency

                if dependency_fn is None:
                    continue

                # Check cache
                cache_key = id(dependency_fn)
                if depends.use_cache and cache_key in cache:
                    resolved[param_name] = cache[cache_key]
                    continue

                # Resolve the dependency
                result = DependencyResolver._call_dependency(dependency_fn, context, cache)

                # Cache if needed
                if depends.use_cache:
                    cache[cache_key] = result

                resolved[param_name] = result

        return resolved

    @staticmethod
    def _call_dependency(dependency_fn, context: dict[str, Any], cache: dict) -> Any:
        """Call a dependency function, resolving any nested dependencies."""
        from turboapi.security import Depends

        sig = inspect.signature(dependency_fn)
        kwargs = {}

        for param_name, param in sig.parameters.items():
            if isinstance(param.default, Depends):
                # Nested dependency
                nested_fn = param.default.dependency
                if nested_fn is not None:
                    cache_key = id(nested_fn)
                    if param.default.use_cache and cache_key in cache:
                        kwargs[param_name] = cache[cache_key]
                    else:
                        result = DependencyResolver._call_dependency(nested_fn, context, cache)
                        if param.default.use_cache:
                            cache[cache_key] = result
                        kwargs[param_name] = result

        # Call the dependency function
        if inspect.iscoroutinefunction(dependency_fn):
            # For async dependencies, we need to handle this differently
            # For now, just call sync functions
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(dependency_fn(**kwargs))
            finally:
                loop.close()
        else:
            return dependency_fn(**kwargs)


class QueryParamParser:
    """Parse query parameters from query string."""
    
    @staticmethod
    def parse_query_params(query_string: str) -> dict[str, Any]:
        """
        Parse query string into dict of parameters.
        Supports multiple values for same key (returns list).
        
        Args:
            query_string: URL query string (e.g., "q=test&limit=10")
            
        Returns:
            Dictionary of parsed query parameters
        """
        if not query_string:
            return {}
        
        params = {}
        parsed = urllib.parse.parse_qs(query_string, keep_blank_values=True)
        
        for key, values in parsed.items():
            # If only one value, return as string; otherwise return as list
            if len(values) == 1:
                params[key] = values[0]
            else:
                params[key] = values
        
        return params


class PathParamParser:
    """Parse path parameters from URL path."""
    
    @staticmethod
    def extract_path_params(route_pattern: str, actual_path: str) -> dict[str, str]:
        """
        Extract path parameters from actual path using route pattern.
        
        Args:
            route_pattern: Route pattern with {param} placeholders (e.g., "/users/{user_id}")
            actual_path: Actual request path (e.g., "/users/123")
            
        Returns:
            Dictionary of extracted path parameters
        """
        import re
        
        # Convert route pattern to regex
        # Replace {param} with named capture groups
        pattern = re.sub(r'\{(\w+)\}', r'(?P<\1>[^/]+)', route_pattern)
        pattern = f'^{pattern}$'
        
        match = re.match(pattern, actual_path)
        if match:
            return match.groupdict()
        
        return {}


class HeaderParser:
    """Parse and extract headers from request."""

    @staticmethod
    def parse_headers(headers_dict: dict[str, str], handler_signature: inspect.Signature) -> dict[str, Any]:
        """
        Parse headers and extract parameters needed by handler.

        Args:
            headers_dict: Dictionary of request headers
            handler_signature: Signature of the handler function

        Returns:
            Dictionary of parsed header parameters
        """
        from turboapi.datastructures import Header

        parsed_headers = {}

        # Check each parameter in handler signature
        for param_name, param in handler_signature.parameters.items():
            # Check if this parameter uses Header() marker
            is_header_param = isinstance(param.default, Header)

            if is_header_param:
                header_marker = param.default
                # Use alias if provided, otherwise convert param name to header format
                if header_marker.alias:
                    header_key = header_marker.alias.lower()
                elif header_marker.convert_underscores:
                    header_key = param_name.replace('_', '-').lower()
                else:
                    header_key = param_name.lower()

                # Find matching header
                for header_name, header_value in headers_dict.items():
                    if header_name.lower() == header_key:
                        parsed_headers[param_name] = header_value
                        break
                else:
                    # No matching header found, use default if available
                    if header_marker.default is not ...:
                        parsed_headers[param_name] = header_marker.default
            else:
                # Not a Header marker, but still try to match by name
                header_key = param_name.replace('_', '-').lower()
                for header_name, header_value in headers_dict.items():
                    if header_name.lower() == header_key:
                        parsed_headers[param_name] = header_value
                        break

        return parsed_headers


class RequestBodyParser:
    """Parse and validate request bodies using Satya models."""
    
    @staticmethod
    def parse_json_body(body: bytes, handler_signature: inspect.Signature) -> dict[str, Any]:
        """
        Parse JSON body and extract parameters for handler.
        
        Supports multiple patterns:
        1. Single parameter (dict/list/Model) - receives entire body
        2. Multiple parameters - extracts fields from JSON
        3. Satya Model - validates entire body
        
        Args:
            body: Raw request body bytes
            handler_signature: Signature of the handler function
            
        Returns:
            Dictionary of parsed parameters ready for handler
        """
        if not body:
            return {}
            
        try:
            json_data = json.loads(body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid JSON body: {e}")
        
        parsed_params = {}
        params_list = list(handler_signature.parameters.items())
        
        # PATTERN 1: Single parameter that should receive entire body
        # Examples: handler(data: dict), handler(items: list), handler(request: Model)
        if len(params_list) == 1:
            param_name, param = params_list[0]
            
            # Check if parameter is a Satya Model
            try:
                is_satya_model = inspect.isclass(param.annotation) and issubclass(param.annotation, Model)
            except Exception:
                is_satya_model = False
            
            if is_satya_model:
                # Validate entire JSON body against Satya model
                try:
                    validated_model = param.annotation.model_validate(json_data)
                    parsed_params[param_name] = validated_model
                    return parsed_params
                except Exception as e:
                    raise ValueError(f"Validation error for {param_name}: {e}")
            
            # If annotated as dict or list, pass entire body
            elif param.annotation in (dict, list) or param.annotation == inspect.Parameter.empty:
                parsed_params[param_name] = json_data
                return parsed_params
            
            # Check for typing.Dict, typing.List, etc.
            origin = get_origin(param.annotation)
            if origin in (dict, list):
                parsed_params[param_name] = json_data
                return parsed_params
        
        # PATTERN 2: Multiple parameters - extract individual fields
        # Example: handler(name: str, age: int, email: str)
        for param_name, param in params_list:
            if param.annotation == inspect.Parameter.empty:
                # No type annotation, try to match by name
                if param_name in json_data:
                    parsed_params[param_name] = json_data[param_name]
                continue
            
            # Check if parameter is a Satya Model
            try:
                is_satya_model = inspect.isclass(param.annotation) and issubclass(param.annotation, Model)
            except Exception:
                is_satya_model = False
            
            if is_satya_model:
                # Validate entire JSON body against Satya model
                try:
                    validated_model = param.annotation.model_validate(json_data)
                    parsed_params[param_name] = validated_model
                except Exception as e:
                    raise ValueError(f"Validation error for {param_name}: {e}")
            
            # Check if parameter name exists in JSON data
            elif param_name in json_data:
                value = json_data[param_name]
                
                # Type conversion for basic types
                if param.annotation in (int, float, str, bool):
                    try:
                        if param.annotation is bool and isinstance(value, str):
                            parsed_params[param_name] = value.lower() in ('true', '1', 'yes', 'on')
                        else:
                            parsed_params[param_name] = param.annotation(value)
                    except (ValueError, TypeError) as e:
                        raise ValueError(f"Invalid type for {param_name}: {e}")
                else:
                    # Use value as-is for other types (lists, dicts, etc.)
                    parsed_params[param_name] = value
            
            # Handle default values
            elif param.default != inspect.Parameter.empty:
                parsed_params[param_name] = param.default
        
        return parsed_params


class ResponseHandler:
    """Handle different response formats including FastAPI-style tuples."""
    
    @staticmethod
    def normalize_response(result: Any) -> tuple[Any, int]:
        """
        Normalize handler response to (content, status_code) format.

        Supports:
        - return {"data": "value"}  -> ({"data": "value"}, 200)
        - return {"error": "msg"}, 404  -> ({"error": "msg"}, 404)
        - return "text"  -> ("text", 200)
        - return satya_model  -> (model.model_dump(), 200)
        - return JSONResponse(content, status_code)  -> (content, status_code)
        - return HTMLResponse(content)  -> (content, 200)

        Args:
            result: Raw result from handler

        Returns:
            Tuple of (content, status_code)
        """
        # Handle Response objects (JSONResponse, HTMLResponse, etc.)
        from turboapi.responses import Response
        if isinstance(result, Response):
            # Extract content from Response object
            body = result.body
            if isinstance(body, bytes):
                # Try to decode as JSON for JSONResponse
                try:
                    import json
                    body = json.loads(body.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Keep as string for HTML/Text responses
                    body = body.decode('utf-8')
            return body, result.status_code

        # Handle tuple returns: (content, status_code)
        if isinstance(result, tuple):
            if len(result) == 2:
                content, status_code = result
                return content, status_code
            else:
                # Invalid tuple format, treat as regular response
                return result, 200

        # Handle dhi/Satya models
        if isinstance(result, Model):
            return result.model_dump(), 200

        # Handle dict with status_code key (internal format)
        if isinstance(result, dict) and "status_code" in result:
            status = result.pop("status_code")
            return result, status

        # Default: treat as 200 OK response
        return result, 200
    
    @staticmethod
    def format_json_response(content: Any, status_code: int) -> dict[str, Any]:
        """
        Format content as JSON response.
        
        Args:
            content: Response content
            status_code: HTTP status code
            
        Returns:
            Dictionary with properly formatted response
        """
        # Handle Satya models
        if isinstance(content, Model):
            content = content.model_dump()
        
        # Recursively convert any nested Satya models in dicts/lists
        def make_serializable(obj):
            if isinstance(obj, Model):
                return obj.model_dump()
            elif isinstance(obj, dict):
                return {k: make_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [make_serializable(item) for item in obj]
            elif isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            else:
                # Try to convert to string for unknown types
                return str(obj)
        
        content = make_serializable(content)
        
        return {
            "content": content,
            "status_code": status_code,
            "content_type": "application/json"
        }


def create_enhanced_handler(original_handler, route_definition):
    """
    Create an enhanced handler with automatic body parsing and response normalization.
    
    This wrapper:
    1. Parses JSON body automatically using Satya validation
    2. Normalizes responses (supports tuple returns)
    3. Provides better error messages
    4. Properly handles both sync and async handlers
    
    Args:
        original_handler: The original Python handler function
        route_definition: RouteDefinition with metadata
        
    Returns:
        Enhanced handler function (async if original is async, sync otherwise)
    """
    sig = inspect.signature(original_handler)
    is_async = inspect.iscoroutinefunction(original_handler)
    
    if is_async:
        # Create async enhanced handler for async original handlers
        async def enhanced_handler(**kwargs):
            """Enhanced handler with automatic parsing of body, query params, path params, and headers."""
            try:
                parsed_params = {}
                
                # 1. Parse query parameters
                if "query_string" in kwargs:
                    query_string = kwargs.get("query_string", "")
                    if query_string:
                        query_params = QueryParamParser.parse_query_params(query_string)
                        parsed_params.update(query_params)
                
                # 2. Parse path parameters (if route pattern is available)
                if "path" in kwargs and hasattr(route_definition, 'path'):
                    actual_path = kwargs.get("path", "")
                    route_pattern = route_definition.path
                    if actual_path and route_pattern:
                        path_params = PathParamParser.extract_path_params(route_pattern, actual_path)
                        parsed_params.update(path_params)
                
                # 3. Parse headers
                if "headers" in kwargs:
                    headers_dict = kwargs.get("headers", {})
                    if headers_dict:
                        header_params = HeaderParser.parse_headers(headers_dict, sig)
                        parsed_params.update(header_params)
                
                # 4. Parse request body (JSON)
                if "body" in kwargs:
                    body_data = kwargs["body"]

                    if body_data:  # Only parse if body is not empty
                        parsed_body = RequestBodyParser.parse_json_body(
                            body_data,
                            sig
                        )
                        # Merge parsed body params (body params take precedence)
                        parsed_params.update(parsed_body)

                # 5. Resolve dependencies
                context = {
                    "headers": kwargs.get("headers", {}),
                    "query_string": kwargs.get("query_string", ""),
                    "body": kwargs.get("body", b""),
                }
                dependency_params = DependencyResolver.resolve_dependencies(sig, context)
                parsed_params.update(dependency_params)

                # Filter to only pass expected parameters
                filtered_kwargs = {
                    k: v for k, v in parsed_params.items()
                    if k in sig.parameters
                }

                # Call original async handler and await it
                result = await original_handler(**filtered_kwargs)
                
                # Normalize response
                content, status_code = ResponseHandler.normalize_response(result)
                
                return ResponseHandler.format_json_response(content, status_code)
                
            except ValueError as e:
                # Validation or parsing error (400 Bad Request)
                return ResponseHandler.format_json_response(
                    {"error": "Bad Request", "detail": str(e)},
                    400
                )
            except Exception as e:
                # Unexpected error (500 Internal Server Error)
                import traceback
                return ResponseHandler.format_json_response(
                    {
                        "error": "Internal Server Error",
                        "detail": str(e),
                        "traceback": traceback.format_exc()
                    },
                    500
                )
        
        return enhanced_handler
    
    else:
        # Create sync enhanced handler for sync original handlers
        def enhanced_handler(**kwargs):
            """Enhanced handler with automatic parsing of body, query params, path params, and headers."""
            try:
                parsed_params = {}
                
                # 1. Parse query parameters
                if "query_string" in kwargs:
                    query_string = kwargs.get("query_string", "")
                    if query_string:
                        query_params = QueryParamParser.parse_query_params(query_string)
                        parsed_params.update(query_params)
                
                # 2. Parse path parameters (if route pattern is available)
                if "path" in kwargs and hasattr(route_definition, 'path'):
                    actual_path = kwargs.get("path", "")
                    route_pattern = route_definition.path
                    if actual_path and route_pattern:
                        path_params = PathParamParser.extract_path_params(route_pattern, actual_path)
                        parsed_params.update(path_params)
                
                # 3. Parse headers
                if "headers" in kwargs:
                    headers_dict = kwargs.get("headers", {})
                    if headers_dict:
                        header_params = HeaderParser.parse_headers(headers_dict, sig)
                        parsed_params.update(header_params)
                
                # 4. Parse request body (JSON)
                if "body" in kwargs:
                    body_data = kwargs["body"]

                    if body_data:  # Only parse if body is not empty
                        parsed_body = RequestBodyParser.parse_json_body(
                            body_data,
                            sig
                        )
                        # Merge parsed body params (body params take precedence)
                        parsed_params.update(parsed_body)

                # 5. Resolve dependencies
                context = {
                    "headers": kwargs.get("headers", {}),
                    "query_string": kwargs.get("query_string", ""),
                    "body": kwargs.get("body", b""),
                }
                dependency_params = DependencyResolver.resolve_dependencies(sig, context)
                parsed_params.update(dependency_params)

                # Filter to only pass expected parameters
                filtered_kwargs = {
                    k: v for k, v in parsed_params.items()
                    if k in sig.parameters
                }

                # Call original sync handler
                result = original_handler(**filtered_kwargs)
                
                # Normalize response
                content, status_code = ResponseHandler.normalize_response(result)
                
                return ResponseHandler.format_json_response(content, status_code)
                
            except ValueError as e:
                # Validation or parsing error (400 Bad Request)
                return ResponseHandler.format_json_response(
                    {"error": "Bad Request", "detail": str(e)},
                    400
                )
            except Exception as e:
                # Unexpected error (500 Internal Server Error)
                import traceback
                return ResponseHandler.format_json_response(
                    {
                        "error": "Internal Server Error",
                        "detail": str(e),
                        "traceback": traceback.format_exc()
                    },
                    500
                )
        
        return enhanced_handler
