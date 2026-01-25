"""
TurboAPI Direct Rust Integration
Connects FastAPI-compatible routing directly to Rust HTTP core with zero Python overhead.
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
from .request_handler import create_enhanced_handler, ResponseHandler
from .version_check import CHECK_MARK, CROSS_MARK, ROCKET


def classify_handler(handler, route) -> tuple[str, dict[str, str], dict]:
    """Classify a handler for fast dispatch (Phase 3).

    Returns:
        (handler_type, param_types, model_info) where:
        - handler_type: "simple_sync" | "body_sync" | "model_sync" | "enhanced"
        - param_types: dict mapping param_name -> type hint string
        - model_info: dict with "param_name" and "model_class" for model handlers
    """
    if inspect.iscoroutinefunction(handler):
        return "enhanced", {}, {}

    sig = inspect.signature(handler)
    param_types = {}
    needs_body = False
    model_info = {}

    for param_name, param in sig.parameters.items():
        annotation = param.annotation

        # Check for dhi/Pydantic BaseModel
        try:
            if BaseModel is not None and inspect.isclass(annotation) and issubclass(annotation, BaseModel):
                # Found a model parameter - use fast model path
                model_info = {"param_name": param_name, "model_class": annotation}
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

    # Model handlers use fast model path (simd-json + model_validate)
    if model_info:
        method = route.method.value.upper() if hasattr(route, "method") else "GET"
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            return "model_sync", param_types, model_info

    method = route.method.value.upper() if hasattr(route, "method") else "GET"
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        if needs_body:
            return "enhanced", param_types, {}
        return "body_sync", param_types, {}

    return "simple_sync", param_types, {}

try:
    from turboapi import turbonet
    RUST_CORE_AVAILABLE = True
except ImportError:
    RUST_CORE_AVAILABLE = False
    turbonet = None
    print("[WARN] Rust core not available - running in simulation mode")

class RustIntegratedTurboAPI(TurboAPI):
    """TurboAPI with direct Rust HTTP server integration - zero Python middleware overhead."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rust_server = None
        self.route_handlers = {}  # Store Python handlers by route key
        print(f"{ROCKET} RustIntegratedTurboAPI created - direct Rust integration")

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

    def configure_rate_limiting(self, enabled: bool = False, requests_per_minute: int = 1000000):
        """Configure rate limiting for the server.

        Args:
            enabled: Whether to enable rate limiting (default: False for benchmarking)
            requests_per_minute: Maximum requests per minute per IP (default: 1,000,000)
        """
        if RUST_CORE_AVAILABLE:
            try:
                turbonet.configure_rate_limiting(enabled, requests_per_minute)
                status = "enabled" if enabled else "disabled"
                print(f"[CONFIG] Rate limiting {status} ({requests_per_minute:,} req/min)")
            except Exception as e:
                print(f"[WARN] Failed to configure rate limiting: {e}")
        else:
            print("[WARN] Rate limiting configuration requires Rust core")

    def _initialize_rust_server(self, host: str = "127.0.0.1", port: int = 8000):
        """Initialize the Rust HTTP server with direct integration."""
        if not RUST_CORE_AVAILABLE:
            print("[WARN] Rust core not available - cannot initialize server")
            return False

        try:
            # Create Rust server
            self.rust_server = turbonet.TurboServer(host, port)

            # Add middleware directly to Rust server (zero Python overhead)
            for middleware_class, kwargs in self.middleware_stack:
                middleware_name = middleware_class.__name__

                if middleware_name == "CorsMiddleware":
                    cors_middleware = turbonet.CorsMiddleware(
                        kwargs.get("origins", ["*"]),
                        kwargs.get("methods", ["GET", "POST", "PUT", "DELETE"]),
                        kwargs.get("headers", ["*"]),
                        kwargs.get("max_age", 3600)
                    )
                    self.rust_server.add_middleware(cors_middleware)
                    print(f"{CHECK_MARK} Added CORS middleware to Rust server")

                elif middleware_name == "RateLimitMiddleware":
                    rate_limit = turbonet.RateLimitMiddleware(
                        kwargs.get("requests_per_minute", 1000)
                    )
                    self.rust_server.add_middleware(rate_limit)
                    print(f"{CHECK_MARK} Added Rate Limiting middleware to Rust server")

                # Add more middleware types as needed

            # Register all routes with Rust server
            self._register_routes_with_rust()

            print(f"{CHECK_MARK} Rust server initialized with {len(self.registry.get_routes())} routes")
            return True

        except Exception as e:
            print(f"{CROSS_MARK} Rust server initialization failed: {e}")
            return False

    def _register_routes_with_rust(self):
        """Register all Python routes with the Rust HTTP server.
        Phase 3: Uses handler classification for fast dispatch.
        """
        for route in self.registry.get_routes():
            try:
                route_key = f"{route.method.value}:{route.path}"
                self.route_handlers[route_key] = route.handler

                # Phase 3: Classify handler for fast dispatch
                handler_type, param_types, model_info = classify_handler(route.handler, route)

                if handler_type == "model_sync":
                    # FAST MODEL PATH: Rust parses JSON with simd-json, validates model
                    enhanced_handler = create_enhanced_handler(route.handler, route)
                    self.rust_server.add_route_model(
                        route.method.value,
                        route.path,
                        enhanced_handler,  # Fallback wrapper
                        model_info["param_name"],
                        model_info["model_class"],
                        route.handler,  # Original unwrapped handler
                    )
                    print(f"{CHECK_MARK} [model_sync] {route.method.value} {route.path}")
                elif handler_type in ("simple_sync", "body_sync"):
                    # FAST PATH: Register with metadata for Rust-side parsing
                    # Enhanced handler is fallback, original handler is for direct call
                    enhanced_handler = create_enhanced_handler(route.handler, route)
                    param_types_json = json.dumps(param_types)

                    self.rust_server.add_route_fast(
                        route.method.value,
                        route.path,
                        enhanced_handler,  # Fallback wrapper
                        handler_type,
                        param_types_json,
                        route.handler,  # Original unwrapped handler
                    )
                    print(f"{CHECK_MARK} [{handler_type}] {route.method.value} {route.path}")
                else:
                    # ENHANCED PATH: Full Python wrapper needed
                    enhanced_handler = create_enhanced_handler(route.handler, route)
                    self.rust_server.add_route(
                        route.method.value,
                        route.path,
                        enhanced_handler,
                    )
                    print(f"{CHECK_MARK} [enhanced] {route.method.value} {route.path}")

            except Exception as e:
                print(f"{CROSS_MARK} Failed to register route {route.method.value} {route.path}: {e}")

    def _extract_path_params(self, route_path: str, actual_path: str) -> dict[str, str]:
        """Extract path parameters from actual path using route pattern."""
        import re

        # Convert route path to regex
        pattern = route_path
        param_names = []

        # Find all path parameters
        param_matches = re.findall(r'\{([^}]+)\}', route_path)

        for param in param_matches:
            param_names.append(param)
            pattern = pattern.replace(f'{{{param}}}', '([^/]+)')

        # Match actual path
        match = re.match(f'^{pattern}$', actual_path)

        if match:
            return dict(zip(param_names, match.groups(), strict=False))

        return {}

    def _convert_to_rust_response(self, result) -> Any:
        """Convert Python result to Rust ResponseView."""
        if not RUST_CORE_AVAILABLE:
            return result

        if isinstance(result, dict) and "status_code" in result:
            # Handle error responses
            response = turbonet.ResponseView(result["status_code"])
            if "error" in result:
                response.json(json.dumps({
                    "error": result["error"],
                    "detail": result.get("detail", "")
                }))
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
        """Run with direct Rust server integration."""
        print(f"\n{ROCKET} Starting TurboAPI with Direct Rust Integration...")
        print(f"   Host: {host}:{port}")
        print(f"   Title: {self.title} v{self.version}")

        # Initialize Rust server
        if not self._initialize_rust_server(host, port):
            print(f"{CROSS_MARK} Failed to initialize Rust server")
            return

        # Print integration info
        print("\n[CONFIG] Direct Rust Integration:")
        print(f"   Rust HTTP Server: {CHECK_MARK} Active")
        print(f"   Middleware Pipeline: {CHECK_MARK} Rust-native (zero Python overhead)")
        print(f"   Route Handlers: {CHECK_MARK} {len(self.route_handlers)} Python functions registered")
        print(f"   Performance: {CHECK_MARK} 5-10x FastAPI target (no Python middleware overhead)")

        # Print route information
        self.print_routes()

        print("\n[PERF] Zero-Overhead Architecture:")
        print("   HTTP Request → Rust Middleware → Python Handler → Rust Response")
        print("   No Python middleware overhead!")
        print("   Direct Rust-to-Python calls only for route handlers")

        # Run startup handlers
        if self.startup_handlers:
            import asyncio
            asyncio.run(self._run_startup_handlers())

        print(f"\n{CHECK_MARK} TurboAPI Direct Rust Integration ready!")
        print(f"   Visit: http://{host}:{port}")

        try:
            if RUST_CORE_AVAILABLE:
                # Start the actual Rust server
                print("\n[SERVER] Starting Rust HTTP server with zero Python overhead...")
                self.rust_server.run()
            else:
                print("\n[WARN] Rust core not available - simulation mode")
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
TurboAPI = RustIntegratedTurboAPI
