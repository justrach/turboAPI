"""Response classes for TurboAPI.

FastAPI-compatible response types: JSONResponse, HTMLResponse, PlainTextResponse,
StreamingResponse, FileResponse, RedirectResponse.
"""

import json
import mimetypes
import os
from collections.abc import AsyncIterator, Iterator
from typing import Any


class Response:
    """Base response class."""

    media_type: str | None = None
    charset: str = "utf-8"

    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        media_type: str | None = None,
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self._cookies: list[str] = []
        if media_type is not None:
            self.media_type = media_type
        self._content = content  # Store original content for model_dump
        self.body = self._render(content)
        # Expose ``.content`` for middleware hooks that read/replace the body
        # (e.g. GZipMiddleware does ``response.content = compressed``).
        self.content = self.body

    def _render(self, content: Any) -> bytes:
        if content is None:
            return b""
        if isinstance(content, bytes):
            return content
        return content.encode(self.charset)

    def model_dump(self) -> Any:
        """Return the content for JSON serialization."""
        # Decode body back to content
        if isinstance(self.body, bytes):
            try:
                return json.loads(self.body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self.body.decode("utf-8")
        return self._content

    def set_cookie(
        self,
        key: str,
        value: str = "",
        max_age: int | None = None,
        expires: int | None = None,
        path: str = "/",
        domain: str | None = None,
        secure: bool = False,
        httponly: bool = False,
        samesite: str | None = "lax",
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
        self._cookies.append(cookie)
        # Also expose in headers dict for direct access (FastAPI compat)
        existing = self.headers.get("set-cookie")
        if existing is None:
            self.headers["set-cookie"] = cookie
        elif isinstance(existing, list):
            existing.append(cookie)
        else:
            self.headers["set-cookie"] = [existing, cookie]

    def delete_cookie(self, key: str, path: str = "/", domain: str | None = None) -> None:
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
        headers: dict[str, str] | None = None,
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
        content: AsyncIterator | Iterator,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        media_type: str | None = None,
    ):
        self.status_code = status_code
        self.headers = headers or {}
        if media_type:
            self.media_type = media_type
        self._content_iterator = content
        self.body = b""  # Will be streamed
        self._cookies: list[str] = []

    async def body_iterator(self) -> AsyncIterator[bytes]:
        """Iterate over the response body chunks (async)."""
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

    def body_iter(self):
        """Return a sync iterator of bytes chunks suitable for the Zig
        chunked-transfer write path.

        Sync sources are wrapped directly. Async sources are driven one
        chunk at a time via the worker thread's event loop — each call
        to next() runs the loop until the source yields one chunk. That
        gives real-time streaming for SSE / token streams without
        introducing a separate event loop or background thread.
        """
        src = self._content_iterator
        if hasattr(src, "__aiter__"):
            return _AsyncToSyncChunkIterator(src)
        return _sync_chunk_iter(src)


def _sync_chunk_iter(src):
    """Encode str chunks → bytes; pass bytes through."""
    for chunk in src:
        if isinstance(chunk, str):
            yield chunk.encode("utf-8")
        else:
            yield chunk


class _AsyncToSyncChunkIterator:
    """Drive an async iterator one chunk at a time on the worker's loop.

    Reuses the per-thread event loop from `turboapi.async_pool` so we
    don't spawn a fresh loop per chunk. StopAsyncIteration → StopIteration.
    """

    __slots__ = ("_aiter", "_loop_runner")

    def __init__(self, async_source):
        self._aiter = async_source.__aiter__()
        self._loop_runner = None

    def __iter__(self):
        return self

    def __next__(self):
        # Lazy-import to avoid a circular import at module load.
        if self._loop_runner is None:
            from turboapi.async_pool import ensure_event_loop
            self._loop_runner = ensure_event_loop().run_until_complete
        try:
            chunk = self._loop_runner(self._aiter.__anext__())
        except StopAsyncIteration:
            raise StopIteration from None
        if isinstance(chunk, str):
            return chunk.encode("utf-8")
        return chunk


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
        headers: dict[str, str] | None = None,
        media_type: str | None = None,
        filename: str | None = None,
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
        self._cookies: list[str] = []
