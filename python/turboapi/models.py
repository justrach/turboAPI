"""
Request and Response models for TurboAPI with Satya integration.
"""

from typing import Dict, Any, Optional, Union
from satya import Model, Field
import json


class TurboRequest(Model):
    """High-performance HTTP Request model powered by Satya."""
    
    method: str = Field(description="HTTP method")
    path: str = Field(description="Request path")
    query_string: str = Field(default="", description="Query string")
    headers: Dict[str, str] = Field(default={}, description="HTTP headers")
    path_params: Dict[str, str] = Field(default={}, description="Path parameters")
    query_params: Dict[str, str] = Field(default={}, description="Query parameters")
    body: Optional[bytes] = Field(default=None, description="Request body")
    
    def get_header(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """Get header value (case-insensitive)."""
        name_lower = name.lower()
        for key, value in self.headers.items():
            if key.lower() == name_lower:
                return value
        return default
    
    def json(self) -> Any:
        """Parse request body as JSON using Satya's fast parsing."""
        if not self.body:
            return None
        # Use Satya's streaming JSON parsing for performance
        return json.loads(self.body.decode('utf-8'))
    
    def validate_json(self, model_class: type) -> Any:
        """Validate JSON body against a Satya model."""
        if not self.body:
            return None
        return model_class.model_validate_json_bytes(self.body, streaming=True)
    
    def text(self) -> str:
        """Get request body as text."""
        return self.body.decode('utf-8') if self.body else ""
    
    @property
    def content_type(self) -> Optional[str]:
        """Get Content-Type header."""
        return self.get_header('content-type')
    
    @property
    def content_length(self) -> int:
        """Get Content-Length."""
        length_str = self.get_header('content-length')
        return int(length_str) if length_str else len(self.body or b"")


# Backward compatibility alias
Request = TurboRequest


class TurboResponse(Model):
    """High-performance HTTP Response model powered by Satya."""
    
    status_code: int = Field(ge=100, le=599, default=200, description="HTTP status code")
    headers: Dict[str, str] = Field(default={}, description="HTTP headers")
    content: Any = Field(default="", description="Response content")
    
    def __init__(self, **data):
        # Handle content serialization before validation
        if 'content' in data:
            content = data['content']
            if isinstance(content, dict):
                # Serialize dict to JSON
                data['content'] = json.dumps(content)
                if 'headers' not in data:
                    data['headers'] = {}
                data['headers']['content-type'] = 'application/json'
            elif isinstance(content, (str, int, float, bool)):
                # Keep as-is, will be converted to string
                pass
            elif isinstance(content, bytes):
                # Convert bytes to string for storage
                data['content'] = content.decode('utf-8')
            else:
                # Convert other types to string
                data['content'] = str(content)
        
        super().__init__(**data)
    
    @property
    def body(self) -> bytes:
        """Get response body as bytes."""
        if isinstance(self.content, str):
            return self.content.encode('utf-8')
        elif isinstance(self.content, bytes):
            return self.content
        else:
            return str(self.content).encode('utf-8')
    
    def set_header(self, name: str, value: str) -> None:
        """Set a response header."""
        self.headers[name] = value
    
    def get_header(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """Get a response header."""
        return self.headers.get(name, default)
    
    @classmethod
    def json(cls, data: Any, status_code: int = 200, headers: Optional[Dict[str, str]] = None):
        """Create a JSON response with automatic serialization."""
        response_headers = headers or {}
        response_headers['content-type'] = 'application/json'
        
        return cls(
            content=data,  # Will be auto-serialized to JSON
            status_code=status_code,
            headers=response_headers
        )
    
    @classmethod
    def text(cls, content: str, status_code: int = 200, headers: Optional[Dict[str, str]] = None):
        """Create a text response."""
        response_headers = headers or {}
        response_headers['content-type'] = 'text/plain; charset=utf-8'
        
        return cls(
            content=content,
            status_code=status_code,
            headers=response_headers
        )
    
    @classmethod
    def html(cls, content: str, status_code: int = 200, headers: Optional[Dict[str, str]] = None):
        """Create an HTML response."""
        response_headers = headers or {}
        response_headers['content-type'] = 'text/html; charset=utf-8'
        
        return cls(
            content=content,
            status_code=status_code,
            headers=response_headers
        )


# Backward compatibility alias
Response = TurboResponse
