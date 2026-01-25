"""Response classes for TurboAPI.

FastAPI-compatible response types: JSONResponse, HTMLResponse, PlainTextResponse,
StreamingResponse, FileResponse, RedirectResponse.
"""

import json
import mimetypes
import os
from typing import Any, AsyncIterator, Iterator, Optional, Union


class Response:
    """Base response class."""

    media_type: Optional[str] = None
    charset: str = "utf-8"

    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        headers: Optional[dict[str, str]] = None,
        media_type: Optional[str] = None,
    ):
        self.status_code = status_code
        self.headers = headers or {}
        if media_type is not None:
            self.media_type = media_type
        self._content = content  # Store original content for model_dump
        self.body = self._render(content)

    def _render(self, content: Any) -> bytes:
        if content is None:
            return b""
        if isinstance(content, bytes):
            return content
        return content.encode(self.charset)

    def model_dump(self) -> Any:
        """Return the content for JSON serialization (used by Rust SIMD JSON)."""
        # Decode body back to content
        if isinstance(self.body, bytes):
            try:
                return json.loads(self.body.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self.body.decode('utf-8')
        return self._content

    def set_cookie(
        self,
        key: str,
        value: str = "",
        max_age: Optional[int] = None,
        expires: Optional[int] = None,
        path: str = "/",
        domain: Optional[str] = None,
        secure: bool = False,
        httponly: bool = False,
        samesite: Optional[str] = "lax",
    ) -> None:
        """Set a cookie on the response."""
        cookie = f"{key}={value}; Path={path}"
        if max_age is not None:
            cookie += f"; Max-Age={max_age}"
        if expires is not None:
            cookie += f"; Expires={expires}"
        if domain:
            cookie += f"; Domain={domain}"
        if secure:
            cookie += "; Secure"
        if httponly:
            cookie += "; HttpOnly"
        if samesite:
            cookie += f"; SameSite={samesite}"
        self.headers.setdefault("set-cookie", cookie)

    def delete_cookie(self, key: str, path: str = "/", domain: Optional[str] = None) -> None:
        """Delete a cookie."""
        self.set_cookie(key, "", max_age=0, path=path, domain=domain)


class JSONResponse(Response):
    """JSON response. Default response type for TurboAPI."""

    media_type = "application/json"

    def _render(self, content: Any) -> bytes:
        if content is None:
            return b"null"
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")


class HTMLResponse(Response):
    """HTML response."""

    media_type = "text/html"


class PlainTextResponse(Response):
    """Plain text response."""

    media_type = "text/plain"


class RedirectResponse(Response):
    """HTTP redirect response.

    Usage:
        @app.get("/old-path")
        def redirect():
            return RedirectResponse(url="/new-path")
    """

    def __init__(
        self,
        url: str,
        status_code: int = 307,
        headers: Optional[dict[str, str]] = None,
    ):
        headers = headers or {}
        headers["location"] = url
        super().__init__(content=b"", status_code=status_code, headers=headers)


class StreamingResponse(Response):
    """Streaming response for large content or server-sent events.

    Usage:
        async def generate():
            for i in range(10):
                yield f"data: {i}\\n\\n"

        @app.get("/stream")
        def stream():
            return StreamingResponse(generate(), media_type="text/event-stream")
    """

    def __init__(
        self,
        content: Union[AsyncIterator, Iterator],
        status_code: int = 200,
        headers: Optional[dict[str, str]] = None,
        media_type: Optional[str] = None,
    ):
        self.status_code = status_code
        self.headers = headers or {}
        if media_type:
            self.media_type = media_type
        self._content_iterator = content
        self.body = b""  # Will be streamed

    async def body_iterator(self) -> AsyncIterator[bytes]:
        """Iterate over the response body chunks."""
        if hasattr(self._content_iterator, "__aiter__"):
            async for chunk in self._content_iterator:
                if isinstance(chunk, str):
                    yield chunk.encode("utf-8")
                else:
                    yield chunk
        else:
            for chunk in self._content_iterator:
                if isinstance(chunk, str):
                    yield chunk.encode("utf-8")
                else:
                    yield chunk


class FileResponse(Response):
    """File response for serving files from disk.

    Usage:
        @app.get("/download")
        def download():
            return FileResponse("path/to/file.pdf", filename="report.pdf")
    """

    def __init__(
        self,
        path: str,
        status_code: int = 200,
        headers: Optional[dict[str, str]] = None,
        media_type: Optional[str] = None,
        filename: Optional[str] = None,
    ):
        self.path = path
        self.status_code = status_code
        self.headers = headers or {}

        if media_type is None:
            media_type, _ = mimetypes.guess_type(path)
            if media_type is None:
                media_type = "application/octet-stream"
        self.media_type = media_type

        if filename:
            self.headers["content-disposition"] = f'attachment; filename="{filename}"'

        # Read file content
        stat = os.stat(path)
        self.headers["content-length"] = str(stat.st_size)

        with open(path, "rb") as f:
            self.body = f.read()
