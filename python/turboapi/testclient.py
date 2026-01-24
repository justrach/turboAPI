"""TestClient for TurboAPI.

FastAPI-compatible test client for testing API endpoints without starting a server.
Uses the same interface as httpx/requests.
"""

import json
import inspect
from typing import Any, Optional
from urllib.parse import urlencode, urlparse, parse_qs


class TestResponse:
    """Response object returned by TestClient."""

    def __init__(
        self,
        status_code: int = 200,
        content: bytes = b"",
        headers: Optional[dict[str, str]] = None,
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
        params: Optional[dict] = None,
        json: Any = None,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
        cookies: Optional[dict] = None,
        content: Optional[bytes] = None,
    ) -> TestResponse:
        """Execute a request against the app."""
        import asyncio

        # Parse URL
        parsed = urlparse(url)
        path = parsed.path or "/"
        query_string = parsed.query or ""

        # Add query params
        if params:
            if query_string:
                query_string += "&" + urlencode(params)
            else:
                query_string = urlencode(params)

        # Build request body
        body = b""
        request_headers = dict(headers or {})

        if json is not None:
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

        # Find matching route
        route, path_params = self._find_route(method.upper(), path)
        if route is None:
            return TestResponse(status_code=404, content=b'{"detail":"Not Found"}')

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
            # Check for HTTPException
            if hasattr(e, "status_code") and hasattr(e, "detail"):
                error_body = {"detail": e.detail}
                return TestResponse(
                    status_code=e.status_code,
                    content=_json_encode(error_body),
                    headers=getattr(e, "headers", None) or {},
                )
            return TestResponse(
                status_code=500,
                content=_json_encode({"detail": str(e)}),
            )

        # Run background tasks if any
        for param_name, param in sig.parameters.items():
            if param.annotation is BackgroundTasks and param_name in kwargs:
                kwargs[param_name].run_tasks()

        # Build response
        return self._build_response(result)

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
                    params = dict(zip(param_names, match.groups()))
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
        from .responses import Response as TurboResponse, JSONResponse

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
        except (TypeError, ValueError):
            return TestResponse(
                status_code=200,
                content=str(result).encode("utf-8"),
            )


def _json_encode(obj: Any) -> bytes:
    """JSON encode an object to bytes."""
    import json as json_module
    return json_module.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
