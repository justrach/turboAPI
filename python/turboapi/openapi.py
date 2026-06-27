"""OpenAPI schema generation and Swagger/ReDoc UI for TurboAPI.

Generates OpenAPI 3.1.0 compatible schemas from route definitions and serves
interactive API documentation at /docs (Swagger UI) and /redoc (ReDoc).
"""

import inspect
import json
import types
from typing import Annotated, Any, Union, get_args, get_origin

from .datastructures import Body, Cookie, File, Form, Header, Path, Query, UploadFile
from .security import get_depends


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
    components = schema["components"]["schemas"]
    _add_validation_error_schemas(components)

    routes = app.registry.get_routes()
    for route in routes:
        path = route.path
        method = route.method.value.lower()
        handler = route.handler

        # Generate operation
        operation = _generate_operation(handler, route, components)

        # Add to paths
        openapi_path = _convert_path(path)
        if openapi_path not in schema["paths"]:
            schema["paths"][openapi_path] = {}
        schema["paths"][openapi_path][method] = operation

    return schema


def _convert_path(path: str) -> str:
    """Convert route path to OpenAPI format (already uses {param} syntax)."""
    return path


def _generate_operation(handler, route, components: dict[str, Any]) -> dict:
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

    response_model = getattr(route, "response_model", None)
    if response_model is not None:
        operation["responses"]["200"]["content"]["application/json"]["schema"] = (
            _type_to_schema(response_model, components)
        )

    sig = inspect.signature(handler)
    parameters = []
    json_body_items: list[dict[str, Any]] = []
    form_body_items: list[dict[str, Any]] = []
    multipart_body_items: list[dict[str, Any]] = []

    import re

    path_params = set(re.findall(r"\{([^}]+)\}", route.path))
    body_methods = {"POST", "PUT", "PATCH"}
    method = route.method.value.upper()

    for param_name, param in sig.parameters.items():
        if get_depends(param) is not None:
            continue

        annotation, metadata = _unwrap_annotated(param.annotation)
        marker = _get_marker(param, metadata)

        if param_name in path_params or isinstance(marker, Path):
            parameters.append(
                _build_parameter(
                    _param_name(param_name, marker),
                    "path",
                    annotation,
                    components,
                    param,
                    marker,
                    required=True,
                )
            )
        elif isinstance(marker, Query):
            parameters.append(
                _build_parameter(
                    _param_name(param_name, marker),
                    "query",
                    annotation,
                    components,
                    param,
                    marker,
                )
            )
        elif isinstance(marker, Header):
            name = marker.alias or (
                param_name.replace("_", "-")
                if getattr(marker, "convert_underscores", True)
                else param_name
            )
            parameters.append(
                _build_parameter(name, "header", annotation, components, param, marker)
            )
        elif isinstance(marker, Cookie):
            parameters.append(
                _build_parameter(
                    _param_name(param_name, marker),
                    "cookie",
                    annotation,
                    components,
                    param,
                    marker,
                )
            )
        elif isinstance(marker, Form):
            form_body_items.append(
                _build_body_item(
                    _param_name(param_name, marker),
                    annotation,
                    components,
                    param,
                    marker,
                )
            )
        elif isinstance(marker, File) or annotation is UploadFile:
            multipart_body_items.append(
                _build_body_item(
                    _param_name(param_name, marker),
                    annotation,
                    components,
                    param,
                    marker,
                    schema={"type": "string", "format": "binary"},
                )
            )
        elif isinstance(marker, Body) or method in body_methods:
            json_body_items.append(
                _build_body_item(
                    _param_name(param_name, marker),
                    annotation,
                    components,
                    param,
                    marker,
                )
            )
        else:
            parameters.append(
                _build_parameter(param_name, "query", annotation, components, param, marker)
            )

    if parameters:
        operation["parameters"] = parameters

    content = {}
    if json_body_items:
        content["application/json"] = {
            "schema": _build_json_body_schema(json_body_items, components)
        }
    if form_body_items:
        content["application/x-www-form-urlencoded"] = {
            "schema": _build_object_body_schema(form_body_items)
        }
    if multipart_body_items:
        content["multipart/form-data"] = {
            "schema": _build_object_body_schema(multipart_body_items)
        }

    if content:
        body_groups = (json_body_items, form_body_items, multipart_body_items)
        operation["requestBody"] = {
            "required": any(item["required"] for items in body_groups for item in items),
            "content": content,
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


def _add_validation_error_schemas(components: dict[str, Any]) -> None:
    """Register the default 422 response component schemas."""
    components.setdefault(
        "ValidationError",
        {
            "type": "object",
            "title": "ValidationError",
            "properties": {
                "loc": {
                    "type": "array",
                    "items": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                },
                "msg": {"type": "string"},
                "type": {"type": "string"},
            },
            "required": ["loc", "msg", "type"],
        },
    )
    components.setdefault(
        "HTTPValidationError",
        {
            "type": "object",
            "title": "HTTPValidationError",
            "properties": {
                "detail": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/ValidationError"},
                }
            },
        },
    )


