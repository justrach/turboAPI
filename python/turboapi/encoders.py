"""
JSON encoding utilities (FastAPI-compatible).

This module provides the jsonable_encoder function for converting
objects to JSON-serializable dictionaries.
"""

import dataclasses
from collections import deque
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path, PurePath
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union
from uuid import UUID

# Try to import dhi BaseModel
try:
    from dhi import BaseModel

    HAS_DHI = True
except ImportError:
    BaseModel = None
    HAS_DHI = False

# Try to import Pydantic for compatibility
try:
    import pydantic

    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False


ENCODERS_BY_TYPE: Dict[Type[Any], Callable[[Any], Any]] = {
    bytes: lambda o: o.decode(),
    date: lambda o: o.isoformat(),
    datetime: lambda o: o.isoformat(),
    time: lambda o: o.isoformat(),
    timedelta: lambda o: o.total_seconds(),
    Decimal: float,
    Enum: lambda o: o.value,
    frozenset: list,
    deque: list,
    set: list,
    Path: str,
    PurePath: str,
    UUID: str,
}


def jsonable_encoder(
    obj: Any,
    include: Optional[Set[str]] = None,
    exclude: Optional[Set[str]] = None,
    by_alias: bool = True,
    exclude_unset: bool = False,
    exclude_defaults: bool = False,
    exclude_none: bool = False,
    custom_encoder: Optional[Dict[Any, Callable[[Any], Any]]] = None,
    sqlalchemy_safe: bool = True,
) -> Any:
    """
    Convert any object to a JSON-serializable value (FastAPI-compatible).

    This function is useful for converting complex objects (like Pydantic/dhi models,
    dataclasses, etc.) to dictionaries that can be serialized to JSON.

    Args:
        obj: The object to convert
        include: Set of field names to include (all if None)
        exclude: Set of field names to exclude
        by_alias: Use field aliases if available
        exclude_unset: Exclude fields that were not explicitly set
        exclude_defaults: Exclude fields with default values
        exclude_none: Exclude fields with None values
        custom_encoder: Custom encoders for specific types
        sqlalchemy_safe: If True, avoid encoding SQLAlchemy lazy-loaded attributes

    Returns:
        JSON-serializable value

    Usage:
        from turboapi.encoders import jsonable_encoder
        from turboapi import BaseModel

        class User(BaseModel):
            name: str
            created_at: datetime

        user = User(name="Alice", created_at=datetime.now())
        json_data = jsonable_encoder(user)
        # {"name": "Alice", "created_at": "2024-01-01T12:00:00"}
    """
    custom_encoder = custom_encoder or {}
    exclude = exclude or set()

    # Handle None
    if obj is None:
        return None

    # Handle dhi BaseModel
    if HAS_DHI and BaseModel is not None and isinstance(obj, BaseModel):
        return _encode_model(
            obj,
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            custom_encoder=custom_encoder,
        )

    # Handle Pydantic models
    if HAS_PYDANTIC:
        if hasattr(pydantic, "BaseModel") and isinstance(obj, pydantic.BaseModel):
            return _encode_pydantic(
                obj,
                include=include,
                exclude=exclude,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
                custom_encoder=custom_encoder,
            )

    # Handle dataclasses
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _encode_dataclass(
            obj,
            include=include,
            exclude=exclude,
            exclude_none=exclude_none,
            custom_encoder=custom_encoder,
        )

    # Handle custom encoders
    if type(obj) in custom_encoder:
        return custom_encoder[type(obj)](obj)

    # Handle built-in encoders
    if type(obj) in ENCODERS_BY_TYPE:
        return ENCODERS_BY_TYPE[type(obj)](obj)

    # Handle dicts
    if isinstance(obj, dict):
        return {
            jsonable_encoder(
                key,
                custom_encoder=custom_encoder,
            ): jsonable_encoder(
                value,
                include=include,
                exclude=exclude,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
                custom_encoder=custom_encoder,
            )
            for key, value in obj.items()
            if not (exclude_none and value is None)
        }

    # Handle lists, tuples, sets, frozensets
    if isinstance(obj, (list, tuple, set, frozenset, deque)):
        return [
            jsonable_encoder(
                item,
                include=include,
                exclude=exclude,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
                custom_encoder=custom_encoder,
            )
            for item in obj
        ]

    # Handle Enum
    if isinstance(obj, Enum):
        return obj.value

    # Handle primitives
    if isinstance(obj, (str, int, float, bool)):
        return obj

    # Handle objects with __dict__
    if hasattr(obj, "__dict__"):
        data = {}
        for key, value in obj.__dict__.items():
            if key.startswith("_"):
                continue
            if sqlalchemy_safe and key.startswith("_sa_"):
                continue
            if exclude and key in exclude:
                continue
            if include is not None and key not in include:
                continue
            if exclude_none and value is None:
                continue
            data[key] = jsonable_encoder(
                value,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
                custom_encoder=custom_encoder,
            )
        return data

    # Fallback: try to convert to string
    try:
        return str(obj)
    except Exception:
        return repr(obj)


def _encode_model(
    obj: Any,
    include: Optional[Set[str]],
    exclude: Set[str],
    by_alias: bool,
    exclude_unset: bool,
    exclude_defaults: bool,
    exclude_none: bool,
    custom_encoder: Dict[Any, Callable[[Any], Any]],
) -> Dict[str, Any]:
    """Encode a dhi BaseModel to a dict."""
    # Use model_dump if available
    if hasattr(obj, "model_dump"):
        # Try with full parameters (Pydantic v2 style)
        try:
            data = obj.model_dump(
                include=include,
                exclude=exclude,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
            )
        except TypeError:
            # Fallback for dhi or simpler model_dump implementations
            data = obj.model_dump()
    else:
        # Fallback to dict() or __dict__
        data = dict(obj) if hasattr(obj, "__iter__") else vars(obj).copy()

    # Apply include/exclude filters manually if needed
    if include is not None:
        data = {k: v for k, v in data.items() if k in include}

    # Recursively encode nested values
    return {
        key: jsonable_encoder(value, custom_encoder=custom_encoder)
        for key, value in data.items()
        if key not in exclude and not (exclude_none and value is None)
    }


def _encode_pydantic(
    obj: Any,
    include: Optional[Set[str]],
    exclude: Set[str],
    by_alias: bool,
    exclude_unset: bool,
    exclude_defaults: bool,
    exclude_none: bool,
    custom_encoder: Dict[Any, Callable[[Any], Any]],
) -> Dict[str, Any]:
    """Encode a Pydantic model to a dict."""
    # Pydantic v2
    if hasattr(obj, "model_dump"):
        data = obj.model_dump(
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
        )
    # Pydantic v1
    elif hasattr(obj, "dict"):
        data = obj.dict(
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
        )
    else:
        data = vars(obj).copy()

    # Recursively encode nested values
    return {
        key: jsonable_encoder(value, custom_encoder=custom_encoder)
        for key, value in data.items()
    }


def _encode_dataclass(
    obj: Any,
    include: Optional[Set[str]],
    exclude: Set[str],
    exclude_none: bool,
    custom_encoder: Dict[Any, Callable[[Any], Any]],
) -> Dict[str, Any]:
    """Encode a dataclass to a dict."""
    data = dataclasses.asdict(obj)
    return {
        key: jsonable_encoder(value, custom_encoder=custom_encoder)
        for key, value in data.items()
        if key not in exclude
        and (include is None or key in include)
        and not (exclude_none and value is None)
    }


__all__ = ["jsonable_encoder", "ENCODERS_BY_TYPE"]
