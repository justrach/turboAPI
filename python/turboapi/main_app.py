"""
TurboAPI Application Class
FastAPI-compatible application with revolutionary performance
"""

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

from .routing import Router
from .version_check import CHECK_MARK, ROCKET


def _parse_multipart(body: bytes, boundary: str) -> tuple[dict, list]:
    """Parse multipart/form-data body into (form_fields, file_fields)."""
    form_fields: dict[str, str] = {}
    file_fields: list[dict] = []
    delim = ("--" + boundary).encode()
    for part in body.split(delim)[1:]:
        if part in (b"--", b"--\r\n", b"\r\n--") or part.startswith(b"--"):
            break
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if b"\r\n\r\n" not in part:
            continue
        hdr_bytes, content = part.split(b"\r\n\r\n", 1)
        hdrs: dict[str, str] = {}
        for line in hdr_bytes.split(b"\r\n"):
            if b":" in line:
                k, v = line.split(b":", 1)
                hdrs[k.decode().lower().strip()] = v.decode().strip()
        cd = hdrs.get("content-disposition", "")
        name: str | None = None
        filename: str | None = None
        for seg in cd.split(";"):
            seg = seg.strip()
            if seg.startswith("name="):
                name = seg[5:].strip('"')
            elif seg.startswith("filename="):
                filename = seg[9:].strip('"')
        if name is None:
            continue
        if filename is not None:
            file_fields.append(
                {
                    "name": name,
                    "filename": filename,
                    "content_type": hdrs.get("content-type", "application/octet-stream"),
                    "body": content,
                }
            )
        else:
            form_fields[name] = content.decode("utf-8", errors="replace")
    return form_fields, file_fields