_MARKER_TYPES = (Form, File, Query, Header, Cookie, Path, Body)


def _unwrap_annotated(annotation):
    """Return the base annotation and Annotated metadata."""
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        return args[0], list(args[1:])
    return annotation, []


def _get_marker(param: inspect.Parameter, metadata: list[Any]):
    if isinstance(param.default, _MARKER_TYPES):
        return param.default
    for item in metadata:
        if isinstance(item, _MARKER_TYPES):
            return item
    return None


def _param_name(name: str, marker) -> str:
    return getattr(marker, "alias", None) or name


def _is_json_safe(value: Any) -> bool:
    try:
        json.dumps(value)
    except TypeError:
        return False
    return True


def _json_safe_schema(value: Any):
    if isinstance(value, dict):
        return {
            key: _json_safe_schema(item)
            for key, item in value.items()
            if isinstance(item, (dict, list)) or _is_json_safe(item)
        }
    if isinstance(value, list):
        return [
            _json_safe_schema(item)
            for item in value
            if isinstance(item, (dict, list)) or _is_json_safe(item)
        ]
    return value if _is_json_safe(value) else None


def _is_model_type(annotation) -> bool:
    return inspect.isclass(annotation) and (
        hasattr(annotation, "model_json_schema")
        or hasattr(annotation, "schema")
        or hasattr(annotation, "model_fields")
        or hasattr(annotation, "__fields__")
    )


def _register_model_schema(annotation, components: dict[str, Any]) -> str:
    name = annotation.__name__
    if name in components:
        return name

    if hasattr(annotation, "model_json_schema"):
        schema = annotation.model_json_schema()
    elif hasattr(annotation, "schema"):
        schema = annotation.schema()
    else:
        schema = {"title": name, "type": "object"}

    components[name] = _json_safe_schema(schema)
    return name


def _schema_default(param: inspect.Parameter, marker):
    if marker is not None:
        default = getattr(marker, "default", ...)
    else:
        default = param.default

    if default is inspect.Parameter.empty or default is ...:
        return None, False
    if _is_json_safe(default):
        return default, True
    return None, False


def _is_required(param: inspect.Parameter, marker, *, force_required: bool = False) -> bool:
    if force_required:
        return True
    if marker is not None:
        return getattr(marker, "default", ...) is ...
    return param.default is inspect.Parameter.empty


def _build_parameter(
    name: str,
    location: str,
    annotation,
    components: dict[str, Any],
    param: inspect.Parameter,
    marker,
    *,
    required: bool | None = None,
) -> dict[str, Any]:
    schema = _type_to_schema(annotation, components)
    default, has_default = _schema_default(param, marker)
    if has_default:
        schema = dict(schema)
        schema["default"] = default

    return {
        "name": name,
        "in": location,
        "required": _is_required(param, marker, force_required=required is True)
        if required is not None
        else _is_required(param, marker),
        "schema": schema,
    }


def _build_body_item(
    name: str,
    annotation,
    components: dict[str, Any],
    param: inspect.Parameter,
    marker,
    *,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item_schema = dict(schema or _type_to_schema(annotation, components))
    default, has_default = _schema_default(param, marker)
    if has_default:
        item_schema["default"] = default
    return {
        "name": name,
        "annotation": annotation,
        "schema": item_schema,
        "required": _is_required(param, marker),
    }


def _build_object_body_schema(items: list[dict[str, Any]]) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {item["name"]: item["schema"] for item in items},
    }
    required = [item["name"] for item in items if item["required"]]
    if required:
        schema["required"] = required
    return schema


def _build_json_body_schema(
    items: list[dict[str, Any]], components: dict[str, Any]
) -> dict[str, Any]:
    if len(items) == 1 and _is_model_type(items[0]["annotation"]):
        return _type_to_schema(items[0]["annotation"], components)
    return _build_object_body_schema(items)


def _type_to_schema(annotation, components: dict[str, Any] | None = None) -> dict:
    """Convert Python type annotation to OpenAPI schema."""
    annotation, _ = _unwrap_annotated(annotation)
    components = components if components is not None else {}

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
    if annotation is bytes or annotation is UploadFile:
        return {"type": "string", "format": "binary"}

    # Handle typing generics
    origin = get_origin(annotation)
    if origin is list:
        args = get_args(annotation)
        items_schema = _type_to_schema(args[0], components) if args else {}
        return {"type": "array", "items": items_schema}
    if origin is dict:
        return {"type": "object"}

    # Handle Optional[X] / Union[X, None].
    if origin in (Union, types.UnionType):
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            inner = dict(_type_to_schema(non_none[0], components))
            inner["nullable"] = True
            return inner
        return {"nullable": True}
    # Handle bare NoneType annotation
    if annotation is type(None):
        return {"nullable": True}

    # Try to get schema from DHI/Satya/Pydantic-style models.
    try:
        if _is_model_type(annotation):
            name = _register_model_schema(annotation, components)
            return {"$ref": f"#/components/schemas/{name}"}
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
