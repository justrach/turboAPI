"""
TurboAPI Direct Zig Integration
Connects FastAPI-compatible routing directly to Zig HTTP core with zero overhead.
Phase 3: Handler classification for fast dispatch (bypass Python enhanced wrapper).
"""

import inspect
import json
from typing import Any, get_origin

try:
    from dhi import BaseModel
except ImportError:
    # Dhi not installed - Model-based handlers won't get special treatment
    BaseModel = None

from .main_app import TurboAPI
from .models import Request, Response
from .request_handler import (
    create_enhanced_handler,
    create_fast_handler,
    create_fast_model_handler,
    create_pos_handler,
)
from .version_check import CHECK_MARK, CROSS_MARK, ROCKET


def classify_handler(handler, route) -> tuple[str, dict[str, str], dict]:
    """Classify a handler for fast dispatch (Phase 3 + Phase 4 async).

    Returns:
        (handler_type, param_types, model_info) where:
        - handler_type: "simple_sync" | "body_sync" | "model_sync" | "simple_async" | "body_async" | "enhanced"
        - param_types: dict mapping param_name -> type hint string
        - model_info: dict with "param_name" and "model_class" for model handlers
    """
    is_async = inspect.iscoroutinefunction(handler)

    sig = inspect.signature(handler)
    param_types = {}
    needs_body = False
    has_depends = False
    model_info = {}

    # Check for Depends/SecurityBase — forces enhanced path
    try:
        from .security import Depends, SecurityBase, get_depends

        for _, param in sig.parameters.items():
            if isinstance(param.default, (Depends, SecurityBase)) or get_depends(param) is not None:
                has_depends = True
                break
    except ImportError:
        pass

    if has_depends:
        return "enhanced", {}, {}

    for param_name, param in sig.parameters.items():
        annotation = param.annotation

        # Check for dhi/Pydantic BaseModel
        try:
            if (
                BaseModel is not None
                and inspect.isclass(annotation)
                and issubclass(annotation, BaseModel)
            ):
                # Found a model parameter - use fast model path (sync only for now)
                model_info = {"param_name": param_name, "model_class": annotation}
                # For async handlers, model parsing needs the enhanced path
                # since Zig-side model parsing only supports sync handlers
                if is_async:
                    needs_body = True
                continue  # Don't add to param_types
        except TypeError:
            pass

        if annotation in (dict, list, bytes):
            needs_body = True

        origin = get_origin(annotation)
        if origin in (dict, list):
            needs_body = True

        if annotation is int:
            param_types[param_name] = "int"
        elif annotation is float:
            param_types[param_name] = "float"
        elif annotation is bool:
            param_types[param_name] = "bool"
        elif annotation is str or annotation is inspect.Parameter.empty:
            param_types[param_name] = "str"

    method = route.method.value.upper() if hasattr(route, "method") else "GET"

    # Model handlers use fast model path (simd-json + model_validate) - sync only
    if model_info and not is_async:
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            return "model_sync", param_types, model_info

    # Async handlers - async fast paths
    if is_async:
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            if needs_body:
                # Complex body types still need enhanced path
                return "enhanced", param_types, {}
            return "body_async", param_types, {}
        return "simple_async", param_types, {}

    # Sync handlers - Phase 3 sync fast paths
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        if needs_body:
            return "enhanced", param_types, {}
        return "body_sync", param_types, {}

    # Zero-arg GET: use the PyObject_CallNoArgs fast path in Zig
    if not param_types:
        return "simple_sync_noargs", param_types, {}
    return "simple_sync", param_types, {}


def _extract_model_schema(model_class) -> str | None:
    """Extract a JSON schema descriptor from a dhi BaseModel class for Zig-native validation.

    Supports nested models, unions (str | int), Optional, typed lists, and Field constraints.

    Returns a JSON string like:
        {"name":"UserModel","fields":[{"name":"address","type":"object","schema":{...}},..]}
    """
    try:
        schema = _build_schema(model_class)
        return json.dumps(schema) if schema else None
    except Exception:
        return None


