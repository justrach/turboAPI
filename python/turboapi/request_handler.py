"""
Enhanced Request Handler with dhi Integration
Provides FastAPI-compatible automatic JSON body parsing and validation
Supports query parameters, path parameters, headers, request body, and dependencies
"""

import inspect
import json
import urllib.parse
from typing import Any, get_origin

from dhi import BaseModel as Model


class DependencyResolver:
    """Resolve Depends() dependencies recursively with caching and cleanup."""

    @staticmethod
    def resolve_dependencies(
        handler_signature: inspect.Signature, context: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Resolve all Depends/Security parameters.

        Args:
            handler_signature: Signature of the handler function
            context: Context dict with headers, query_string, body, etc.

        Returns:
            Dictionary of resolved dependency values
        """
        from turboapi.security import get_depends

        cache = {}
        cleanups = []  # generators to close after request
        resolved = {}

        for param_name, param in handler_signature.parameters.items():
            depends = get_depends(param)
            if depends is not None:
                dep_fn = depends.dependency
                if dep_fn is None:
                    continue

                value = DependencyResolver._resolve_single(
                    dep_fn, depends.use_cache, context, cache, cleanups
                )
                resolved[param_name] = value

        # Store cleanups in context for later teardown
        context["_cleanups"] = cleanups
        return resolved

    @staticmethod
    def _resolve_single(dep_fn, use_cache, context, cache, cleanups):
        """Resolve a single dependency, handling sub-deps, caching, generators."""
        from turboapi.security import SecurityBase, get_depends

        cache_key = id(dep_fn)
        if use_cache and cache_key in cache:
            return cache[cache_key]

        # First resolve any sub-dependencies this function needs
        sub_kwargs = {}
        if callable(dep_fn):
            try:
                sig = inspect.signature(dep_fn)
                for p_name, p in sig.parameters.items():
                    sub_dep = get_depends(p)
                    if sub_dep is not None and sub_dep.dependency is not None:
                        sub_kwargs[p_name] = DependencyResolver._resolve_single(
                            sub_dep.dependency, sub_dep.use_cache, context, cache, cleanups
                        )
            except (ValueError, TypeError):
                pass

        # Check if it's a security scheme callable
        if isinstance(dep_fn, SecurityBase) and hasattr(dep_fn, "__call__"):
            # Inspect __call__ signature to pass the right context
            try:
                call_sig = inspect.signature(dep_fn.__call__)
                call_params = list(call_sig.parameters.keys())
            except (ValueError, TypeError):
                call_params = []

            if "headers" in call_params:
                # APIKeyHeader — pass full headers dict
                result = dep_fn(headers=context.get("headers", {}))
            elif "query_params" in call_params:
                # APIKeyQuery — parse query string into dict
                from urllib.parse import parse_qs

                qs = context.get("query_string", "")
                qp = (
                    {k: v[0] for k, v in parse_qs(qs, keep_blank_values=True).items()} if qs else {}
                )
                result = dep_fn(query_params=qp)
            elif "cookies" in call_params:
                # APIKeyCookie — pass cookies dict
                result = dep_fn(cookies=context.get("cookies", {}))
            else:
                # OAuth2/HTTPBearer/HTTPBasic — pass authorization header
                headers = context.get("headers", {})
                auth_header = None
                for k, v in headers.items():
                    if k.lower() == "authorization":
                        auth_header = v
                        break
                result = dep_fn(auth_header)
        elif inspect.isgeneratorfunction(dep_fn):
            gen = dep_fn(**sub_kwargs)
            result = next(gen)
            cleanups.append(gen)
        elif inspect.isasyncgenfunction(dep_fn):
            import asyncio

            async def _resolve_async_gen():
                agen = dep_fn(**sub_kwargs)
                val = await agen.__anext__()
                cleanups.append(agen)
                return val

            result = asyncio.run(_resolve_async_gen())
        elif inspect.iscoroutinefunction(dep_fn):
            import asyncio

            result = asyncio.run(dep_fn(**sub_kwargs))
        else:
            result = dep_fn(**sub_kwargs)

        if use_cache:
            cache[cache_key] = result
        return result


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
    def extract_path_params(
        route_pattern: str, actual_path: str, handler_signature: inspect.Signature | None = None
    ) -> dict[str, Any]:
        """
        Extract path parameters from actual path using route pattern.

        Args:
            route_pattern: Route pattern with {param} placeholders (e.g., "/users/{user_id}")
            actual_path: Actual request path (e.g., "/users/123")
            handler_signature: Optional handler signature for type coercion

        Returns:
            Dictionary of extracted path parameters (type-coerced if signature provided)
        """
        import re

        # Convert route pattern to regex
        # Replace {param} with named capture groups
        pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", route_pattern)
        pattern = f"^{pattern}$"

        match = re.match(pattern, actual_path)
        if not match:
            return {}

        params = match.groupdict()

        # Coerce types based on handler signature annotations
        if handler_signature:
            for name, value in params.items():
                if name in handler_signature.parameters:
                    annotation = handler_signature.parameters[name].annotation
                    try:
                        if annotation is int:
                            params[name] = int(value)
                        elif annotation is float:
                            params[name] = float(value)
                        elif annotation is bool:
                            params[name] = value.lower() in ("true", "1", "yes")
                    except (ValueError, TypeError):
                        pass  # keep as string

        return params


class HeaderParser:
    """Parse and extract headers from request."""

    @staticmethod
    def parse_headers(
        headers_dict: dict[str, str], handler_signature: inspect.Signature
    ) -> dict[str, Any]:
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
                    header_key = param_name.replace("_", "-").lower()
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
                header_key = param_name.replace("_", "-").lower()
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
            # CRITICAL: Make a defensive copy immediately using bytearray to force real copy
            # Free-threaded Python with Metal/MLX can have concurrent memory access issues
            body_copy = bytes(bytearray(body))
            json_data = json.loads(body_copy.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid JSON body: {e}")

        parsed_params = {}
        params_list = list(handler_signature.parameters.items())

        # Filter out Depends/Security parameters — they are resolved separately
        from turboapi.security import Depends, SecurityBase, get_depends

        body_params_list = [
            (name, p)
            for name, p in params_list
            if not isinstance(p.default, (Depends, SecurityBase)) and get_depends(p) is None
        ]

        # PATTERN 1: Single parameter that should receive entire body
        # Examples: handler(data: dict), handler(items: list), handler(request: Model)
        if len(body_params_list) == 1:
            param_name, param = body_params_list[0]

            # Check if parameter is a Satya Model
            try:
                is_satya_model = inspect.isclass(param.annotation) and issubclass(
                    param.annotation, Model
                )
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
            # Check for typing.Dict, typing.List, etc.
            origin = get_origin(param.annotation)
            if origin in (dict, list):
                parsed_params[param_name] = json_data
                return parsed_params

            # Check for Pydantic-like models (model_validate, e.g. pydantic.BaseModel)
            if inspect.isclass(param.annotation) and hasattr(param.annotation, "model_validate"):
                try:
                    validated_model = param.annotation.model_validate(json_data)
                    parsed_params[param_name] = validated_model
                    return parsed_params
                except Exception as e:
                    raise ValueError(f"Validation error for {param_name}: {e}")

            # Unknown class annotation with single param — try direct construction
            if inspect.isclass(param.annotation):
                try:
                    parsed_params[param_name] = param.annotation(**json_data)
                    return parsed_params
                except Exception:
                    pass

        # PATTERN 2: Multiple parameters - extract individual fields
        # Example: handler(name: str, age: int, email: str)
        for param_name, param in body_params_list:
            if param.annotation == inspect.Parameter.empty:
                # No type annotation, try to match by name
                if param_name in json_data:
                    parsed_params[param_name] = json_data[param_name]
                continue

            # Check if parameter is a Satya Model
            try:
                is_satya_model = inspect.isclass(param.annotation) and issubclass(
                    param.annotation, Model
                )
            except Exception:
                is_satya_model = False

            if is_satya_model:
                # Validate entire JSON body against Satya model
                try:
                    validated_model = param.annotation.model_validate(json_data)
                    parsed_params[param_name] = validated_model
                except Exception as e:
                    raise ValueError(f"Validation error for {param_name}: {e}")

            # Check for Pydantic-like model (model_validate but not Satya)
            elif inspect.isclass(param.annotation) and hasattr(param.annotation, "model_validate"):
                try:
                    parsed_params[param_name] = param.annotation.model_validate(json_data)
                except Exception as e:
                    raise ValueError(f"Validation error for {param_name}: {e}")
            # Check if parameter name exists in JSON data
            elif param_name in json_data:
                value = json_data[param_name]

                # Type conversion for basic types
                if param.annotation in (int, float, str, bool):
                    try:
                        if param.annotation is bool and isinstance(value, str):
                            parsed_params[param_name] = value.lower() in ("true", "1", "yes", "on")
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


def _is_binary_content_type(content_type: str) -> bool:
    """Check if the content type indicates binary data."""
    if not content_type:
        return False
    ct_lower = content_type.lower()
    # Binary content types that should not be JSON serialized
    binary_prefixes = (
        "audio/",
        "video/",
        "image/",
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "application/gzip",
        "application/x-tar",
    )
    return ct_lower.startswith(binary_prefixes)


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
            Tuple of (content, status_code) or (content, status_code, content_type)
        """
        # Handle Response objects (JSONResponse, HTMLResponse, etc.)
        from turboapi.responses import Response

        if isinstance(result, Response):
            # Extract content from Response object
            body = result.body
            content_type = result.media_type

            # Collect extra headers (non-empty headers dict + cookies)
            extra_headers: dict = {}
            for k, v in result.headers.items():
                if k.lower() not in {"content-type", "content-length"}:
                    extra_headers[k] = v
            for cookie in getattr(result, "_cookies", []):
                existing = extra_headers.get("set-cookie")
                if existing is None:
                    extra_headers["set-cookie"] = cookie
                else:
                    # Accumulate as list; caller handles multi-value emission
                    if isinstance(existing, list):
                        existing.append(cookie)
                    else:
                        extra_headers["set-cookie"] = [existing, cookie]

            # For binary content types, return raw bytes
            if content_type and _is_binary_content_type(content_type):
                return body, result.status_code, content_type, extra_headers

            if isinstance(body, bytes):
                # Try to decode as JSON for JSONResponse
                try:
                    import json

                    body = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError:
                    # Not JSON, try as plain text
                    try:
                        body = body.decode("utf-8")
                    except UnicodeDecodeError:
                        # Binary data - return with content_type
                        return body, result.status_code, content_type, extra_headers
                except UnicodeDecodeError:
                    # Binary data - return with content_type
                    return body, result.status_code, content_type, extra_headers
            return body, result.status_code, content_type, extra_headers

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
            status = result["status_code"]
            content = {k: v for k, v in result.items() if k != "status_code"}
            return content, status

        # Default: treat as 200 OK response
        return result, 200

    @staticmethod
    def format_response(
        content: Any,
        status_code: int,
        content_type: str | None = None,
        extra_headers: dict | None = None,
    ) -> dict[str, Any]:
        """
        Format content as response. Handles both JSON and binary responses.

        Args:
            content: Response content (can be dict, str, bytes, etc.)
            status_code: HTTP status code
            content_type: Optional content type (for binary responses)
            extra_headers: Optional dict of extra response headers (e.g. Set-Cookie)

        Returns:
            Dictionary with properly formatted response
        """
        # For binary content (bytes with binary content_type), return directly
        if isinstance(content, bytes) and content_type and _is_binary_content_type(content_type):
            result: dict[str, Any] = {
                "content": content,  # Keep as bytes for Zig to extract
                "status_code": status_code,
                "content_type": content_type,
            }
            if extra_headers:
                result["extra_headers"] = extra_headers
            return result

        # Handle Satya models
        if isinstance(content, Model):
            content = content.model_dump()

        # Recursively convert any nested Satya models in dicts/lists
        def make_serializable(obj):
            if isinstance(obj, Model):
                return obj.model_dump()
            elif isinstance(obj, bytes):
                # Non-binary bytes - try to decode as UTF-8, otherwise base64 encode
                try:
                    return obj.decode("utf-8")
                except UnicodeDecodeError:
                    import base64

                    return base64.b64encode(obj).decode("ascii")
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

        result = {
            "content": content,
            "status_code": status_code,
            "content_type": content_type or "application/json",
        }
        if extra_headers:
            result["extra_headers"] = extra_headers
        return result

    @staticmethod
    def format_json_response(
        content: Any,
        status_code: int,
        content_type: str | None = None,
        extra_headers: dict | None = None,
    ) -> dict[str, Any]:
        """Alias for format_response for backwards compatibility."""
        return ResponseHandler.format_response(content, status_code, content_type, extra_headers)


_json_dumps = __import__("json").dumps


def _format_zig_tuple(content, status_code, content_type=None):
    """Return (status_code, content_type, body) 3-tuple for Zig's sendTupleResponse."""
    ct = content_type or "application/json"
    if isinstance(content, bytes):
        return (status_code, ct, content)
    if hasattr(content, "model_dump"):
        content = content.model_dump()
    try:
        return (status_code, ct, _json_dumps(content))
    except Exception:
        return (status_code, "application/json", _json_dumps({"error": str(content)}))


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

    # Pre-compile path param regex and type converters at registration time
    import re as _re

    _path_pattern = None
    _path_param_types = {}
    if hasattr(route_definition, "path") and route_definition.path:
        rp = route_definition.path
        if "{" in rp:
            _path_pattern = _re.compile("^" + _re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", rp) + "$")
        for pname, param in sig.parameters.items():
            ann = param.annotation
            if ann is int:
                _path_param_types[pname] = int
            elif ann is float:
                _path_param_types[pname] = float
            elif ann is bool:
                _path_param_types[pname] = lambda v: v.lower() in ("true", "1", "yes")

    # Pre-check which features this handler needs
    _param_names = set(sig.parameters.keys())
    _has_dependencies = False
    _has_header_params = False
    _has_form_params = False
    from turboapi.datastructures import Header

    try:
        from turboapi.security import Depends, SecurityBase, get_depends

        _has_security = True
    except ImportError:
        _has_security = False
    try:
        from turboapi.datastructures import File, Form
        from turboapi.datastructures import UploadFile as _UploadFile

        _has_form_types = True
    except ImportError:
        _has_form_types = False

    for pname, param in sig.parameters.items():
        if isinstance(param.default, Header):
            _has_header_params = True
        elif _has_form_types and isinstance(param.default, (Form, File)):
            _has_form_params = True
        elif _has_form_types and (
            param.annotation is _UploadFile
            or (isinstance(param.annotation, type) and issubclass(param.annotation, _UploadFile))
        ):
            _has_form_params = True
        elif not (
            _has_security
            and (
                isinstance(param.default, (Depends, SecurityBase)) or get_depends(param) is not None
            )
        ):
            _has_header_params = True
        if _has_security and (
            isinstance(param.default, (Depends, SecurityBase)) or get_depends(param) is not None
        ):
            _has_dependencies = True
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
                if "path" in kwargs and hasattr(route_definition, "path"):
                    actual_path = kwargs.get("path", "")
                    route_pattern = route_definition.path
                    if actual_path and route_pattern:
                        path_params = PathParamParser.extract_path_params(
                            route_pattern, actual_path, sig
                        )
                        parsed_params.update(path_params)

                # 3. Parse headers
                if "headers" in kwargs:
                    headers_dict = kwargs.get("headers", {})
                    if headers_dict:
                        header_params = HeaderParser.parse_headers(headers_dict, sig)
                        parsed_params.update(header_params)

                # 3.5. Resolve Form / File / UploadFile parameters from Zig-parsed data
                _form_fields = kwargs.get("form_fields", {})
                _file_fields = kwargs.get("file_fields", [])
                if _has_form_params:
                    for pname, param in sig.parameters.items():
                        if _has_form_types and isinstance(param.default, Form):
                            key = param.default.alias or pname
                            if key in _form_fields:
                                parsed_params[pname] = _form_fields[key]
                            elif param.default.default is not ...:
                                parsed_params[pname] = param.default.default
                        elif _has_form_types and isinstance(param.default, File):
                            key = param.default.alias or pname
                            matched = None
                            for ff in _file_fields:
                                if ff.get("name") == key:
                                    matched = ff
                                    break
                            if matched:
                                uf = _UploadFile(
                                    filename=matched.get("filename"),
                                    content_type=matched.get(
                                        "content_type", "application/octet-stream"
                                    ),
                                    size=len(matched.get("body", b"")),
                                )
                                uf.file.write(matched.get("body", b""))
                                uf.file.seek(0)
                                parsed_params[pname] = uf
                            elif param.default.default is not ...:
                                parsed_params[pname] = param.default.default
                        elif _has_form_types and (
                            param.annotation is _UploadFile
                            or (
                                isinstance(param.annotation, type)
                                and issubclass(param.annotation, _UploadFile)
                            )
                        ):
                            key = pname
                            matched = None
                            for ff in _file_fields:
                                if ff.get("name") == key:
                                    matched = ff
                                    break
                            if matched:
                                uf = _UploadFile(
                                    filename=matched.get("filename"),
                                    content_type=matched.get(
                                        "content_type", "application/octet-stream"
                                    ),
                                    size=len(matched.get("body", b"")),
                                )
                                uf.file.write(matched.get("body", b""))
                                uf.file.seek(0)
                                parsed_params[pname] = uf

                # 4. Parse request body (JSON) — skip if form data was already parsed
                if "body" in kwargs:
                    body_data = kwargs["body"]
                    if body_data and not (_form_fields or _file_fields):
                        parsed_body = RequestBodyParser.parse_json_body(body_data, sig)
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
                filtered_kwargs = {k: v for k, v in parsed_params.items() if k in sig.parameters}

                # Call original async handler and await it
                result = await original_handler(**filtered_kwargs)

                # Run dependency cleanups (generator teardown)
                cleanups = context.get("_cleanups", [])
                for gen in cleanups:
                    try:
                        next(gen)
                    except StopIteration:
                        pass
                    except Exception:
                        pass

                # Normalize response - may return 2, 3, or 4-element tuple
                normalized = ResponseHandler.normalize_response(result)
                extra_headers = None
                if len(normalized) == 4:
                    content, status_code, content_type, extra_headers = normalized
                elif len(normalized) == 3:
                    content, status_code, content_type = normalized
                else:
                    content, status_code = normalized
                    content_type = None

                return ResponseHandler.format_json_response(content, status_code, content_type, extra_headers)

            except ValueError as e:
                return ResponseHandler.format_json_response(
                    {"error": "Bad Request", "detail": str(e)}, 400
                )
            except Exception as e:
                from turboapi.security import HTTPException

                if isinstance(e, HTTPException):
                    return ResponseHandler.format_json_response({"detail": e.detail}, e.status_code)
                import traceback

                return ResponseHandler.format_json_response(
                    {
                        "error": "Internal Server Error",
                        "detail": str(e),
                        "traceback": traceback.format_exc(),
                    },
                    500,
                )

        return enhanced_handler

    else:
        # Create sync enhanced handler for sync original handlers
        def enhanced_handler(**kwargs):
            """Enhanced handler with automatic parsing of body, query params, path params, and headers."""
            try:
                parsed_params = {}

                # 1. Parse query parameters
                query_string = kwargs.get("query_string", "")
                if query_string:
                    query_params = QueryParamParser.parse_query_params(query_string)
                    parsed_params.update(query_params)

                # 2. Parse path parameters using pre-compiled regex
                if _path_pattern is not None:
                    actual_path = kwargs.get("path", "")
                    if actual_path:
                        m = _path_pattern.match(actual_path)
                        if m:
                            params = m.groupdict()
                            for k, v in params.items():
                                converter = _path_param_types.get(k)
                                if converter:
                                    try:
                                        params[k] = converter(v)
                                    except (ValueError, TypeError):
                                        pass
                            parsed_params.update(params)

                # 3. Parse headers (only if handler needs them)
                if _has_header_params:
                    headers_dict = kwargs.get("headers", {})
                    if headers_dict:
                        header_params = HeaderParser.parse_headers(headers_dict, sig)
                        parsed_params.update(header_params)

                # 3.5. Resolve Form / File / UploadFile parameters from Zig-parsed data
                _form_fields = kwargs.get("form_fields", {})
                _file_fields = kwargs.get("file_fields", [])
                if _has_form_params:
                    for pname, param in sig.parameters.items():
                        if _has_form_types and isinstance(param.default, Form):
                            key = param.default.alias or pname
                            if key in _form_fields:
                                parsed_params[pname] = _form_fields[key]
                            elif param.default.default is not ...:
                                parsed_params[pname] = param.default.default
                        elif _has_form_types and isinstance(param.default, File):
                            key = param.default.alias or pname
                            matched = None
                            for ff in _file_fields:
                                if ff.get("name") == key:
                                    matched = ff
                                    break
                            if matched:
                                uf = _UploadFile(
                                    filename=matched.get("filename"),
                                    content_type=matched.get(
                                        "content_type", "application/octet-stream"
                                    ),
                                    size=len(matched.get("body", b"")),
                                )
                                uf.file.write(matched.get("body", b""))
                                uf.file.seek(0)
                                parsed_params[pname] = uf
                            elif param.default.default is not ...:
                                parsed_params[pname] = param.default.default
                        elif _has_form_types and (
                            param.annotation is _UploadFile
                            or (
                                isinstance(param.annotation, type)
                                and issubclass(param.annotation, _UploadFile)
                            )
                        ):
                            key = pname
                            matched = None
                            for ff in _file_fields:
                                if ff.get("name") == key:
                                    matched = ff
                                    break
                            if matched:
                                uf = _UploadFile(
                                    filename=matched.get("filename"),
                                    content_type=matched.get(
                                        "content_type", "application/octet-stream"
                                    ),
                                    size=len(matched.get("body", b"")),
                                )
                                uf.file.write(matched.get("body", b""))
                                uf.file.seek(0)
                                parsed_params[pname] = uf

                # 4. Parse request body (JSON) — skip if form data was already parsed
                body_data = kwargs.get("body", b"")
                if body_data and not (_form_fields or _file_fields):
                    parsed_body = RequestBodyParser.parse_json_body(body_data, sig)
                    parsed_params.update(parsed_body)

                # 5. Resolve dependencies (only if handler uses Depends/Security)
                if _has_dependencies:
                    context = {
                        "headers": kwargs.get("headers", {}),
                        "query_string": query_string,
                        "body": body_data,
                    }
                    dependency_params = DependencyResolver.resolve_dependencies(sig, context)
                    parsed_params.update(dependency_params)

                # Filter to only pass expected parameters
                filtered_kwargs = {k: v for k, v in parsed_params.items() if k in _param_names}

                # Call original sync handler
                result = original_handler(**filtered_kwargs)

                # Run dependency cleanups (generator teardown)
                if _has_dependencies:
                    cleanups = context.get("_cleanups", [])
                    for gen in cleanups:
                        try:
                            next(gen)
                        except StopIteration:
                            pass
                        except Exception:
                            pass

                # Normalize response - may return 2, 3, or 4-element tuple
                normalized = ResponseHandler.normalize_response(result)
                extra_headers = None
                if len(normalized) == 4:
                    content, status_code, content_type, extra_headers = normalized
                elif len(normalized) == 3:
                    content, status_code, content_type = normalized
                else:
                    content, status_code = normalized
                    content_type = None

                return ResponseHandler.format_json_response(content, status_code, content_type, extra_headers)

            except ValueError as e:
                return ResponseHandler.format_json_response(
                    {"error": "Bad Request", "detail": str(e)}, 400
                )
            except Exception as e:
                from turboapi.security import HTTPException

                if isinstance(e, HTTPException):
                    return ResponseHandler.format_json_response({"detail": e.detail}, e.status_code)
                import traceback

                return ResponseHandler.format_json_response(
                    {
                        "error": "Internal Server Error",
                        "detail": str(e),
                        "traceback": traceback.format_exc(),
                    },
                    500,
                )

        return enhanced_handler


def create_pos_handler(original_handler):
    """Minimal positional wrapper for PyObject_Vectorcall dispatch.

    Zig assembles args from path/query params and calls this positionally —
    zero **kwargs dict, zero parse_qs, zero call_kwargs allocation.
    Returns (status_code, content_type, body) 3-tuple for sendTupleResponse.
    """
    import json as _json

    _dumps = _json.dumps
    from turboapi.responses import Response as _Response

    def pos_handler(*args):
        try:
            result = original_handler(*args)
            if isinstance(result, _Response):
                body = (
                    result.body if isinstance(result.body, bytes) else result.body.encode("utf-8")
                )
                return (result.status_code, result.media_type or "application/json", body)
            if hasattr(result, "model_dump"):
                result = result.model_dump()
            if isinstance(result, tuple) and len(result) == 2:
                return (result[1], "application/json", _dumps(result[0]))
            return (200, "application/json", _dumps(result))
        except Exception as e:
            try:
                from turboapi.exceptions import HTTPException as _HTTPException

                if isinstance(e, _HTTPException):
                    return (e.status_code, "application/json", _dumps({"detail": e.detail}))
            except ImportError:
                pass
            return (500, "application/json", _dumps({"error": str(e)}))

    return pos_handler


def create_fast_handler(original_handler, route_definition):
    """Create a minimal-overhead handler for simple sync routes.

    Returns a 3-tuple (status_code, content_type, body_str) so Zig can unpack
    via PyTuple_GET_ITEM — eliminates 3x PyDict_GetItemString per request.
    """
    import json as _json

    sig = inspect.signature(original_handler)
    param_names = set(sig.parameters.keys())

    # Pre-build type converters for path params
    _converters: dict[str, type] = {}
    for pname, param in sig.parameters.items():
        ann = param.annotation
        if ann is int:
            _converters[pname] = int
        elif ann is float:
            _converters[pname] = float

    method_str = (
        route_definition.method.value.upper() if hasattr(route_definition, "method") else "GET"
    )
    _needs_body = method_str in ("POST", "PUT", "PATCH", "DELETE")

    _dumps = _json.dumps

    from turboapi.responses import Response as _Response

    if not param_names:
        # Zero-arg handler: fastest possible path — returns 3-tuple for Zig
        def fast_handler_noargs(**kwargs):
            try:
                result = original_handler()
                if isinstance(result, _Response):
                    ct = result.media_type or "application/json"
                    body = (
                        result.body
                        if isinstance(result.body, bytes)
                        else result.body.encode("utf-8")
                    )
                    return (result.status_code, ct, body)
                if isinstance(result, tuple) and len(result) == 2:
                    return (result[1], "application/json", _dumps(result[0]))
                if hasattr(result, "model_dump"):
                    result = result.model_dump()
                return (200, "application/json", _dumps(result))
            except Exception as e:
                try:
                    from turboapi.exceptions import HTTPException as _HTTPException

                    if isinstance(e, _HTTPException):
                        return (e.status_code, "application/json", _dumps({"detail": e.detail}))
                except ImportError:
                    pass
                return (500, "application/json", _dumps({"error": str(e)}))

        return fast_handler_noargs

    def fast_handler(**kwargs):
        try:
            call_kwargs = {}

            path_params = kwargs.get("path_params")
            if path_params:
                for k, v in path_params.items():
                    if k in param_names:
                        converter = _converters.get(k)
                        call_kwargs[k] = converter(v) if converter else v

            if len(call_kwargs) < len(param_names):
                qs = kwargs.get("query_string", "")
                if qs:
                    from urllib.parse import parse_qs

                    for k, v in parse_qs(qs, keep_blank_values=True).items():
                        if k in param_names and k not in call_kwargs:
                            call_kwargs[k] = v[0]

            if _needs_body:
                body = kwargs.get("body", b"")
                if body:
                    parsed_body = RequestBodyParser.parse_json_body(body, sig)
                    call_kwargs.update(parsed_body)

            result = original_handler(**call_kwargs)

            if isinstance(result, _Response):
                ct = result.media_type or "application/json"
                body = (
                    result.body if isinstance(result.body, bytes) else result.body.encode("utf-8")
                )
                return (result.status_code, ct, body)

            if hasattr(result, "model_dump"):
                result = result.model_dump()
            if isinstance(result, tuple) and len(result) == 2:
                return (result[1], "application/json", _dumps(result[0]))
            return (200, "application/json", _dumps(result))
        except Exception as e:
            try:
                from turboapi.exceptions import HTTPException

                if isinstance(e, HTTPException):
                    return (e.status_code, "application/json", _dumps({"detail": e.detail}))
            except ImportError:
                pass
            return (500, "application/json", _dumps({"error": str(e)}))

    return fast_handler


def create_fast_model_handler(original_handler, model_class, param_name):
    """Create a minimal handler for model_sync routes.

    Zig has already validated the JSON body against the schema.
    Returns a 3-tuple (status_code, content_type, body_str) for tuple ABI.
    """
    import json as _json

    _loads = _json.loads
    _dumps = _json.dumps

    def fast_model_handler(**kwargs):
        try:
            data = kwargs.get("body_dict")
            if data is None:
                body = kwargs.get("body", b"")
                if not body:
                    return (400, "application/json", _dumps({"detail": "Request body is empty"}))
                data = _loads(body)

            model = model_class(**data)
            result = original_handler(**{param_name: model})

            if hasattr(result, "model_dump"):
                result = result.model_dump()
            if isinstance(result, tuple) and len(result) == 2:
                return (result[1], "application/json", _dumps(result[0]))
            return (200, "application/json", _dumps(result))
        except Exception as e:
            try:
                from turboapi.exceptions import HTTPException

                if isinstance(e, HTTPException):
                    return (e.status_code, "application/json", _dumps({"detail": e.detail}))
            except ImportError:
                pass
            return (500, "application/json", _dumps({"error": str(e)}))

    return fast_model_handler
