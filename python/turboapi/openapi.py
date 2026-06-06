"""OpenAPI schema generation and Swagger/ReDoc UI for TurboAPI.

Generates OpenAPI 3.1.0 compatible schemas from route definitions and serves
interactive API documentation at /docs (Swagger UI) and /redoc (ReDoc).
"""

import copy
import inspect
import json
import re
import types
from typing import Annotated, Any, Union, get_args, get_origin

from .datastructures import (
    Body,
    Cookie,
    File,
    Form,
    Header,
    Path as PathMarker,
    Query,
    UploadFile,
)
from .security import Depends, SecurityBase, get_depends

_BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_PARAM_MARKER_TYPES = (Body, Cookie, File, Form, Header, PathMarker, Query)

_VALIDATION_ERROR_SCHEMAS = {
    "ValidationError": {
        "title": "ValidationError",
        "type": "object",
        "properties": {
            "loc": {
                "title": "Location",
                "type": "array",
                "items": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
            },
            "msg": {"title": "Message", "type": "string"},
            "type": {"title": "Error Type", "type": "string"},
        },
        "required": ["loc", "msg", "type"],
    },
    "HTTPValidationError": {
        "title": "HTTPValidationError",
        "type": "object",
        "properties": {
            "detail": {
                "title": "Detail",
                "type": "array",
                "items": {"$ref": "#/components/schemas/ValidationError"},
            }
        },
    },
}


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
        "components": {"schemas": copy.deepcopy(_VALIDATION_ERROR_SCHEMAS)},
    }
    components = schema["components"]["schemas"]

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
    response_schema = {}
    response_model = getattr(route, "response_model", None)
    if response_model is not None:
        response_schema = _type_to_schema(response_model, components)

    operation: dict[str, Any] = {
        "summary": _get_summary(handler),
        "operationId": f"{route.method.value.lower()}_{handler.__name__}",
        "responses": {
            "200": {
                "description": "Successful Response",
                "content": {"application/json": {"schema": response_schema}},
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

    sig = inspect.signature(handler)
    parameters = []
    body_entries: list[dict[str, Any]] = []
    path_params = set(re.findall(r"\{([^}]+)\}", route.path))
    method = route.method.value.upper()

    for param_name, param in sig.parameters.items():
        if _is_dependency_parameter(param):
            continue

        annotation, marker = _resolve_annotation_and_marker(param)
        param_schema = _schema_for_param(annotation, marker, param, components)
        required = _is_required_param(param, marker)

        if param_name in path_params or isinstance(marker, PathMarker):
            parameters.append(_build_parameter(param_name, "path", True, param_schema, marker))
        elif isinstance(marker, Query):
            parameters.append(
                _build_parameter(
                    _parameter_alias(param_name, marker),
                    "query",
                    required,
                    param_schema,
                    marker,
                )
            )
        elif isinstance(marker, Header):
            parameters.append(
                _build_parameter(
                    _parameter_alias(param_name, marker, location="header"),
                    "header",
                    required,
                    param_schema,
                    marker,
                )
            )
        elif isinstance(marker, Cookie):
            parameters.append(
                _build_parameter(
                    _parameter_alias(param_name, marker, location="cookie"),
                    "cookie",
                    required,
                    param_schema,
                    marker,
                )
            )
        elif _is_form_or_file_param(annotation, marker):
            media_type = getattr(marker, "media_type", None) or "multipart/form-data"
            if _is_file_param(annotation, marker):
                media_type = "multipart/form-data"
            body_entries.append(
                {
                    "name": _parameter_alias(param_name, marker),
                    "schema": param_schema,
                    "required": required,
                    "media_type": media_type,
                    "direct": False,
                }
            )
        elif isinstance(marker, Body):
            body_entries.append(
                {
                    "name": _parameter_alias(param_name, marker),
                    "schema": param_schema,
                    "required": required,
                    "media_type": marker.media_type,
                    "direct": _is_model_class(annotation) and not marker.embed,
                }
            )
        elif method in _BODY_METHODS and _is_model_class(annotation):
            body_entries.append(
                {
                    "name": param_name,
                    "schema": param_schema,
                    "required": required,
                    "media_type": "application/json",
                    "direct": True,
                }
            )
        elif method in _BODY_METHODS:
            body_entries.append(
                {
                    "name": param_name,
                    "schema": param_schema,
                    "required": required,
                    "media_type": "application/json",
                    "direct": False,
                }
            )
        else:
            parameters.append(
                _build_parameter(param_name, "query", required, param_schema, marker)
            )

    if parameters:
        operation["parameters"] = parameters

    if body_entries:
        operation["requestBody"] = _build_request_body(body_entries)

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


def _type_to_schema(annotation, components: dict[str, Any] | None = None) -> dict:
    """Convert Python type annotation to OpenAPI schema."""
    annotation, _metadata = _unwrap_annotated(annotation)

    if annotation is inspect.Parameter.empty or annotation is Any:
        return {}
    if annotation is type(None):
        return {"type": "null"}
    if _is_model_class(annotation):
        return _register_model_schema(annotation, components)
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
    if _is_upload_file_type(annotation):
        return {"type": "string", "format": "binary"}

    origin = get_origin(annotation)
    if origin in (list, tuple, set, frozenset):
        args = get_args(annotation)
        items_schema = _type_to_schema(args[0], components) if args else {}
        return {"type": "array", "items": items_schema}
    if origin is dict:
        args = get_args(annotation)
        schema = {"type": "object"}
        if len(args) == 2:
            schema["additionalProperties"] = _type_to_schema(args[1], components)
        return schema

    if _is_union_type(annotation):
        args = get_args(annotation)
        schemas = [_type_to_schema(arg, components) for arg in args]
        if len(schemas) == 1:
            return schemas[0]
        return {"anyOf": schemas}

    if inspect.isclass(annotation):
        return {"type": "object"}

    return {}


def _unwrap_annotated(annotation) -> tuple[Any, tuple[Any, ...]]:
    """Return the underlying annotation plus all Annotated metadata."""
    metadata: list[Any] = []
    while get_origin(annotation) is Annotated:
        args = get_args(annotation)
        if not args:
            break
        annotation = args[0]
        metadata.extend(args[1:])
    return annotation, tuple(metadata)


def _resolve_annotation_and_marker(param: inspect.Parameter) -> tuple[Any, Any | None]:
    annotation, metadata = _unwrap_annotated(param.annotation)

    for item in metadata:
        if isinstance(item, _PARAM_MARKER_TYPES):
            return annotation, item

    if isinstance(param.default, _PARAM_MARKER_TYPES):
        return annotation, param.default

    return annotation, None


def _is_dependency_parameter(param: inspect.Parameter) -> bool:
    if isinstance(param.default, (Depends, SecurityBase)):
        return True
    return get_depends(param) is not None


def _is_required_param(param: inspect.Parameter, marker: Any | None) -> bool:
    default = _effective_default(param, marker)
    return default is inspect.Parameter.empty or default is ...


def _effective_default(param: inspect.Parameter, marker: Any | None) -> Any:
    if isinstance(param.default, _PARAM_MARKER_TYPES):
        return param.default.default
    if param.default is not inspect.Parameter.empty:
        return param.default
    if marker is not None and hasattr(marker, "default"):
        return marker.default
    return inspect.Parameter.empty


def _schema_for_param(
    annotation, marker: Any | None, param: inspect.Parameter, components: dict[str, Any]
) -> dict:
    if _is_file_param(annotation, marker):
        schema = {"type": "string", "format": "binary"}
    else:
        schema = _type_to_schema(annotation, components)

    schema = dict(schema)
    _apply_marker_metadata(schema, marker)

    default = _effective_default(param, marker)
    if default is not inspect.Parameter.empty and default is not ... and _is_jsonable(default):
        schema["default"] = default

    return schema


def _apply_marker_metadata(schema: dict[str, Any], marker: Any | None) -> None:
    if marker is None:
        return

    for attr, openapi_name in (
        ("title", "title"),
        ("description", "description"),
        ("min_length", "minLength"),
        ("max_length", "maxLength"),
        ("regex", "pattern"),
        ("gt", "exclusiveMinimum"),
        ("ge", "minimum"),
        ("lt", "exclusiveMaximum"),
        ("le", "maximum"),
    ):
        value = getattr(marker, attr, None)
        if value is not None:
            schema[openapi_name] = value


def _build_parameter(
    name: str, location: str, required: bool, schema: dict[str, Any], marker: Any | None
) -> dict[str, Any]:
    parameter = {
        "name": name,
        "in": location,
        "required": True if location == "path" else required,
        "schema": schema,
    }
    description = getattr(marker, "description", None)
    if description:
        parameter["description"] = description
    return parameter


def _build_request_body(body_entries: list[dict[str, Any]]) -> dict[str, Any]:
    if any(entry["media_type"] == "multipart/form-data" for entry in body_entries):
        for entry in body_entries:
            entry["media_type"] = "multipart/form-data"

    content: dict[str, Any] = {}
    media_types = sorted({entry["media_type"] for entry in body_entries})
    for media_type in media_types:
        entries = [entry for entry in body_entries if entry["media_type"] == media_type]
        if len(entries) == 1 and entries[0]["direct"]:
            body_schema = entries[0]["schema"]
        else:
            body_schema = {
                "type": "object",
                "properties": {entry["name"]: entry["schema"] for entry in entries},
            }
            required = [entry["name"] for entry in entries if entry["required"]]
            if required:
                body_schema["required"] = required
        content[media_type] = {"schema": body_schema}

    return {"required": any(entry["required"] for entry in body_entries), "content": content}


def _parameter_alias(param_name: str, marker: Any | None, *, location: str | None = None) -> str:
    alias = getattr(marker, "alias", None)
    if alias:
        return alias
    if location == "header" and getattr(marker, "convert_underscores", True):
        return param_name.replace("_", "-")
    return param_name


def _is_form_or_file_param(annotation, marker: Any | None) -> bool:
    return isinstance(marker, (Form, File)) or _is_upload_file_type(annotation)


def _is_file_param(annotation, marker: Any | None) -> bool:
    return isinstance(marker, File) or _is_upload_file_type(annotation)


def _is_upload_file_type(annotation) -> bool:
    try:
        return inspect.isclass(annotation) and issubclass(annotation, UploadFile)
    except TypeError:
        return False


def _is_union_type(annotation) -> bool:
    origin = get_origin(annotation)
    return origin is Union or origin is types.UnionType or isinstance(annotation, types.UnionType)


def _is_model_class(annotation) -> bool:
    try:
        return inspect.isclass(annotation) and (
            hasattr(annotation, "model_json_schema")
            or hasattr(annotation, "schema")
            or hasattr(annotation, "model_fields")
            or hasattr(annotation, "__fields__")
        )
    except TypeError:
        return False


def _register_model_schema(model_class, components: dict[str, Any] | None) -> dict[str, str]:
    name = getattr(model_class, "__name__", "Model")
    if components is not None and name not in components:
        components[name] = {}
        model_schema = _model_to_schema(model_class, components)
        components[name].update(model_schema)
    return {"$ref": f"#/components/schemas/{name}"}


def _model_to_schema(model_class, components: dict[str, Any] | None) -> dict[str, Any]:
    schema: dict[str, Any] | None = None

    if hasattr(model_class, "model_json_schema"):
        try:
            schema = model_class.model_json_schema(ref_template="#/components/schemas/{model}")
        except TypeError:
            schema = model_class.model_json_schema()
        except Exception:
            schema = None
    elif hasattr(model_class, "schema"):
        try:
            schema = model_class.schema(ref_template="#/components/schemas/{model}")
        except TypeError:
            schema = model_class.schema()
        except Exception:
            schema = None

    if not isinstance(schema, dict):
        schema = _schema_from_annotations(model_class, components)

    schema = copy.deepcopy(schema)
    _move_defs_to_components(schema, components)
    _rewrite_component_refs(schema)
    return schema


def _schema_from_annotations(model_class, components: dict[str, Any] | None) -> dict[str, Any]:
    properties = {}
    required = []
    annotations = getattr(model_class, "__annotations__", {})
    fields = getattr(model_class, "model_fields", getattr(model_class, "__fields__", {}))

    for field_name, annotation in annotations.items():
        properties[field_name] = _type_to_schema(annotation, components)
        if _model_field_is_required(model_class, field_name, fields):
            required.append(field_name)

    schema: dict[str, Any] = {
        "title": getattr(model_class, "__name__", "Model"),
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def _model_field_is_required(model_class, field_name: str, fields: Any) -> bool:
    if isinstance(fields, dict) and field_name in fields:
        field = fields[field_name]
        is_required = getattr(field, "is_required", None)
        if callable(is_required):
            return bool(is_required())
        if isinstance(is_required, bool):
            return is_required
        default = getattr(field, "default", inspect.Parameter.empty)
        return default is inspect.Parameter.empty or default is ...
    return not hasattr(model_class, field_name)


def _move_defs_to_components(schema: dict[str, Any], components: dict[str, Any] | None) -> None:
    if components is None:
        return
    for defs_key in ("$defs", "definitions"):
        defs = schema.pop(defs_key, None)
        if isinstance(defs, dict):
            for name, value in defs.items():
                _rewrite_component_refs(value)
                components.setdefault(name, value)


def _rewrite_component_refs(value: Any) -> None:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            if ref.startswith("#/$defs/"):
                value["$ref"] = "#/components/schemas/" + ref.rsplit("/", 1)[-1]
            elif ref.startswith("#/definitions/"):
                value["$ref"] = "#/components/schemas/" + ref.rsplit("/", 1)[-1]
        for item in value.values():
            _rewrite_component_refs(item)
    elif isinstance(value, list):
        for item in value:
            _rewrite_component_refs(item)


def _is_jsonable(value: Any) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


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