def _build_schema(model_class) -> dict | None:
    """Recursively build a schema dict from a dhi BaseModel class."""

    hints = {}
    if hasattr(model_class, "__annotations__"):
        for name, ann in model_class.__annotations__.items():
            hints[name] = ann
    if not hints:
        return None

    fields = []
    model_fields = getattr(model_class, "model_fields", {}) if BaseModel is not None else {}
    for field_name, field_type in hints.items():
        field_info = _resolve_type(field_name, field_type)

        # Check if field has a default (not required)
        if field_name in model_fields:
            fi = model_fields[field_name]
            if hasattr(fi, "is_required") and not fi.is_required:
                field_info["required"] = False

            # Extract dhi Field constraints if available
            constraint = fi.default if hasattr(fi.default, "min_length") else fi
            for attr in ("min_length", "max_length", "gt", "ge", "lt", "le"):
                val = getattr(constraint, attr, None)
                if val is not None:
                    field_info[attr] = val

        fields.append(field_info)

    return {"name": model_class.__name__, "fields": fields}


def _resolve_type(field_name: str, field_type) -> dict:
    """Resolve a Python type annotation to a schema field descriptor."""
    import typing

    field_info: dict = {"name": field_name, "required": True}
    origin = get_origin(field_type)

    # Handle typing.Union / X | Y (includes Optional and Python 3.10+ union syntax)
    import types

    if origin is typing.Union or isinstance(field_type, types.UnionType):
        args = typing.get_args(field_type)
        non_none = [a for a in args if a is not type(None)]
        has_none = type(None) in args

        if has_none:
            field_info["required"] = False

        if len(non_none) == 1:
            # Optional[X] — recurse on the inner type
            inner = _resolve_type(field_name, non_none[0])
            inner["required"] = field_info["required"]
            return inner
        else:
            # True union: str | int — list the allowed types
            union_types = []
            for t in non_none:
                union_types.append(_python_type_to_str(t))
            field_info["type"] = "union"
            field_info["union_types"] = union_types
            return field_info

    # Handle list[X]
    if origin is list:
        field_info["type"] = "array"
        args = typing.get_args(field_type)
        if args:
            item_type = args[0]
            if _is_model_class(item_type):
                nested = _build_schema(item_type)
                if nested:
                    field_info["items_schema"] = nested
            else:
                field_info["items_type"] = _python_type_to_str(item_type)
        return field_info

    # Handle dict[K, V]
    if origin is dict:
        field_info["type"] = "object"
        return field_info

    # Handle nested BaseModel
    if _is_model_class(field_type):
        field_info["type"] = "object"
        nested = _build_schema(field_type)
        if nested:
            field_info["schema"] = nested
        return field_info

    # Simple scalar types
    field_info["type"] = _python_type_to_str(field_type)
    return field_info


def _python_type_to_str(t) -> str:
    if t is str:
        return "string"
    elif t is int:
        return "integer"
    elif t is float:
        return "float"
    elif t is bool:
        return "boolean"
    elif t is list or get_origin(t) is list:
        return "array"
    elif t is dict or get_origin(t) is dict:
        return "object"
    return "any"


def _is_model_class(t) -> bool:
    try:
        import inspect

        return BaseModel is not None and inspect.isclass(t) and issubclass(t, BaseModel)
    except TypeError:
        return False


try:
    from turboapi import turbonet

    NATIVE_CORE_AVAILABLE = True
except ImportError:
    NATIVE_CORE_AVAILABLE = False
    turbonet = None
    print("[WARN] Native core not available - running in simulation mode")


