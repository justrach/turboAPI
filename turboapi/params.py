"""
Parameters module for TurboAPI.

This module defines various parameter types that can be used
to define API endpoints with proper validation using satya.
"""

from typing import Any, Callable, Dict, List, Optional, Union, Type


class Param:
    """Base class for all parameter types."""
    
    def __init__(
        self,
        *,
        default: Any = ...,
        gt: Optional[float] = None,
        ge: Optional[float] = None,
        lt: Optional[float] = None,
        le: Optional[float] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        regex: Optional[str] = None,
        description: Optional[str] = None,
        title: Optional[str] = None,
        example: Any = None,
        examples: Optional[Dict[str, Any]] = None,
        deprecated: Optional[bool] = None,
    ):
        """Initialize the parameter."""
        self.default = default
        self.gt = gt
        self.ge = ge
        self.lt = lt
        self.le = le
        self.min_length = min_length
        self.max_length = max_length
        self.regex = regex
        self.description = description
        self.title = title
        self.example = example
        self.examples = examples
        self.deprecated = deprecated
        self.required = default is ...


class Path(Param):
    """Defines a path parameter."""
    
    def __init__(
        self,
        default: Any = ...,
        *,
        gt: Optional[float] = None,
        ge: Optional[float] = None,
        lt: Optional[float] = None,
        le: Optional[float] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        regex: Optional[str] = None,
        description: Optional[str] = None,
        title: Optional[str] = None,
        example: Any = None,
        examples: Optional[Dict[str, Any]] = None,
        deprecated: Optional[bool] = None,
    ):
        """Initialize the path parameter."""
        super().__init__(
            default=default,
            gt=gt,
            ge=ge,
            lt=lt,
            le=le,
            min_length=min_length,
            max_length=max_length,
            regex=regex,
            description=description,
            title=title,
            example=example,
            examples=examples,
            deprecated=deprecated,
        )


class Query(Param):
    """Defines a query parameter."""
    
    def __init__(
        self,
        default: Any = ...,
        *,
        gt: Optional[float] = None,
        ge: Optional[float] = None,
        lt: Optional[float] = None,
        le: Optional[float] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        regex: Optional[str] = None,
        description: Optional[str] = None,
        title: Optional[str] = None,
        example: Any = None,
        examples: Optional[Dict[str, Any]] = None,
        deprecated: Optional[bool] = None,
    ):
        """Initialize the query parameter."""
        super().__init__(
            default=default,
            gt=gt,
            ge=ge,
            lt=lt,
            le=le,
            min_length=min_length,
            max_length=max_length,
            regex=regex,
            description=description,
            title=title,
            example=example,
            examples=examples,
            deprecated=deprecated,
        )


class Header(Param):
    """Defines a header parameter."""
    
    def __init__(
        self,
        default: Any = ...,
        *,
        gt: Optional[float] = None,
        ge: Optional[float] = None,
        lt: Optional[float] = None,
        le: Optional[float] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        regex: Optional[str] = None,
        description: Optional[str] = None,
        title: Optional[str] = None,
        example: Any = None,
        examples: Optional[Dict[str, Any]] = None,
        deprecated: Optional[bool] = None,
        convert_underscores: bool = True,
    ):
        """Initialize the header parameter."""
        super().__init__(
            default=default,
            gt=gt,
            ge=ge,
            lt=lt,
            le=le,
            min_length=min_length,
            max_length=max_length,
            regex=regex,
            description=description,
            title=title,
            example=example,
            examples=examples,
            deprecated=deprecated,
        )
        self.convert_underscores = convert_underscores


class Cookie(Param):
    """Defines a cookie parameter."""
    
    def __init__(
        self,
        default: Any = ...,
        *,
        gt: Optional[float] = None,
        ge: Optional[float] = None,
        lt: Optional[float] = None,
        le: Optional[float] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        regex: Optional[str] = None,
        description: Optional[str] = None,
        title: Optional[str] = None,
        example: Any = None,
        examples: Optional[Dict[str, Any]] = None,
        deprecated: Optional[bool] = None,
    ):
        """Initialize the cookie parameter."""
        super().__init__(
            default=default,
            gt=gt,
            ge=ge,
            lt=lt,
            le=le,
            min_length=min_length,
            max_length=max_length,
            regex=regex,
            description=description,
            title=title,
            example=example,
            examples=examples,
            deprecated=deprecated,
        )


class Body(Param):
    """Defines a request body parameter."""
    
    def __init__(
        self,
        default: Any = ...,
        *,
        embed: bool = False,
        media_type: str = "application/json",
        description: Optional[str] = None,
        title: Optional[str] = None,
        example: Any = None,
        examples: Optional[Dict[str, Any]] = None,
        deprecated: Optional[bool] = None,
    ):
        """Initialize the body parameter."""
        super().__init__(
            default=default,
            description=description,
            title=title,
            example=example,
            examples=examples,
            deprecated=deprecated,
        )
        self.embed = embed
        self.media_type = media_type


class Depends:
    """
    Defines a dependency.
    
    Dependencies are used to inject values into route handlers.
    """
    
    def __init__(self, dependency: Optional[Callable] = None, *, use_cache: bool = True):
        """Initialize the dependency."""
        self.dependency = dependency
        self.use_cache = use_cache


class Security(Depends):
    """
    Defines a security dependency.
    
    Security dependencies are used to enforce security requirements
    for route handlers.
    """
    
    def __init__(
        self,
        dependency: Optional[Callable] = None,
        *,
        scopes: Optional[List[str]] = None,
        use_cache: bool = True,
    ):
        """Initialize the security dependency."""
        super().__init__(dependency=dependency, use_cache=use_cache)
        self.scopes = scopes or []
