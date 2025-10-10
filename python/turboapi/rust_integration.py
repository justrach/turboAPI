"""
TurboAPI Direct Rust Integration
Connects FastAPI-compatible routing directly to Rust HTTP core with zero Python overhead
"""

import inspect
import json
from typing import Any

from .main_app import TurboAPI
from .request_handler import create_enhanced_handler, ResponseHandler
from .version_check import CHECK_MARK, CROSS_MARK, ROCKET

try:
    import turbonet
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
        """Register all Python routes with the Rust HTTP server."""
        for route in self.registry.get_routes():
            try:
                # Create route key
                route_key = f"{route.method.value}:{route.path}"

                # Store Python handler
                self.route_handlers[route_key] = route.handler

                # Create enhanced handler with automatic body parsing
                enhanced_handler = create_enhanced_handler(route.handler, route)
                
                # Create Rust-compatible handler wrapper
                def create_rust_handler(python_handler, route_def):
                    def rust_handler(rust_request):
                        """Rust-callable handler that calls Python function with automatic body parsing."""
                        try:
                            # Extract request data from Rust
                            path = rust_request.path
                            query_string = rust_request.query_string
                            
                            # Get headers - try method call first, then attribute
                            try:
                                headers = rust_request.get_headers() if callable(getattr(rust_request, 'get_headers', None)) else {}
                            except:
                                headers = getattr(rust_request, 'headers', {})
                            
                            # Get body - Rust sets it as 'body' attribute (bytes)
                            body = getattr(rust_request, 'body', b'')
                            
                            # Also try get_body if it's set
                            if not body:
                                get_body_attr = getattr(rust_request, 'get_body', None)
                                if get_body_attr is not None:
                                    if callable(get_body_attr):
                                        body = get_body_attr()
                                    else:
                                        body = get_body_attr

                            # Parse query parameters
                            query_params = {}
                            if query_string:
                                # Simple query string parsing
                                for param in query_string.split('&'):
                                    if '=' in param:
                                        key, value = param.split('=', 1)
                                        query_params[key] = value

                            # Parse path parameters
                            path_params = self._extract_path_params(route_def.path, path)

                            # Prepare arguments for enhanced handler
                            call_args = {}
                            
                            # Add path parameters
                            call_args.update(path_params)
                            
                            # Add query parameters
                            call_args.update(query_params)
                            
                            # Always add body and headers for enhanced handler
                            call_args['body'] = body if body else b''
                            call_args['headers'] = headers

                            # Call enhanced handler (handles parsing, validation, response normalization)
                            result = python_handler(**call_args)
                            
                            # Enhanced handler returns normalized format
                            # {"content": ..., "status_code": ..., "content_type": ...}
                            # But Rust expects a plain dict that it will JSON serialize
                            # So just return the content directly
                            if isinstance(result, dict) and 'content' in result and 'status_code' in result:
                                # Return just the content - Rust will handle status codes later
                                # For now, just return the content as a dict
                                return result['content']
                            
                            # Fallback for plain dict responses
                            return result

                        except Exception as e:
                            # Return 500 error as plain dict (Rust will serialize it)
                            import traceback
                            return {
                                "error": "Internal Server Error",
                                "detail": str(e),
                                "traceback": traceback.format_exc()
                            }

                    return rust_handler  # noqa: B023

                # Register the ORIGINAL handler directly with Rust
                # Rust will call it with call0() (no arguments)
                # The original handler doesn't expect any arguments
                self.rust_server.add_route(
                    route.method.value,
                    route.path,
                    route.handler  # Pass original handler, not wrapper!
                )

                print(f"{CHECK_MARK} Registered {route.method.value} {route.path} with Rust server")

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