class ZigIntegratedTurboAPI(TurboAPI):
    """TurboAPI with direct Zig HTTP server integration - zero Python middleware overhead."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.zig_server = None
        self.route_handlers = {}  # Store Python handlers by route key
        self._middleware_instances = []
        print(f"{ROCKET} ZigIntegratedTurboAPI created - direct Zig integration")

        # Check environment variable to disable rate limiting for benchmarking
        import os

        if os.getenv("TURBO_DISABLE_RATE_LIMITING") == "1":
            self.configure_rate_limiting(enabled=False)
            print("[CONFIG] Rate limiting disabled via environment variable")

    # FastAPI-like decorators for better developer experience
    def get(self, path: str, **kwargs):
        """Decorator for GET routes - FastAPI-like syntax."""
        return super().get(path, **kwargs)

    def post(self, path: str, **kwargs):
        """Decorator for POST routes - FastAPI-like syntax."""
        return super().post(path, **kwargs)

    def put(self, path: str, **kwargs):
        """Decorator for PUT routes - FastAPI-like syntax."""
        return super().put(path, **kwargs)

    def delete(self, path: str, **kwargs):
        """Decorator for DELETE routes - FastAPI-like syntax."""
        return super().delete(path, **kwargs)

    def patch(self, path: str, **kwargs):
        """Decorator for PATCH routes - FastAPI-like syntax."""
        return super().patch(path, **kwargs)

    def native_route(self, method: str, path: str, lib_path: str, symbol_name: str):
        """Register a native FFI handler — bypasses Python entirely.

        The shared library must export a function matching the turboapi_ffi.h
        contract. The handler runs on the Zig request thread with no GIL.

        Args:
            method: HTTP method ("GET", "POST", etc.)
            path: URL path pattern (supports {param} syntax)
            lib_path: Path to the shared library (.so/.dylib)
            symbol_name: Exported symbol name of the handler function

        Usage:
            app.native_route("GET", "/health", "./libhandlers.dylib", "handle_health")
        """
        import os

        abs_path = os.path.abspath(lib_path)
        if not os.path.exists(abs_path):
            print(f"{CROSS_MARK} Native lib not found: {abs_path}")
            return
        self._native_routes = getattr(self, "_native_routes", [])
        self._native_routes.append((method.upper(), path, abs_path, symbol_name))
        print(
            f"{CHECK_MARK} [native] {method.upper()} {path} -> {os.path.basename(lib_path)}:{symbol_name}"
        )

    def static_route(
        self,
        method: str,
        path: str,
        body: str,
        *,
        status: int = 200,
        content_type: str = "application/json",
    ):
        """Register a static route — response is pre-rendered at startup.

        At request time this is a single writeAll of pre-computed bytes:
        no parsing, no allocation, no Python call.

        Args:
            method: HTTP method ("GET", "POST", etc.)
            path: URL path
            body: Response body string
            status: HTTP status code (default: 200)
            content_type: Content-Type header (default: "application/json")

        Usage:
            app.static_route("GET", "/health", '{"status":"ok"}')
            app.static_route("GET", "/version", '{"v":"1.0"}', status=200)
        """
        self._static_routes = getattr(self, "_static_routes", [])
        self._static_routes.append((method.upper(), path, status, content_type, body))
        print(f"{CHECK_MARK} [static] {method.upper()} {path} -> {status} ({len(body)} bytes)")

    def configure_rate_limiting(self, enabled: bool = False, requests_per_minute: int = 1000000):
        """Configure rate limiting for the server.

        Args:
            enabled: Whether to enable rate limiting (default: False for benchmarking)
            requests_per_minute: Maximum requests per minute per IP (default: 1,000,000)
        """
        if NATIVE_CORE_AVAILABLE:
            try:
                turbonet.configure_rate_limiting(enabled, requests_per_minute)
                status = "enabled" if enabled else "disabled"
                print(f"[CONFIG] Rate limiting {status} ({requests_per_minute:,} req/min)")
            except Exception as e:
                print(f"[WARN] Failed to configure rate limiting: {e}")
        else:
            print("[WARN] Rate limiting configuration requires native core")

    def _initialize_zig_server(self, host: str = "127.0.0.1", port: int = 8000):
        """Initialize the Zig HTTP server with direct integration."""
        if not NATIVE_CORE_AVAILABLE:
            print("[ERROR] Native Zig backend not available.")
            print("        Build it first: python zig/build_turbonet.py")
            print("        Requires: Python 3.14+ and Zig 0.15+")
            return False

        try:
            # Create Zig server
            self.zig_server = turbonet.TurboServer(host, port)

            # Add middleware directly to Zig server (zero Python overhead)
            for middleware_class, kwargs in self.middleware_stack:
                middleware_name = middleware_class.__name__

                if middleware_name == "CORSMiddleware":
                    # Use Zig-native CORS — pre-rendered headers, zero per-request overhead.
                    # Routes stay on the fast path (no downgrade to enhanced).
                    origins = kwargs.get("allow_origins", ["*"])
                    methods_list = kwargs.get("allow_methods", ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"])
                    hdrs_list = kwargs.get("allow_headers", ["*"])
                    max_age = kwargs.get("max_age", 600)
                    creds = kwargs.get("allow_credentials", False)
                    self.zig_server.configure_cors(
                        ", ".join(origins),
                        ", ".join(methods_list),
                        ", ".join(hdrs_list),
                        max_age,
                        int(creds),
                    )
                    # Mark this middleware as handled natively — don't add to Python pipeline
                    self._zig_cors_enabled = True
                    print(f"{CHECK_MARK} CORS handled by Zig (zero overhead)")
                    continue  # skip adding to Python middleware instances

                elif middleware_name == "CorsMiddleware":
                    # Legacy Zig bootstrap CorsMiddleware
                    cors_middleware = turbonet.CorsMiddleware(
                        kwargs.get("origins", ["*"]),
                        kwargs.get("methods", ["GET", "POST", "PUT", "DELETE"]),
                        kwargs.get("headers", ["*"]),
                        kwargs.get("max_age", 3600),
                    )
                    self.zig_server.add_middleware(cors_middleware)
                    print(f"{CHECK_MARK} Added CORS middleware to Zig server")

                elif middleware_name == "RateLimitMiddleware":
                    rate_limit = turbonet.RateLimitMiddleware(
                        kwargs.get("requests_per_minute", 1000)
                    )
                    self.zig_server.add_middleware(rate_limit)
                    print(f"{CHECK_MARK} Added Rate Limiting middleware to Zig server")

                # Add more middleware types as needed

            # Instantiate Python middleware objects for request pipeline
            # Skip CORSMiddleware if handled natively by Zig
            self._middleware_instances = []
            for middleware_class, kwargs in self.middleware_stack:
                if getattr(self, "_zig_cors_enabled", False) and middleware_class.__name__ == "CORSMiddleware":
                    continue  # handled in Zig
                self._middleware_instances.append(middleware_class(**kwargs))

            # Register all routes with Zig server
            self._register_routes_with_zig()

            # Register native FFI routes
            for method, path, lib_path, symbol in getattr(self, "_native_routes", []):
                self.zig_server.add_native_route(method, path, lib_path, symbol)

            # Register static routes (pre-rendered response bytes)
            for method, path, status, ct, body in getattr(self, "_static_routes", []):
                self.zig_server.add_static_route(method, path, status, ct, body)

            # Enable response caching for noargs handlers (auto-cache after first call)
            if hasattr(self.zig_server, "enable_response_cache"):
                self.zig_server.enable_response_cache()

            native_count = len(getattr(self, "_native_routes", []))
            static_count = len(getattr(self, "_static_routes", []))
            py_count = len(self.registry.get_routes())
            print(
                f"{CHECK_MARK} Zig server initialized with {py_count} Python"
                f" + {native_count} native + {static_count} static routes"
            )
            return True

        except Exception as e:
            print(f"{CROSS_MARK} Zig server initialization failed: {e}")
            return False

    def _wrap_with_middleware(self, enhanced_handler):
        """Wrap an enhanced handler with middleware before/after/on_error hooks."""
        middleware_instances = self._middleware_instances

        def middleware_wrapped_handler(**kwargs):
            request = Request(
                method=kwargs.get("method", ""),
                path=kwargs.get("path", ""),
                headers=kwargs.get("headers", {}),
                body=kwargs.get("body", b""),
                query_string=kwargs.get("query_string", ""),
                path_params=kwargs.get("path_params", {}),
            )

            # Run before_request
            for mw in middleware_instances:
                try:
                    mw.before_request(request)
                except Exception as e:
                    return {
                        "content": {"error": str(e)},
                        "status_code": 429,
                        "content_type": "application/json",
                    }

            # Call actual handler
            try:
                result = enhanced_handler(**kwargs)
            except Exception as e:
                for mw in reversed(middleware_instances):
                    err_resp = mw.on_error(request, e)
                    if err_resp:
                        return {
                            "content": {"error": str(e)},
                            "status_code": 500,
                            "content_type": "application/json",
                        }
                return {
                    "content": {"error": str(e)},
                    "status_code": 500,
                    "content_type": "application/json",
                }

            # Run after_request
            response = Response(
                content=result.get("content", ""),
                status_code=result.get("status_code", 200),
                headers={},
            )
            for mw in reversed(middleware_instances):
                response = mw.after_request(request, response)

            # Merge middleware-added headers back
            result["status_code"] = response.status_code
            if response.headers:
                result["extra_headers"] = response.headers

            return result

        return middleware_wrapped_handler

    def _register_routes_with_zig(self):
        """Register all Python routes with the Zig HTTP server.
        Phase 3: Uses handler classification for fast dispatch.
        """
        for route in self.registry.get_routes():
            try:
                route_key = f"{route.method.value}:{route.path}"
                self.route_handlers[route_key] = route.handler

                # Phase 3: Classify handler for fast dispatch
                handler_type, param_types, model_info = classify_handler(route.handler, route)

                if handler_type == "model_sync":
                    # FAST MODEL PATH: Zig validates JSON natively via dhi, then calls Python
                    if self._middleware_instances:
                        # Middleware present: register as "enhanced" so Zig uses callPythonHandler
                        # (dict response path). Pre-GIL dhi validation is skipped — middleware
                        # overhead already dominates, so the tradeoff is acceptable.
                        enhanced_handler = create_enhanced_handler(route.handler, route)
                        enhanced_handler = self._wrap_with_middleware(enhanced_handler)
                        self.zig_server.add_route_fast(
                            route.method.value,
                            route.path,
                            enhanced_handler,
                            "enhanced",
                            "{}",
                            route.handler,
                        )
                        print(f"{CHECK_MARK} [model_sync+middleware→enhanced] {route.method.value} {route.path}")
                    else:
                        # Minimal handler: json.loads → Model(**data) → handler(model) → json.dumps
                        enhanced_handler = create_fast_model_handler(
                            route.handler,
                            model_info["model_class"],
                            model_info["param_name"],
                        )

                        # Extract dhi model schema for Zig-native validation
                        schema_json = _extract_model_schema(model_info["model_class"])
                        if schema_json and hasattr(self.zig_server, "add_route_model_validated"):
                            self.zig_server.add_route_model_validated(
                                route.method.value,
                                route.path,
                                enhanced_handler,
                                model_info["param_name"],
                                model_info["model_class"],
                                route.handler,
                                schema_json,
                            )
                            print(f"{CHECK_MARK} [model_sync+dhi] {route.method.value} {route.path}")
                        else:
                            self.zig_server.add_route_model(
                                route.method.value,
                                route.path,
                                enhanced_handler,
                                model_info["param_name"],
                                model_info["model_class"],
                                route.handler,
                            )
                            print(f"{CHECK_MARK} [model_sync] {route.method.value} {route.path}")
                elif handler_type in ("simple_sync", "simple_sync_noargs", "body_sync"):
                    # SYNC FAST PATH: Use minimal-overhead fast handler (returns 3-tuple)
                    if self._middleware_instances:
                        # Middleware present: wrap with enhanced handler, register as "enhanced"
                        # so Zig dispatches through callPythonHandler (dict response path)
                        # instead of the fast tuple path which doesn't support middleware
                        enhanced_handler = create_enhanced_handler(route.handler, route)
                        enhanced_handler = self._wrap_with_middleware(enhanced_handler)
                        registered_type = "enhanced"
                    elif handler_type == "simple_sync":
                        # Vectorcall path: Zig assembles args, calls positionally
                        enhanced_handler = create_pos_handler(route.handler)
                        registered_type = handler_type
                    else:
                        enhanced_handler = create_fast_handler(route.handler, route)
                        registered_type = handler_type

                    # simple_sync: ordered "name:type[?]|..." string for Zig vectorcall arg assembly
                    # '?' suffix = has a Python default → Zig skips trailing missing optionals
                    # Other types: legacy JSON dict (unused in Zig dispatch, kept for compat)
                    if handler_type == "simple_sync" and not self._middleware_instances:
                        sig = inspect.signature(route.handler)
                        meta_parts = []
                        for n, t in param_types.items():
                            param = sig.parameters.get(n)
                            is_opt = (
                                param is not None and param.default is not inspect.Parameter.empty
                            )
                            meta_parts.append(f"{n}:{t}{'?' if is_opt else ''}")
                        param_meta_str = "|".join(meta_parts)
                    else:
                        param_meta_str = json.dumps(param_types)

                    self.zig_server.add_route_fast(
                        route.method.value,
                        route.path,
                        enhanced_handler,
                        registered_type,
                        param_meta_str,
                        route.handler,
                    )
                    print(f"{CHECK_MARK} [{registered_type}] {route.method.value} {route.path}")
                elif handler_type in ("simple_async", "body_async"):
                    # ASYNC FAST PATH: Register with async runtime
                    enhanced_handler = create_enhanced_handler(route.handler, route)
                    if self._middleware_instances:
                        enhanced_handler = self._wrap_with_middleware(enhanced_handler)
                    param_types_json = json.dumps(param_types)

                    self.zig_server.add_route_async_fast(
                        route.method.value,
                        route.path,
                        enhanced_handler,  # Fallback wrapper
                        handler_type,
                        param_types_json,
                        route.handler,  # Original async handler
                    )
                    print(f"{CHECK_MARK} [{handler_type}] {route.method.value} {route.path}")
                else:
                    # ENHANCED PATH: Full Python wrapper needed
                    enhanced_handler = create_enhanced_handler(route.handler, route)
                    if self._middleware_instances:
                        enhanced_handler = self._wrap_with_middleware(enhanced_handler)
                    self.zig_server.add_route(
                        route.method.value,
                        route.path,
                        enhanced_handler,
                    )
                    print(f"{CHECK_MARK} [enhanced] {route.method.value} {route.path}")

            except Exception as e:
                print(
                    f"{CROSS_MARK} Failed to register route {route.method.value} {route.path}: {e}"
                )

    def _extract_path_params(self, route_path: str, actual_path: str) -> dict[str, str]:
        """Extract path parameters from actual path using route pattern."""
        import re

        # Convert route path to regex
        pattern = route_path
        param_names = []

        # Find all path parameters
        param_matches = re.findall(r"\{([^}]+)\}", route_path)

        for param in param_matches:
            param_names.append(param)
            pattern = pattern.replace(f"{{{param}}}", "([^/]+)")

        # Match actual path
        match = re.match(f"^{pattern}$", actual_path)

        if match:
            return dict(zip(param_names, match.groups(), strict=False))

        return {}

    def _convert_to_response(self, result) -> Any:
        """Convert Python result to Zig ResponseView."""
        if not NATIVE_CORE_AVAILABLE:
            return result

        if isinstance(result, dict) and "status_code" in result:
            # Handle error responses
            response = turbonet.ResponseView(result["status_code"])
            if "error" in result:
                response.json(
                    json.dumps({"error": result["error"], "detail": result.get("detail", "")})
                )
            else:
                response.json(json.dumps(result.get("data", result)))
            return response
        elif isinstance(result, dict):
            # JSON response
            response = turbonet.ResponseView(200)
            response.json(json.dumps(result))
            return response
        elif isinstance(result, str):
            # Text response
            response = turbonet.ResponseView(200)
            response.text(result)
            return response
        else:
            # Default JSON response
            response = turbonet.ResponseView(200)
            response.json(json.dumps({"data": result}))
            return response

    def run(self, host: str = "127.0.0.1", port: int = 8000, **kwargs):
        """Run with direct Zig server integration."""
        print(f"\n{ROCKET} Starting TurboAPI with Direct Zig Integration...")
        print(f"   Host: {host}:{port}")
        print(f"   Title: {self.title} v{self.version}")

        # Initialize Zig server
        if not self._initialize_zig_server(host, port):
            print(f"{CROSS_MARK} Failed to initialize Zig server")
            print(f"   Use an ASGI server as fallback: uvicorn main:app --host {host} --port {port}")
            return

        # Print integration info
        print("\n[CONFIG] Direct Zig Integration:")
        print(f"   Zig HTTP Server: {CHECK_MARK} Active")
        print(f"   Middleware Pipeline: {CHECK_MARK} Zig-native (zero Python overhead)")
        print(
            f"   Route Handlers: {CHECK_MARK} {len(self.route_handlers)} Python functions registered"
        )
        print(f"   Performance: {CHECK_MARK} 5-10x FastAPI target (no Python middleware overhead)")

        # Print route information
        self.print_routes()

        print("\n[PERF] Zero-Overhead Architecture:")
        print("   HTTP Request → Zig Middleware → Python Handler → Zig Response")
        print("   No Python middleware overhead!")
        print("   Direct Zig-to-Python calls only for route handlers")

        # Run startup handlers
        if self.startup_handlers:
            import asyncio

            asyncio.run(self._run_startup_handlers())

        print(f"\n{CHECK_MARK} TurboAPI Direct Zig Integration ready!")
        print(f"   Visit: http://{host}:{port}")

        try:
            if NATIVE_CORE_AVAILABLE:
                # Start the actual Zig server
                print("\n[SERVER] Starting Zig HTTP server with zero overhead...")
                self.zig_server.run()
            else:
                print("\n[WARN] Native core not available - simulation mode")
                print("Press Ctrl+C to stop")
                import time

                while True:
                    time.sleep(1)

        except KeyboardInterrupt:
            print("\n[STOP] Shutting down TurboAPI server...")

            # Run shutdown handlers
            if self.shutdown_handlers:
                import asyncio

                asyncio.run(self._run_shutdown_handlers())

            print("[BYE] Server stopped")


# Export the correct integration class
TurboAPI = ZigIntegratedTurboAPI
