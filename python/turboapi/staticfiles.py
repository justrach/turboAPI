"""Static file serving for TurboAPI.

FastAPI-compatible static file mounting.
"""

import mimetypes
import os
from pathlib import Path
from typing import Optional


class StaticFiles:
    """Serve static files from a directory.

    Usage:
        from turboapi import TurboAPI
        from turboapi.staticfiles import StaticFiles

        app = TurboAPI()
        app.mount("/static", StaticFiles(directory="static"), name="static")
    """

    def __init__(
        self,
        directory: Optional[str] = None,
        packages: Optional[list[str]] = None,
        html: bool = False,
        check_dir: bool = True,
    ):
        self.directory = Path(directory) if directory else None
        self.packages = packages
        self.html = html

        if check_dir and self.directory and not self.directory.is_dir():
            raise RuntimeError(f"Directory '{directory}' does not exist")

    def get_file(self, path: str) -> Optional[tuple[bytes, str, int]]:
        """Get a file's contents, content type, and size.

        Returns (content, content_type, size) or None if not found.
        """
        if self.directory is None:
            return None

        # Security: prevent path traversal
        try:
            file_path = (self.directory / path.lstrip("/")).resolve()
            if not str(file_path).startswith(str(self.directory.resolve())):
                return None
        except (ValueError, OSError):
            return None

        # Check if it's a file
        if not file_path.is_file():
            # If html mode, try adding .html or looking for index.html
            if self.html:
                if file_path.is_dir():
                    index = file_path / "index.html"
                    if index.is_file():
                        file_path = index
                    else:
                        return None
                else:
                    html_path = file_path.with_suffix(".html")
                    if html_path.is_file():
                        file_path = html_path
                    else:
                        return None
            else:
                return None

        # Read file
        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"

        content = file_path.read_bytes()
        return content, content_type, len(content)

    def list_files(self) -> list[str]:
        """List all files in the static directory."""
        if self.directory is None:
            return []

        files = []
        for root, _, filenames in os.walk(self.directory):
            for filename in filenames:
                file_path = Path(root) / filename
                rel_path = file_path.relative_to(self.directory)
                files.append(str(rel_path))
        return files
