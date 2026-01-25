"""OpenAPI schema generation and Swagger/ReDoc UI for TurboAPI.

Generates OpenAPI 3.1.0 compatible schemas from route definitions and serves
interactive API documentation at /docs (Swagger UI) and /redoc (ReDoc).
"""

import inspect
import json
from typing import Any, Optional, get_origin, get_args


def generate_openapi_schema(app) -> dict:
    """Generate OpenAPI 3.1.0 schema from app routes.

    Args:
        app: TurboAPI application instance.

    Returns:
        OpenAPI schema dict.
    """
    schema = {
        "openapi": "3.1.0",
        "info": {
            "title": getattr(app, "title", "TurboAPI"),
            "version": getattr(app, "version", "0.1.0"),
            "description": getattr(app, "description", ""),
        },
        "paths": {},
        "components": {"schemas": {}},
    }

    routes = app.registry.get_routes()
    for route in routes:
        path = route.path
        method = route.method.value.lower()
        handler = route.handler

        # Generate operation
        operation = _generate_operation(handler, route)

        # Add to paths
        openapi_path = _convert_path(path)
        if openapi_path not in schema["paths"]:
            schema["paths"][openapi_path] = {}
        schema["paths"][openapi_path][method] = operation

    return schema


def _convert_path(path: str) -> str:
    """Convert route path to OpenAPI format (already uses {param} syntax)."""
    return path


def _generate_operation(handler, route) -> dict:
    """Generate OpenAPI operation object from handler."""
    operation: dict[str, Any] = {
        "summary": _get_summary(handler),
        "operationId": f"{route.method.value.lower()}_{handler.__name__}",
        "responses": {
            "200": {
                "description": "Successful Response",
                "content": {"application/json": {"schema": {}}},
            },
            "422": {
                "description": "Validation Error",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/HTTPValidationError"}
                    }
                },
            },
        },
    }

    # Extract parameters from signature
    sig = inspect.signature(handler)
    parameters = []
    request_body_props = {}

    import re
    path_params = set(re.findall(r"\{([^}]+)\}", route.path))

    for param_name, param in sig.parameters.items():
        annotation = param.annotation
        param_schema = _type_to_schema(annotation)

        if param_name in path_params:
            parameters.append({
                "name": param_name,
                "in": "path",
                "required": True,
                "schema": param_schema,
            })
        elif route.method.value.upper() in ("POST", "PUT", "PATCH"):
            # Body parameter
            request_body_props[param_name] = param_schema
            if param.default is not inspect.Parameter.empty:
                request_body_props[param_name]["default"] = param.default
        else:
            # Query parameter
            query_param = {
                "name": param_name,
                "in": "query",
                "schema": param_schema,
            }
            if param.default is inspect.Parameter.empty:
                query_param["required"] = True
            else:
                query_param["required"] = False
                if param.default is not None:
                    query_param["schema"]["default"] = param.default
            parameters.append(query_param)

    if parameters:
        operation["parameters"] = parameters

    if request_body_props:
        operation["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": request_body_props,
                    }
                }
            },
        }

    # Add tags
    if hasattr(route, "tags") and route.tags:
        operation["tags"] = route.tags

    # Add docstring as description
    if handler.__doc__:
        operation["description"] = handler.__doc__.strip()

    return operation


def _get_summary(handler) -> str:
    """Generate summary from handler name."""
    name = handler.__name__
    return name.replace("_", " ").title()


def _type_to_schema(annotation) -> dict:
    """Convert Python type annotation to OpenAPI schema."""
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {}
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is list:
        return {"type": "array", "items": {}}
    if annotation is dict:
        return {"type": "object"}
    if annotation is bytes:
        return {"type": "string", "format": "binary"}

    # Handle typing generics
    origin = get_origin(annotation)
    if origin is list:
        args = get_args(annotation)
        items_schema = _type_to_schema(args[0]) if args else {}
        return {"type": "array", "items": items_schema}
    if origin is dict:
        return {"type": "object"}

    # Handle Optional
    if origin is type(None):
        return {"nullable": True}

    # Try to get schema from Satya/Pydantic models
    try:
        if hasattr(annotation, "__fields__") or hasattr(annotation, "model_fields"):
            return {"$ref": f"#/components/schemas/{annotation.__name__}"}
    except (TypeError, AttributeError):
        pass

    return {}


# HTML templates for Swagger UI and ReDoc
SWAGGER_UI_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>{title} - Swagger UI</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
SwaggerUIBundle({{
    url: "{openapi_url}",
    dom_id: '#swagger-ui',
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
    layout: "BaseLayout"
}})
</script>
</body>
</html>"""

REDOC_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>{title} - ReDoc</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
    <style>body {{ margin: 0; padding: 0; }}</style>
</head>
<body>
<redoc spec-url='{openapi_url}'></redoc>
<script src="https://unpkg.com/redoc@latest/bundles/redoc.standalone.js"></script>
</body>
</html>"""


def get_swagger_ui_html(title: str, openapi_url: str = "/openapi.json") -> str:
    """Generate Swagger UI HTML page."""
    return SWAGGER_UI_HTML.format(title=title, openapi_url=openapi_url)


def get_redoc_html(title: str, openapi_url: str = "/openapi.json") -> str:
    """Generate ReDoc HTML page."""
    return REDOC_HTML.format(title=title, openapi_url=openapi_url)
