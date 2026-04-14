"""TestClient for TurboAPI.

FastAPI-compatible test client for testing API endpoints without starting a server.
Uses the same interface as httpx/requests.
"""

import inspect
import json
import uuid
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse


class TestResponse:
    """Response object returned by TestClient."""

    def __init__(
        self,
        status_code: int = 200,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self._json = None

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def json(self) -> Any:
        if self._json is None:
            self._json = json.loads(self.content)
        return self._json

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def is_redirect(self) -> bool:
        return 300 <= self.status_code < 400

    @property
    def is_client_error(self) -> bool:
        return 400 <= self.status_code < 500

    @property
    def is_server_error(self) -> bool:
        return 500 <= self.status_code < 600

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPStatusError(
                f"HTTP {self.status_code}",
                response=self,
            )


class HTTPStatusError(Exception):
    """Raised when a response has a 4xx or 5xx status code."""

    def __init__(self, message: str, response: TestResponse):
        self.response = response
        super().__init__(message)


class TestClient:
    """Test client for TurboAPI applications.

    Usage:
        from turboapi import TurboAPI
        from turboapi.testclient import TestClient

        app = TurboAPI()

        @app.get("/")
        def root():
            return {"message": "Hello"}

        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"message": "Hello"}
    """

    def __init__(self, app, base_url: str = "http://testserver"):
        self.app = app
        self.base_url = base_url
        self._cookies: dict[str, str] = {}

    def get(self, url: str, **kwargs) -> TestResponse:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> TestResponse:
        return self._request("POST", url, **kwargs)

    def put(self, url: str, **kwargs) -> TestResponse:
        return self._request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs) -> TestResponse:
        return self._request("DELETE", url, **kwargs)

    def patch(self, url: str, **kwargs) -> TestResponse:
        return self._request("PATCH", url, **kwargs)

    def options(self, url: str, **kwargs) -> TestResponse:
        return self._request("OPTIONS", url, **kwargs)

    def head(self, url: str, **kwargs) -> TestResponse:
        return self._request("HEAD", url, **kwargs)

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json: Any = None,
        data: dict | None = None,
        files: dict | None = None,
        headers: dict | None = None,
        cookies: dict | None = None,
        content: bytes | None = None,
    ) -> TestResponse:
        """Execute a request against the app."""
        import asyncio

        parsed = urlparse(url)
        path = parsed.path or "/"
        query_string = parsed.query or ""

        if params:
            if query_string:
                query_string += "&" + urlencode(params)
            else:
                query_string = urlencode(params)

        body = b""
        request_headers = dict(headers or {})

        if files is not None:
            boundary = f"----TurboAPIBoundary{uuid.uuid4().hex[:16]}"
            parts = []
            for field_name, file_info in files.items():
                if isinstance(file_info, tuple):
                    filename, file_content = file_info
                    if isinstance(file_content, str):
                        file_content = file_content.encode("utf-8")
                    file_ct = "application/octet-stream"
                    if len(file_info) > 2:
                        file_ct = file_info[2]
                elif isinstance(file_info, dict):
                    filename = file_info.get("filename", "upload")
                    file_content = file_info.get("content", b"")
                    if isinstance(file_content, str):
                        file_content = file_content.encode("utf-8")
                    file_ct = file_info.get("content_type", "application/octet-stream")
                else:
                    filename = "upload"
                    file_content = file_info
                    file_ct = "application/octet-stream"
                parts.append(
                    f"--{boundary}\r\n".encode()
                    + f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
                    + f"Content-Type: {file_ct}\r\n\r\n".encode()
                    + file_content
                    + b"\r\n"
                )
            if data:
                for k, v in data.items():
                    parts.append(
                        f"--{boundary}\r\n".encode()
                        + f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
                        + str(v).encode("utf-8")
                        + b"\r\n"
                    )
            body = b"".join(parts) + f"--{boundary}--\r\n".encode()
            request_headers.setdefault("content-type", f"multipart/form-data; boundary={boundary}")
        elif json is not None:
            import json as json_module

            body = json_module.dumps(json).encode("utf-8")
            request_headers.setdefault("content-type", "application/json")
        elif data is not None:
            body = urlencode(data).encode("utf-8")
            request_headers.setdefault("content-type", "application/x-www-form-urlencoded")
        elif content is not None:
            body = content

        # Merge cookies
        merged_cookies = {**self._cookies}
        if cookies:
            merged_cookies.update(cookies)
        if merged_cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in merged_cookies.items())
            request_headers["cookie"] = cookie_str

        # Issue #104: Check mounted apps (e.g. StaticFiles) before route matching
        if hasattr(self.app, "_mounts"):
            for mount_path, mount_info in self.app._mounts.items():
                if path.startswith(mount_path + "/") or path == mount_path:
                    sub_path = path[len(mount_path) :]
                    mounted_app = mount_info["app"]
                    if hasattr(mounted_app, "get_file"):
                        result = mounted_app.get_file(sub_path)
                        if result is not None:
                            content_bytes, content_type, size = result
                            return TestResponse(
                                status_code=200,
                                content=content_bytes,
                                headers={"content-type": content_type},
                            )

        # Issue #102: Serve docs and openapi URLs
        if (
            hasattr(self.app, "openapi_url")
            and self.app.openapi_url
            and path == self.app.openapi_url
        ):
            import json as json_module

            schema = self.app.openapi()
            body = json_module.dumps(schema).encode("utf-8")
            return TestResponse(
                status_code=200, content=body, headers={"content-type": "application/json"}
            )

        if hasattr(self.app, "docs_url") and self.app.docs_url and path == self.app.docs_url:
            html = f"""<!DOCTYPE html>
<html><head><title>{self.app.title} - Swagger UI</title></head>
<body><div id="swagger-ui"></div></body></html>"""
            return TestResponse(
                status_code=200, content=html.encode("utf-8"), headers={"content-type": "text/html"}
            )

        # Find matching route
        route, path_params = self._find_route(method.upper(), path)
        if route is None:
            return TestResponse(status_code=404, content=b'{"detail":"Not Found"}')

        # Issue #103: Enforce router-level dependencies
        if hasattr(route, "dependencies") and route.dependencies:
            for dep in route.dependencies:
                dep_fn = dep.dependency if hasattr(dep, "dependency") else dep
                if dep_fn is not None:
                    try:
                        if inspect.iscoroutinefunction(dep_fn):
                            try:
                                asyncio.get_event_loop().run_until_complete(dep_fn())
                            except RuntimeError:
                                asyncio.run(dep_fn())
                        else:
                            dep_fn()
                    except Exception as dep_exc:
                        if hasattr(dep_exc, "status_code") and hasattr(dep_exc, "detail"):
                            return TestResponse(
                                status_code=dep_exc.status_code,
                                content=_json_encode({"detail": dep_exc.detail}),
                                headers=getattr(dep_exc, "headers", None) or {},
                            )
                        raise

        # Build handler kwargs
        handler = route.handler
        sig = inspect.signature(handler)
        kwargs = {}

        # Add path params
        kwargs.update(path_params)

        # Add query params
        if query_string:
            qp = parse_qs(query_string, keep_blank_values=True)
            for key, values in qp.items():
                if key in sig.parameters:
                    param = sig.parameters[key]
                    val = values[0] if len(values) == 1 else values
                    # Type coercion
                    if param.annotation is int:
                        val = int(val)
                    elif param.annotation is float:
                        val = float(val)
                    elif param.annotation is bool:
                        val = val.lower() in ("true", "1", "yes")
                    kwargs[key] = val

        # Add body params
        if body and request_headers.get("content-type") == "application/json":
            import json as json_module

            body_data = json_module.loads(body)
            if isinstance(body_data, dict):
                for key, val in body_data.items():
                    if key in sig.parameters:
                        kwargs[key] = val

        # Add BackgroundTasks if requested
        from .background import BackgroundTasks

        for param_name, param in sig.parameters.items():
            if param.annotation is BackgroundTasks:
                kwargs[param_name] = BackgroundTasks()

        # Resolve Depends/Annotated[..., Depends(...)] parameters
        try:
            from .security import get_depends

            for param_name, param in sig.parameters.items():
                if param_name in kwargs:
                    continue
                dep = get_depends(param)
                if dep is not None and dep.dependency is not None:
                    dep_fn = dep.dependency
                    if inspect.iscoroutinefunction(dep_fn):
                        try:
                            kwargs[param_name] = asyncio.run(dep_fn())
                        except RuntimeError:
                            kwargs[param_name] = dep_fn()
                    else:
                        kwargs[param_name] = dep_fn()
        except ImportError:
            pass

        # Run before_request middleware
        from .models import Request

        request_obj = Request(
            method=method,
            url=path,
            headers=request_headers,
            query_params=parse_qs(query_string) if query_string else {},
        )

        middleware_instances = []
        for middleware_class, mw_kwargs in getattr(self.app, "middleware_stack", []):
            try:
                mw_instance = middleware_class(**mw_kwargs)
                middleware_instances.append(mw_instance)
                try:
                    mw_instance.before_request(request_obj)
                except Exception as e:
                    # Middleware error - return error response
                    return TestResponse(
                        status_code=getattr(e, "status_code", 500),
                        content=_json_encode({"detail": str(e)}),
                    )
            except Exception:
                pass  # Skip middleware that fails to initialize

        # Call handler
        try:
            if inspect.iscoroutinefunction(handler):
                try:
                    loop = asyncio.get_running_loop()
                    result = loop.run_until_complete(handler(**kwargs))
                except RuntimeError:
                    result = asyncio.run(handler(**kwargs))
            else:
                result = handler(**kwargs)
        except Exception as e:
            # Issue #100: Check registered custom exception handlers first
            if hasattr(self.app, "_exception_handlers"):
                for exc_class, exc_handler in self.app._exception_handlers.items():
                    if isinstance(e, exc_class):
                        result = exc_handler(None, e)
                        if inspect.isawaitable(result):
                            try:
                                result = asyncio.get_event_loop().run_until_complete(result)
                            except RuntimeError:
                                result = asyncio.run(result)
                        return self._build_response(result)
            # Check for HTTPException
            if hasattr(e, "status_code") and hasattr(e, "detail"):
                error_body = {"detail": e.detail}
                response = TestResponse(
                    status_code=e.status_code,
                    content=_json_encode(error_body),
                    headers=getattr(e, "headers", None) or {},
                )
            else:
                response = TestResponse(
                    status_code=500,
                    content=_json_encode({"detail": str(e)}),
                )

            # Run after_request middleware on error response
            for mw_instance in reversed(middleware_instances):
                try:
                    response = self._response_to_turbo_response(response)
                    response = mw_instance.after_request(request_obj, response)
                    response = self._turbo_response_to_test_response(response)
                except Exception:
                    pass
            return response

        # Run background tasks if any
        for param_name, param in sig.parameters.items():
            if param.annotation is BackgroundTasks and param_name in kwargs:
                kwargs[param_name].run_tasks()

        # Build response
        response = self._build_response(result)

        # Run after_request middleware
        for mw_instance in reversed(middleware_instances):
            try:
                turbo_response = self._response_to_turbo_response(response)
                processed = mw_instance.after_request(request_obj, turbo_response)
                response = self._turbo_response_to_test_response(processed)
            except Exception:
                pass  # Skip middleware that fails

        return response

    def _find_route(self, method: str, path: str):
        """Find a matching route for the given method and path."""
        import re

        routes = self.app.registry.get_routes()
        for route in routes:
            if route.method.value.upper() != method:
                continue

            # Check for exact match
            if route.path == path:
                return route, {}

            # Check for path parameter match
            pattern = route.path
            param_names = re.findall(r"\{([^}]+)\}", pattern)
            if param_names:
                regex_pattern = pattern
                for name in param_names:
                    regex_pattern = regex_pattern.replace(f"{{{name}}}", "([^/]+)")
                match = re.match(f"^{regex_pattern}$", path)
                if match:
                    params = dict(zip(param_names, match.groups(), strict=False))
                    # Type coerce path params based on handler signature
                    sig = inspect.signature(route.handler)
                    for name, val in params.items():
                        if name in sig.parameters:
                            ann = sig.parameters[name].annotation
                            if ann is int:
                                params[name] = int(val)
                            elif ann is float:
                                params[name] = float(val)
                    return route, params

        return None, {}

    def _build_response(self, result) -> TestResponse:
        """Convert handler result to TestResponse."""
        from .responses import Response as TurboResponse

        # Handle Response objects
        if isinstance(result, TurboResponse):
            return TestResponse(
                status_code=result.status_code,
                content=result.body,
                headers=result.headers,
            )

        # Handle dict/list (default JSON response)
        if isinstance(result, (dict, list)):
            content = _json_encode(result)
            return TestResponse(
                status_code=200,
                content=content,
                headers={"content-type": "application/json"},
            )

        # Handle string
        if isinstance(result, str):
            return TestResponse(
                status_code=200,
                content=result.encode("utf-8"),
                headers={"content-type": "text/plain"},
            )

        # Handle None
        if result is None:
            return TestResponse(status_code=200, content=b"null")

        # Fallback: try JSON serialization
        try:
            content = _json_encode(result)
            return TestResponse(status_code=200, content=content)
        except TypeError, ValueError:
            return TestResponse(
                status_code=200,
                content=str(result).encode("utf-8"),
            )

    def _response_to_turbo_response(self, response: TestResponse):
        """Convert TestResponse to TurboResponse for middleware processing."""
        from .models import Response

        turbo_response = Response(content=response.content, status_code=response.status_code)
        turbo_response.headers = dict(response.headers)
        return turbo_response

    def _turbo_response_to_test_response(self, turbo_response) -> TestResponse:
        """Convert TurboResponse back to TestResponse after middleware processing."""
        content = getattr(turbo_response, "content", None) or getattr(turbo_response, "body", b"")
        if isinstance(content, str):
            content = content.encode("utf-8")
        return TestResponse(
            status_code=getattr(turbo_response, "status_code", 200),
            content=content,
            headers=dict(getattr(turbo_response, "headers", {})),
        )


def _json_encode(obj: Any) -> bytes:
    """JSON encode an object to bytes."""
    import json as json_module

    return json_module.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
