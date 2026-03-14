"""Data structures for TurboAPI - Form, File, UploadFile.

FastAPI-compatible parameter markers and file handling classes.
"""

import io
import tempfile
from typing import Any


class Form:
    """Marker class for form data parameters.

    Usage:
        @app.post("/login")
        async def login(username: str = Form(), password: str = Form()):
            return {"username": username}
    """

    def __init__(
        self,
        default: Any = ...,
        *,
        alias: str | None = None,
        title: str | None = None,
        description: str | None = None,
        min_length: int | None = None,
        max_length: int | None = None,
        regex: str | None = None,
        media_type: str = "application/x-www-form-urlencoded",
    ):
        self.default = default
        self.alias = alias
        self.title = title
        self.description = description
        self.min_length = min_length
        self.max_length = max_length
        self.regex = regex
        self.media_type = media_type


class File:
    """Marker class for file upload parameters.

    Usage:
        @app.post("/upload")
        async def upload(file: bytes = File()):
            return {"file_size": len(file)}
    """

    def __init__(
        self,
        default: Any = ...,
        *,
        alias: str | None = None,
        title: str | None = None,
        description: str | None = None,
        max_length: int | None = None,
        media_type: str = "multipart/form-data",
    ):
        self.default = default
        self.alias = alias
        self.title = title
        self.description = description
        self.max_length = max_length
        self.media_type = media_type


class UploadFile:
    """Represents an uploaded file.

    Usage:
        @app.post("/upload")
        async def upload(file: UploadFile):
            contents = await file.read()
            return {"filename": file.filename, "size": len(contents)}
    """

    def __init__(
        self,
        filename: str | None = None,
        file: io.IOBase | None = None,
        content_type: str = "application/octet-stream",
        *,
        size: int | None = None,
        headers: dict | None = None,
    ):
        self.filename = filename
        self.content_type = content_type
        self.size = size
        self.headers = headers or {}
        if file is None:
            self.file = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
        else:
            self.file = file

    async def read(self, size: int = -1) -> bytes:
        """Read file contents."""
        if hasattr(self.file, "read"):
            return self.file.read(size)
        return b""

    async def write(self, data: bytes) -> None:
        """Write data to the file."""
        if hasattr(self.file, "write"):
            self.file.write(data)

    async def seek(self, offset: int) -> None:
        """Seek to a position in the file."""
        if hasattr(self.file, "seek"):
            self.file.seek(offset)

    async def close(self) -> None:
        """Close the file."""
        if hasattr(self.file, "close"):
            self.file.close()

    def __repr__(self) -> str:
        return f"UploadFile(filename={self.filename!r}, content_type={self.content_type!r}, size={self.size})"


class Header:
    """Marker class for header parameters.

    Usage:
        @app.get("/items")
        async def read_items(x_token: str = Header()):
            return {"X-Token": x_token}
    """

    def __init__(
        self,
        default: Any = ...,
        *,
        alias: str | None = None,
        title: str | None = None,
        description: str | None = None,
        convert_underscores: bool = True,
    ):
        self.default = default
        self.alias = alias
        self.title = title
        self.description = description
        self.convert_underscores = convert_underscores


class Cookie:
    """Marker class for cookie parameters.

    Usage:
        @app.get("/items")
        async def read_items(session_id: str = Cookie()):
            return {"session_id": session_id}
    """

    def __init__(
        self,
        default: Any = ...,
        *,
        alias: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ):
        self.default = default
        self.alias = alias
        self.title = title
        self.description = description


class Query:
    """Marker class for query parameters with validation.

    Usage:
        @app.get("/items")
        async def read_items(q: str = Query(min_length=3)):
            return {"q": q}
    """

    def __init__(
        self,
        default: Any = ...,
        *,
        alias: str | None = None,
        title: str | None = None,
        description: str | None = None,
        min_length: int | None = None,
        max_length: int | None = None,
        regex: str | None = None,
        gt: float | None = None,
        ge: float | None = None,
        lt: float | None = None,
        le: float | None = None,
    ):
        self.default = default
        self.alias = alias
        self.title = title
        self.description = description
        self.min_length = min_length
        self.max_length = max_length
        self.regex = regex
        self.gt = gt
        self.ge = ge
        self.lt = lt
        self.le = le


class Path:
    """Marker class for path parameters with validation.

    Usage:
        @app.get("/items/{item_id}")
        async def read_item(item_id: int = Path(gt=0)):
            return {"item_id": item_id}
    """

    def __init__(
        self,
        default: Any = ...,
        *,
        alias: str | None = None,
        title: str | None = None,
        description: str | None = None,
        gt: float | None = None,
        ge: float | None = None,
        lt: float | None = None,
        le: float | None = None,
    ):
        self.default = default
        self.alias = alias
        self.title = title
        self.description = description
        self.gt = gt
        self.ge = ge
        self.lt = lt
        self.le = le


class Body:
    """Marker class for body parameters.

    Usage:
        @app.post("/items")
        async def create_item(name: str = Body(), price: float = Body()):
            return {"name": name, "price": price}
    """

    def __init__(
        self,
        default: Any = ...,
        *,
        embed: bool = False,
        alias: str | None = None,
        title: str | None = None,
        description: str | None = None,
        media_type: str = "application/json",
    ):
        self.default = default
        self.embed = embed
        self.alias = alias
        self.title = title
        self.description = description
        self.media_type = media_type
