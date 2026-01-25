"""Jinja2 templating support for TurboAPI.

FastAPI-compatible template rendering.
"""

from typing import Any, Optional

from .responses import HTMLResponse


class Jinja2Templates:
    """Jinja2 template renderer.

    Usage:
        from turboapi import TurboAPI
        from turboapi.templating import Jinja2Templates

        app = TurboAPI()
        templates = Jinja2Templates(directory="templates")

        @app.get("/page")
        def page():
            return templates.TemplateResponse("page.html", {"title": "Hello"})
    """

    def __init__(self, directory: str):
        self.directory = directory
        self._env = None

    @property
    def env(self):
        """Lazy-load Jinja2 environment."""
        if self._env is None:
            try:
                from jinja2 import Environment, FileSystemLoader
                self._env = Environment(
                    loader=FileSystemLoader(self.directory),
                    autoescape=True,
                )
            except ImportError:
                raise RuntimeError(
                    "jinja2 must be installed to use Jinja2Templates. "
                    "Install it with: pip install jinja2"
                )
        return self._env

    def TemplateResponse(
        self,
        name: str,
        context: Optional[dict[str, Any]] = None,
        status_code: int = 200,
        headers: Optional[dict[str, str]] = None,
    ) -> HTMLResponse:
        """Render a template and return an HTMLResponse.

        Args:
            name: Template filename.
            context: Template context variables.
            status_code: HTTP status code.
            headers: Additional response headers.
        """
        context = context or {}
        template = self.env.get_template(name)
        content = template.render(**context)
        return HTMLResponse(
            content=content,
            status_code=status_code,
            headers=headers,
        )

    def get_template(self, name: str):
        """Get a template by name."""
        return self.env.get_template(name)