class TurboAPI(Router):
    """Main TurboAPI application class with FastAPI-compatible API."""

    def __init__(
        self,
        title: str = "TurboAPI",
        version: str = "0.1.0",
        description: str = "A revolutionary Python web framework",
        docs_url: str | None = "/docs",
        redoc_url: str | None = "/redoc",
        openapi_url: str | None = "/openapi.json",
        lifespan: Callable | None = None,
        **kwargs,
    ):
        super().__init__()
        self.title = title
        self.version = version
        self.description = description
        self.middleware_stack = []
        self.startup_handlers = []
        self.shutdown_handlers = []
        self.docs_url = docs_url
        self.redoc_url = redoc_url
        self.openapi_url = openapi_url
        self._lifespan = lifespan
        self._mounts: dict[str, Any] = {}
        self._websocket_routes: dict[str, Callable] = {}
        self._exception_handlers: dict[type, Callable] = {}
        self._openapi_schema: dict | None = None

        print(f"{ROCKET} TurboAPI application created: {title} v{version}")

    @property
    def routes(self):
        """Get all registered routes."""
        return self.registry.get_routes() if hasattr(self, "registry") else []

    def add_middleware(self, middleware_class, **kwargs):
        """Add middleware to the application."""
        self.middleware_stack.append((middleware_class, kwargs))
        print(f"[CONFIG] Added middleware: {middleware_class.__name__}")

    def on_event(self, event_type: str):
        """Register event handlers (startup/shutdown)."""

        def decorator(func: Callable):
            if event_type == "startup":
                self.startup_handlers.append(func)
                print(f"[EVENT] Registered startup handler: {func.__name__}")
            elif event_type == "shutdown":
                self.shutdown_handlers.append(func)
                print(f"[EVENT] Registered shutdown handler: {func.__name__}")
            return func

        return decorator

    def include_router(
        self,
        router: Router,
        prefix: str = "",
        tags: list[str] = None,
        dependencies: list[Any] = None,
    ):
        """Include a router with all its routes."""
        super().include_router(router, prefix, tags)
        print(f"[ROUTER] Included router with prefix: {prefix}")

    def mount(self, path: str, app: Any, name: str | None = None) -> None:
        """Mount a sub-application or static files at a path.

        Usage:
            app.mount("/static", StaticFiles(directory="static"), name="static")

        For ``StaticFiles`` mounts we register real HTTP routes so the Zig
        server serves the files directly (middleware, compression, etc. all
        work the way they do for any other route). Multi-segment paths are
        covered by registering a handful of ``{p1}/{p2}/...`` patterns.
        """
        path = path.rstrip("/")
        self._mounts[path] = {"app": app, "name": name}

        if hasattr(app, "get_file"):
            self._register_static_mount(path, app)

        print(f"[MOUNT] Mounted {name or 'app'} at {path}")

    _MAX_STATIC_DEPTH = 8

    def _register_static_mount(self, mount_path: str, static_app: Any) -> None:
        """Register catch-all routes that delegate to a StaticFiles instance.

        We register ``mount_path/{p1}``, ``mount_path/{p1}/{p2}``, … up to
        ``_MAX_STATIC_DEPTH`` segments. Each handler rebuilds the sub-path
        and calls ``static_app.get_file(sub)``.
        """
        from .responses import Response as _Response

        for depth in range(1, self._MAX_STATIC_DEPTH + 1):
            segments = "/".join(f"{{p{i}}}" for i in range(1, depth + 1))
            route_path = f"{mount_path}/{segments}"
            param_names = tuple(f"p{i}" for i in range(1, depth + 1))

            def _make_handler(app_ref=static_app, names=param_names):
                def _static_handler(**kwargs):
                    sub_path = "/".join(kwargs[n] for n in names if kwargs.get(n))
                    result = app_ref.get_file(sub_path)
                    if result is None:
                        return _Response(
                            content=b"Not Found",
                            status_code=404,
                            media_type="text/plain",
                        )
                    content, content_type, size = result
                    return _Response(
                        content=content,
                        status_code=200,
                        media_type=content_type,
                        headers={"Content-Length": str(size)},
                    )

                # Build an explicit signature so the router recognises each
                # path parameter as a string-typed placeholder.
                params = [
                    inspect.Parameter(n, inspect.Parameter.KEYWORD_ONLY, annotation=str)
                    for n in names
                ]
                _static_handler.__signature__ = inspect.Signature(parameters=params)
                _static_handler.__name__ = (
                    f"_static_mount_{mount_path.strip('/').replace('/', '_')}_{len(names)}"
                )
                return _static_handler

            self.get(route_path)(_make_handler())

    def websocket(self, path: str):
        """Register a WebSocket endpoint.

        Usage:
            @app.websocket("/ws")
            async def websocket_endpoint(websocket: WebSocket):
                await websocket.accept()
                data = await websocket.receive_text()
                await websocket.send_text(f"Echo: {data}")
        """
        def decorator(func: Callable):
            self._websocket_routes[path] = func
            # Register with the Zig server if it's running. The decorator may
            # be invoked at module-import time (before app.run()) — in that
            # case we keep _websocket_routes around and register lazily on
            # run(). If a turbonet server instance already exists, register
            # immediately so the route is live without an app.run() round-trip
            # (useful in tests).
            try:
                import importlib.util

                if importlib.util.find_spec("turboapi.turbonet") is not None:
                    srv = getattr(self, "_turbonet_server", None)
                    if srv is not None and hasattr(srv, "add_websocket_route"):
                        srv.add_websocket_route(path, func)
            except ImportError:
                pass
            return func

        return decorator

    def exception_handler(self, exc_class: type):
        """Register a custom exception handler.

        Usage:
            @app.exception_handler(ValueError)
            async def value_error_handler(request, exc):
                return JSONResponse(status_code=400, content={"detail": str(exc)})
        """

        def decorator(func: Callable):
            self._exception_handlers[exc_class] = func
            return func

        return decorator

    def openapi(self) -> dict:
        """Get the OpenAPI schema for this application."""
        if self._openapi_schema is None:
            from .openapi import generate_openapi_schema

            self._openapi_schema = generate_openapi_schema(self)
        return self._openapi_schema

    async def _run_startup_handlers(self):
        """Run all startup event handlers."""
        print("[START] Running startup handlers...")
        for handler in self.startup_handlers:
            if asyncio.iscoroutinefunction(handler):
                await handler()
            else:
                handler()

    async def _run_shutdown_handlers(self):
        """Run all shutdown event handlers."""
        print("[STOP] Running shutdown handlers...")
        for handler in self.shutdown_handlers:
            if asyncio.iscoroutinefunction(handler):
                await handler()
            else:
                handler()

    def get_route_info(self) -> dict[str, Any]:
        """Get information about all registered routes."""
        routes_info = []

        for route in self.registry.get_routes():
            route_info = {
                "path": route.path,
                "method": route.method.value,
                "handler": route.handler.__name__,
                "path_params": [
                    {"name": p.name, "type": p.type.__name__, "required": p.required}
                    for p in route.path_params
                ],
                "query_params": {
                    name: type_.__name__ for name, type_ in route.query_params.items()
                },
                "tags": route.tags,
                "summary": route.summary,
            }
            routes_info.append(route_info)

        return {
            "title": self.title,
            "version": self.version,
            "description": self.description,
            "routes": routes_info,
            "middleware": [m[0].__name__ for m in self.middleware_stack],
        }

    def print_routes(self):
        """Print all registered routes in a nice format."""
        print(f"\n[ROUTES] {self.title} - Registered Routes:")
        print("=" * 50)

        routes_by_method = {}
        for route in self.registry.get_routes():
            method = route.method.value
            if method not in routes_by_method:
                routes_by_method[method] = []
            routes_by_method[method].append(route)

        for method in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]:
            if method in routes_by_method:
                print(f"\n{method} Routes:")
                for route in routes_by_method[method]:
                    params = ", ".join([p.name for p in route.path_params])
                    param_str = f" ({params})" if params else ""
                    print(f"  {route.path}{param_str} -> {route.handler.__name__}")

        print(f"\nTotal routes: {len(self.registry.get_routes())}")
        print(f"Middleware: {len(self.middleware_stack)} components")

    async def handle_request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        """Handle an incoming request (for testing/simulation)."""
        # Find matching route
        match_result = self.registry.match_route(method, path)

        if not match_result:
            return {
                "error": "Not Found",
                "status_code": 404,
                "detail": f"Route {method} {path} not found",
            }

        route, path_params = match_result

        try:
            # Prepare function arguments
            sig = inspect.signature(route.handler)
            call_args = {}

            # Add path parameters
            for param_name, param_value in path_params.items():
                if param_name in sig.parameters:
                    # Convert to correct type
                    param_def = next((p for p in route.path_params if p.name == param_name), None)
                    if param_def and param_def.type is not str:
                        try:
                            param_value = param_def.type(param_value)
                        except (ValueError, TypeError):
                            return {
                                "error": "Bad Request",
                                "status_code": 400,
                                "detail": f"Invalid {param_name}: {param_value}",
                            }
                    call_args[param_name] = param_value

            # Add query parameters and request body
            for param_name, _param in sig.parameters.items():
                if param_name not in call_args and param_name in kwargs:
                    call_args[param_name] = kwargs[param_name]

            # Call the handler
            if asyncio.iscoroutinefunction(route.handler):
                result = await route.handler(**call_args)
            else:
                result = route.handler(**call_args)

            return {
                "data": result,
                "status_code": 200,
                "route": route.path,
                "handler": route.handler.__name__,
            }

        except Exception as e:
            return {"error": "Internal Server Error", "status_code": 500, "detail": str(e)}

    def run_legacy(self, host: str = "127.0.0.1", port: int = 8000, workers: int = 1, **kwargs):
        """Run the TurboAPI application with legacy loop sharding (DEPRECATED).

        Use run() instead for better performance with Zig HTTP core.
        """
        print("\n⚠️  WARNING: Using legacy loop sharding runtime")
        print("   For 12x better performance, use app.run() (default)")
        print(f"\n{ROCKET} Starting TurboAPI server...")
        print(f"   Host: {host}:{port}")
        print(f"   Workers: {workers}")
        print(f"   Title: {self.title} v{self.version}")

        # Print route information
        self.print_routes()

        print("\n[CONFIG] Middleware Stack:")
        for middleware_class, _middleware_kwargs in self.middleware_stack:
            print(f"   - {middleware_class.__name__}")

        print("\n[PERF] Performance Features:")
        print("   - 7.5x FastAPI middleware performance")
        print("   - Python 3.13 free-threading support")
        print("   - Zero-copy optimizations")
        print("   - Zig-powered HTTP core")

        # Run startup handlers
        if self.startup_handlers:
            asyncio.run(self._run_startup_handlers())

        print(f"\n{CHECK_MARK} TurboAPI server ready!")
        print(f"   Visit: http://{host}:{port}")
        print(f"   Docs: http://{host}:{port}/docs (coming soon)")

        try:
            # This would start the actual HTTP server
            # For now, we'll simulate it
            print("\n[SERVER] Server running (Phase 6 integration in progress)")
            print("Press Ctrl+C to stop")

            # Simulate server running
            import time

            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n[STOP] Shutting down TurboAPI server...")

            # Run shutdown handlers
            if self.shutdown_handlers:
                asyncio.run(self._run_shutdown_handlers())

            print("[BYE] Server stopped")

    def run(self, host: str = "127.0.0.1", port: int = 8000, **kwargs):
        """Run the TurboAPI application with Zig HTTP core.

        Performance: 24K+ RPS (12x faster than baseline!)
        Uses Zig thread pool with Python 3.14 free-threading.
        """
        print("\n🚀 Starting TurboAPI with Zig HTTP core!")
        print(f"   Host: {host}:{port}")
        print(f"   Title: {self.title} v{self.version}")
        print("   ⚡ Performance: 24K+ RPS (12x improvement!)")

        # Print route information
        self.print_routes()

        print("\n[PERF] Phase D Features:")
        print("   ✨ Zig 8-thread worker pool")
        print("   ✨ Python 3.14 free-threading (no GIL)")
        print("   ✨ Zero-copy response path")
        print("   ✨ 7,168 concurrent task capacity")
        print("   ✨ Zig-powered HTTP execution")

        # Run startup handlers
        if self.startup_handlers:
            asyncio.run(self._run_startup_handlers())

        print(f"\n{CHECK_MARK} TurboAPI server ready with Zig runtime!")
        print(f"   Visit: http://{host}:{port}")

        try:
            # Import and use the Zig server
            import turbonet

            server = turbonet.TurboServer(host, port)
            self._turbonet_server = server

            # Register all routes
            for route in self.registry.get_routes():
                server.add_route(route.method.value, route.path, route.handler)

            # Register WebSocket routes registered via @app.websocket(...)
            for ws_path, ws_handler in self._websocket_routes.items():
                if hasattr(server, "add_websocket_route"):
                    server.add_websocket_route(ws_path, ws_handler)

            print("\n[SERVER] Starting Zig server...")
            server.run()

        except KeyboardInterrupt:
            print("\n[STOP] Shutting down TurboAPI server...")

            # Run shutdown handlers
            if self.shutdown_handlers:
                asyncio.run(self._run_shutdown_handlers())

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """ASGI fallback — pure Python, ~100x slower than the Zig native backend.

        Use app.run() with the compiled Zig backend for production performance.
        This exists so the app is usable via uvicorn/granian before turbonet is built.
        """
        import json as _json
        from http.cookies import SimpleCookie
        from urllib.parse import parse_qs

        from .datastructures import Cookie as _Cookie
        from .datastructures import File as _File
        from .datastructures import Form as _Form
        from .datastructures import Header as _Header
        from .datastructures import Query as _Query
        from .datastructures import UploadFile as _UF
        from .exceptions import HTTPException as _HTTPException
        from .responses import JSONResponse as _JSONResponse
        from .responses import Response as _Response
        from .responses import StreamingResponse as _StreamingResponse
        from .security import get_depends as _get_depends

        async def _send_response(response: _Response) -> None:
            headers_out: list[list[bytes]] = []
            if getattr(response, "media_type", None):
                headers_out.append([b"content-type", str(response.media_type).encode("latin-1")])
            headers_out.append([b"server", b"TurboAPI"])
            for key, value in getattr(response, "headers", {}).items():
                if isinstance(value, list):
                    for item in value:
                        headers_out.append([str(key).encode("latin-1"), str(item).encode("latin-1")])
                else:
                    headers_out.append([str(key).encode("latin-1"), str(value).encode("latin-1")])

            await send(
                {
                    "type": "http.response.start",
                    "status": getattr(response, "status_code", 200),
                    "headers": headers_out,
                }
            )
            if isinstance(response, _StreamingResponse):
                async for chunk in response.body_iterator():
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            else:
                await send({"type": "http.response.body", "body": getattr(response, "body", b"")})

        async def _send_json(status: int, payload: Any, headers: dict[str, str] | None = None) -> None:
            await _send_response(_JSONResponse(payload, status_code=status, headers=headers))

        def _annotation(param: inspect.Parameter):
            ann = param.annotation
            metadata = getattr(ann, "__metadata__", None)
            if metadata is not None and hasattr(ann, "__origin__"):
                return ann.__origin__
            return ann

        def _coerce(value, ann):
            if ann is inspect.Parameter.empty or value is None:
                return value
            if getattr(ann, "__origin__", None) is not None and type(None) in getattr(ann, "__args__", ()):
                non_none = [a for a in ann.__args__ if a is not type(None)]
                ann = non_none[0] if non_none else ann
            try:
                if ann is bool:
                    if isinstance(value, str):
                        return value.lower() in {"1", "true", "yes", "on"}
                    return bool(value)
                if ann in (str, int, float):
                    return ann(value)
            except Exception:
                return value
            return value

        def _is_body_marker(default) -> bool:
            from .datastructures import Body as _Body
            return isinstance(default, (_Form, _File, _Body))

        def _cookie_map(cookie_header: str) -> dict[str, str]:
            parsed = SimpleCookie()
            parsed.load(cookie_header or "")
            return {key: morsel.value for key, morsel in parsed.items()}

        async def _call_maybe_async(func, **kwargs):
            result = func(**kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

        async def _resolve_dependency(dep, context: dict[str, Any]):
            dependency = dep.dependency
            if dependency is None:
                return None
            dep_sig = inspect.signature(dependency)
            dep_args: dict[str, Any] = {}
            for name, param in dep_sig.parameters.items():
                depends = _get_depends(param)
                if depends is not None:
                    dep_args[name] = await _resolve_dependency(depends, context)
                    continue
                default = param.default
                ann = _annotation(param)
                if isinstance(default, _Header):
                    key = default.alias or (name.replace("_", "-") if default.convert_underscores else name)
                    val = context["headers"].get(key.lower())
                    if val is None and default.default is not ...:
                        val = default.default
                    if val is not None:
                        dep_args[name] = _coerce(val, ann)
                elif isinstance(default, _Cookie):
                    key = default.alias or name
                    val = context["cookies"].get(key)
                    if val is None and default.default is not ...:
                        val = default.default
                    if val is not None:
                        dep_args[name] = _coerce(val, ann)
                elif name in context["query"]:
                    dep_args[name] = _coerce(context["query"][name][0], ann)
                elif name in context["headers"]:
                    dep_args[name] = _coerce(context["headers"][name], ann)
                elif param.default is not inspect.Parameter.empty:
                    dep_args[name] = param.default
            return await _call_maybe_async(dependency, **dep_args)

        async def _send_result(result: Any) -> None:
            if isinstance(result, _Response):
                await _send_response(result)
                return
            if hasattr(result, "model_dump"):
                result = result.model_dump()
            elif hasattr(result, "dict"):
                result = result.dict()
            if isinstance(result, dict):
                await _send_response(_JSONResponse(result))
            elif isinstance(result, str):
                await _send_response(_Response(result, media_type="text/plain"))
            elif isinstance(result, bytes):
                await _send_response(_Response(result, media_type="application/octet-stream"))
            else:
                await _send_response(_JSONResponse(result))

        if scope["type"] == "lifespan":
            lifespan_cm = None
            if self._lifespan is not None:
                lifespan_cm = self._lifespan(self)
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    if lifespan_cm is not None:
                        if inspect.isasyncgen(lifespan_cm):
                            await lifespan_cm.__anext__()
                        else:
                            await lifespan_cm.__aenter__()
                    if self.startup_handlers:
                        await self._run_startup_handlers()
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    if lifespan_cm is not None:
                        try:
                            if inspect.isasyncgen(lifespan_cm):
                                await lifespan_cm.__anext__()
                            else:
                                await lifespan_cm.__aexit__(None, None, None)
                        except StopAsyncIteration:
                            pass
                    if self.shutdown_handlers:
                        await self._run_shutdown_handlers()
                    await send({"type": "lifespan.shutdown.complete"})
                    return

        if scope["type"] != "http":
            return

        method = scope["method"]
        path = scope["path"]
        query_string = scope.get("query_string", b"").decode("utf-8", errors="replace")

        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break

        headers = {}
        for hdr_name, hdr_val in scope.get("headers", []):
            headers[hdr_name.decode("latin-1").lower()] = hdr_val.decode("latin-1")
        cookies = _cookie_map(headers.get("cookie", ""))
        qs = parse_qs(query_string, keep_blank_values=True)
        context = {"headers": headers, "cookies": cookies, "query": qs}

        if method == "GET" and self.openapi_url and path == self.openapi_url:
            await _send_response(_JSONResponse(self.openapi()))
            return
        if method == "GET" and self.docs_url and path == self.docs_url:
            from .openapi import get_swagger_ui_html
            await _send_response(_Response(get_swagger_ui_html(self.title, self.openapi_url or "/openapi.json"), media_type="text/html"))
            return
        if method == "GET" and self.redoc_url and path == self.redoc_url:
            from .openapi import get_redoc_html
            await _send_response(_Response(get_redoc_html(self.title, self.openapi_url or "/openapi.json"), media_type="text/html"))
            return

        match_result = self.registry.match_route(method, path)
        if not match_result:
            await _send_json(404, {"detail": "Not Found"})
            return

        route, path_params = match_result
        sig = inspect.signature(route.handler)
        call_args: dict[str, Any] = {}

        for param_name, param_value in path_params.items():
            if param_name in sig.parameters:
                param_def = next((p for p in route.path_params if p.name == param_name), None)
                ann = param_def.type if param_def else _annotation(sig.parameters[param_name])
                try:
                    call_args[param_name] = _coerce(param_value, ann)
                except (ValueError, TypeError):
                    await _send_json(422, {"detail": f"Invalid {param_name}"})
                    return

        for param_name, param in sig.parameters.items():
            if param_name in call_args:
                continue
            depends = _get_depends(param)
            if depends is not None:
                try:
                    call_args[param_name] = await _resolve_dependency(depends, context)
                except _HTTPException as e:
                    await _send_json(e.status_code, {"detail": e.detail}, headers=e.headers)
                    return
                except Exception as e:
                    await _send_json(500, {"detail": str(e)})
                    return
                continue
            default = param.default
            ann = _annotation(param)
            if isinstance(default, _Query):
                key = default.alias or param_name
                if key in qs:
                    call_args[param_name] = _coerce(qs[key][0], ann)
                elif default.default is not ...:
                    call_args[param_name] = default.default
            elif isinstance(default, _Header):
                key = default.alias or (param_name.replace("_", "-") if default.convert_underscores else param_name)
                val = headers.get(key.lower())
                if val is None and default.default is not ...:
                    val = default.default
                if val is not None:
                    call_args[param_name] = _coerce(val, ann)
            elif isinstance(default, _Cookie):
                key = default.alias or param_name
                val = cookies.get(key)
                if val is None and default.default is not ...:
                    val = default.default
                if val is not None:
                    call_args[param_name] = _coerce(val, ann)
            elif not _is_body_marker(default) and param_name in qs:
                call_args[param_name] = _coerce(qs[param_name][0], ann)

        if body:
            content_type_val = headers.get("content-type", "")
            if "multipart/form-data" in content_type_val:
                import io as _io
                boundary = ""
                for _part in content_type_val.split(";"):
                    _part = _part.strip()
                    if _part.startswith("boundary="):
                        boundary = _part[9:].strip('"')
                        break
                if boundary:
                    _form_fields, _file_fields = _parse_multipart(body, boundary)
                    _file_map = {f["name"]: f for f in _file_fields}
                    for param_name, param in sig.parameters.items():
                        if param_name in call_args or _get_depends(param) is not None:
                            continue
                        default = param.default
                        ann = _annotation(param)
                        is_file_default = isinstance(default, _File)
                        is_upload_ann = ann is _UF
                        if is_file_default or is_upload_ann:
                            field_name = default.alias if is_file_default and default.alias else param_name
                            if field_name in _file_map:
                                fd = _file_map[field_name]
                                call_args[param_name] = _UF(
                                    filename=fd["filename"],
                                    file=_io.BytesIO(fd["body"]),
                                    content_type=fd["content_type"],
                                    size=len(fd["body"]),
                                )
                        elif isinstance(default, _Form):
                            field_name = default.alias if default.alias else param_name
                            if field_name in _form_fields:
                                call_args[param_name] = _coerce(_form_fields[field_name], ann)
                            elif default.default is not ...:
                                call_args[param_name] = default.default
            elif "application/x-www-form-urlencoded" in content_type_val:
                _qs = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
                for param_name, param in sig.parameters.items():
                    if param_name in call_args or _get_depends(param) is not None:
                        continue
                    default = param.default
                    ann = _annotation(param)
                    if isinstance(default, _Form):
                        field_name = default.alias if default.alias else param_name
                        if field_name in _qs:
                            call_args[param_name] = _coerce(_qs[field_name][0], ann)
                        elif default.default is not ...:
                            call_args[param_name] = default.default
            else:
                try:
                    json_body = _json.loads(body)
                    for param_name, param in sig.parameters.items():
                        if param_name in call_args or _get_depends(param) is not None:
                            continue
                        ann = _annotation(param)
                        if ann != inspect.Parameter.empty and hasattr(ann, "model_validate"):
                            call_args[param_name] = ann.model_validate(json_body)
                        elif param_name in (json_body if isinstance(json_body, dict) else {}):
                            call_args[param_name] = _coerce(json_body[param_name], ann)
                except (_json.JSONDecodeError, Exception):
                    pass

        try:
            if asyncio.iscoroutinefunction(route.handler):
                result = await route.handler(**call_args)
            else:
                result = route.handler(**call_args)
        except _HTTPException as e:
            await _send_json(e.status_code, {"detail": e.detail}, headers=e.headers)
            return
        except Exception as e:
            handler = None
            for exc_type, candidate in self._exception_handlers.items():
                if isinstance(e, exc_type):
                    handler = candidate
                    break
            if handler is not None:
                result = await _call_maybe_async(handler, None, e)
                await _send_result(result)
                return
            await _send_json(500, {"detail": str(e)})
            return

        await _send_result(result)
