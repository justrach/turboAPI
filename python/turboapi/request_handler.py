"""
Enhanced Request Handler with Satya Integration
Provides FastAPI-compatible automatic JSON body parsing and validation
"""

import inspect
import json
from typing import Any, get_args, get_origin

from satya import Model


class RequestBodyParser:
    """Parse and validate request bodies using Satya models."""
    
    @staticmethod
    def parse_json_body(body: bytes, handler_signature: inspect.Signature) -> dict[str, Any]:
        """
        Parse JSON body and extract parameters for handler.
        
        Args:
            body: Raw request body bytes
            handler_signature: Signature of the handler function
            
        Returns:
            Dictionary of parsed parameters ready for handler
        """
        if not body:
            return {}
            
        try:
            json_data = json.loads(body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid JSON body: {e}")
        
        parsed_params = {}
        
        # Check each parameter in the handler signature
        for param_name, param in handler_signature.parameters.items():
            if param.annotation == inspect.Parameter.empty:
                # No type annotation, try to match by name
                if param_name in json_data:
                    parsed_params[param_name] = json_data[param_name]
                continue
            
            # Check if parameter is a Satya Model
            try:
                is_satya_model = inspect.isclass(param.annotation) and issubclass(param.annotation, Model)
            except Exception:
                is_satya_model = False
            
            if is_satya_model:
                # Validate entire JSON body against Satya model
                try:
                    validated_model = param.annotation.model_validate(json_data)
                    parsed_params[param_name] = validated_model
                except Exception as e:
                    raise ValueError(f"Validation error for {param_name}: {e}")
            
            # Check if parameter name exists in JSON data
            elif param_name in json_data:
                value = json_data[param_name]
                
                # Type conversion for basic types
                if param.annotation in (int, float, str, bool):
                    try:
                        if param.annotation is bool and isinstance(value, str):
                            parsed_params[param_name] = value.lower() in ('true', '1', 'yes', 'on')
                        else:
                            parsed_params[param_name] = param.annotation(value)
                    except (ValueError, TypeError) as e:
                        raise ValueError(f"Invalid type for {param_name}: {e}")
                else:
                    # Use value as-is for other types (lists, dicts, etc.)
                    parsed_params[param_name] = value
            
            # Handle default values
            elif param.default != inspect.Parameter.empty:
                parsed_params[param_name] = param.default
        
        return parsed_params


class ResponseHandler:
    """Handle different response formats including FastAPI-style tuples."""
    
    @staticmethod
    def normalize_response(result: Any) -> tuple[Any, int]:
        """
        Normalize handler response to (content, status_code) format.
        
        Supports:
        - return {"data": "value"}  -> ({"data": "value"}, 200)
        - return {"error": "msg"}, 404  -> ({"error": "msg"}, 404)
        - return "text"  -> ("text", 200)
        - return satya_model  -> (model.model_dump(), 200)
        
        Args:
            result: Raw result from handler
            
        Returns:
            Tuple of (content, status_code)
        """
        # Handle tuple returns: (content, status_code)
        if isinstance(result, tuple):
            if len(result) == 2:
                content, status_code = result
                return content, status_code
            else:
                # Invalid tuple format, treat as regular response
                return result, 200
        
        # Handle Satya models
        if isinstance(result, Model):
            return result.model_dump(), 200
        
        # Handle dict with status_code key (internal format)
        if isinstance(result, dict) and "status_code" in result:
            status = result.pop("status_code")
            return result, status
        
        # Default: treat as 200 OK response
        return result, 200
    
    @staticmethod
    def format_json_response(content: Any, status_code: int) -> dict[str, Any]:
        """
        Format content as JSON response.
        
        Args:
            content: Response content
            status_code: HTTP status code
            
        Returns:
            Dictionary with properly formatted response
        """
        # Handle Satya models
        if isinstance(content, Model):
            content = content.model_dump()
        
        # Ensure content is JSON-serializable
        if not isinstance(content, (dict, list, str, int, float, bool, type(None))):
            content = str(content)
        
        return {
            "content": content,
            "status_code": status_code,
            "content_type": "application/json"
        }


def create_enhanced_handler(original_handler, route_definition):
    """
    Create an enhanced handler with automatic body parsing and response normalization.
    
    This wrapper:
    1. Parses JSON body automatically using Satya validation
    2. Normalizes responses (supports tuple returns)
    3. Provides better error messages
    
    Args:
        original_handler: The original Python handler function
        route_definition: RouteDefinition with metadata
        
    Returns:
        Enhanced handler function
    """
    sig = inspect.signature(original_handler)
    
    def enhanced_handler(**kwargs):
        """Enhanced handler with automatic body parsing."""
        try:
            # If there's a body in kwargs, parse it
            if "body" in kwargs:
                body_data = kwargs["body"]
                
                if body_data:  # Only parse if body is not empty
                    parsed_body = RequestBodyParser.parse_json_body(
                        body_data, 
                        sig
                    )
                    # Merge parsed body params into kwargs
                    kwargs.update(parsed_body)
                
                # Remove the raw body to avoid passing it to handler
                kwargs.pop("body", None)
            
            # Remove headers if present
            kwargs.pop("headers", None)
            
            # Filter kwargs to only pass expected parameters
            filtered_kwargs = {
                k: v for k, v in kwargs.items() 
                if k in sig.parameters
            }
            
            # Call original handler
            if inspect.iscoroutinefunction(original_handler):
                # For async handlers (future support)
                result = original_handler(**filtered_kwargs)
            else:
                result = original_handler(**filtered_kwargs)
            
            # Normalize response
            content, status_code = ResponseHandler.normalize_response(result)
            
            return ResponseHandler.format_json_response(content, status_code)
            
        except ValueError as e:
            # Validation or parsing error (400 Bad Request)
            return ResponseHandler.format_json_response(
                {"error": "Bad Request", "detail": str(e)},
                400
            )
        except Exception as e:
            # Unexpected error (500 Internal Server Error)
            import traceback
            return ResponseHandler.format_json_response(
                {
                    "error": "Internal Server Error",
                    "detail": str(e),
                    "traceback": traceback.format_exc()
                },
                500
            )
    
    return enhanced_handler
