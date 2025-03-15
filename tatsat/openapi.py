"""
OpenAPI schema generator for Tatsat.

This module handles OpenAPI schema generation for automatic documentation.
"""

from typing import Any, Dict, List, Optional, Union

class OpenAPIGenerator:
    """
    Generator for OpenAPI schema.
    
    This class generates OpenAPI schema documents for Tatsat applications,
    enabling automatic API documentation via Swagger UI and ReDoc.
    """
    
    def __init__(
        self,
        title: str = "Tatsat API",
        description: str = "",
        version: str = "0.1.0",
        openapi_url: str = "/openapi.json",
        terms_of_service: Optional[str] = None,
        contact: Optional[Dict[str, str]] = None,
        license_info: Optional[Dict[str, str]] = None,
    ):
        """Initialize the OpenAPI generator."""
        self.title = title
        self.description = description
        self.version = version
        self.openapi_url = openapi_url
        self.terms_of_service = terms_of_service
        self.contact = contact
        self.license_info = license_info
        self.routes = []
    
    def get_openapi_schema(self) -> Dict[str, Any]:
        """
        Generate the OpenAPI schema.
        
        This method generates a complete OpenAPI schema document based on the
        routes and metadata of the Tatsat application.
        """
        openapi_schema = {
            "openapi": "3.0.2",
            "info": {
                "title": self.title,
                "description": self.description,
                "version": self.version,
            },
            "paths": {},
            "components": {
                "schemas": {},
                "securitySchemes": {},
            },
        }
        
        # Add additional info fields if provided
        if self.terms_of_service:
            openapi_schema["info"]["termsOfService"] = self.terms_of_service
        
        if self.contact:
            openapi_schema["info"]["contact"] = self.contact
        
        if self.license_info:
            openapi_schema["info"]["license"] = self.license_info
        
        # Generate paths from the routes
        for route in self.routes:
            if hasattr(route, "include_in_schema") and not route.include_in_schema:
                continue
            
            # Generate path item
            path_item = self._generate_path_item(route)
            
            # Add path item to the schema
            if path_item and route.path not in openapi_schema["paths"]:
                openapi_schema["paths"][route.path] = path_item
            elif path_item:
                # Merge with existing path item
                for method, operation in path_item.items():
                    openapi_schema["paths"][route.path][method] = operation
        
        return openapi_schema
    
    def _generate_path_item(self, route) -> Dict[str, Any]:
        """Generate a path item for the OpenAPI schema."""
        if not hasattr(route, "methods") or not route.methods:
            return {}
        
        path_item = {}
        
        for method in route.methods:
            if method == "HEAD":
                # Skip HEAD methods as they're typically not documented
                continue
            
            operation = self._generate_operation(route, method)
            path_item[method.lower()] = operation
        
        return path_item
    
    def _generate_operation(self, route, method: str) -> Dict[str, Any]:
        """Generate an operation object for the OpenAPI schema."""
        operation = {
            "summary": getattr(route, "summary", ""),
            "operationId": getattr(route, "operation_id", "") or f"{method.lower()}_{route.path}",
            "responses": {
                str(getattr(route, "status_code", 200)): {
                    "description": getattr(route, "response_description", "Successful Response"),
                }
            },
        }
        
        # Add description if available
        if hasattr(route, "description") and route.description:
            operation["description"] = route.description
        
        # Add tags if available
        if hasattr(route, "tags") and route.tags:
            operation["tags"] = route.tags
        
        # Add deprecated flag if available
        if hasattr(route, "deprecated") and route.deprecated:
            operation["deprecated"] = True
        
        # Add request body if this is a method that typically has a body
        if method in ["POST", "PUT", "PATCH"]:
            request_body = self._generate_request_body(route)
            if request_body:
                operation["requestBody"] = request_body
        
        # Add parameters (path, query, header, cookie)
        parameters = self._generate_parameters(route)
        if parameters:
            operation["parameters"] = parameters
        
        # Add response schema if available
        if hasattr(route, "response_model") and route.response_model:
            schema = self._generate_schema_from_model(route.response_model)
            operation["responses"][str(getattr(route, "status_code", 200))]["content"] = {
                "application/json": {
                    "schema": schema
                }
            }
        
        return operation
    
    def _generate_request_body(self, route) -> Dict[str, Any]:
        """Generate a request body object for the OpenAPI schema."""
        # In a real implementation, this would extract the request body
        # schema from the route handler's signature and parameters
        # For now, we'll return a placeholder
        return {
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object"
                    }
                }
            },
            "required": True
        }
    
    def _generate_parameters(self, route) -> List[Dict[str, Any]]:
        """Generate parameter objects for the OpenAPI schema."""
        # In a real implementation, this would extract path, query, 
        # header, and cookie parameters from the route's signature
        # For now, we'll extract just path parameters from the route path
        parameters = []
        
        # Extract path parameters
        path_params = [segment.strip("{}") for segment in route.path.split("/") if segment.startswith("{") and segment.endswith("}")]
        for param in path_params:
            parameters.append({
                "name": param,
                "in": "path",
                "required": True,
                "schema": {
                    "type": "string"
                }
            })
        
        return parameters
    
    def _generate_schema_from_model(self, model) -> Dict[str, Any]:
        """Generate a schema object from a satya model."""
        # In a real implementation, this would inspect the satya model
        # to generate an appropriate JSON Schema
        # For now, we'll return a placeholder
        return {
            "type": "object"
        }
    
    @staticmethod
    def get_swagger_ui_html(openapi_url: str, title: str) -> str:
        """Generate HTML for Swagger UI."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{title}</title>
            <meta charset="utf-8"/>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
        </head>
        <body>
            <div id="swagger-ui"></div>
            <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
            <script>
                const ui = SwaggerUIBundle({{
                    url: '{openapi_url}',
                    dom_id: '#swagger-ui',
                    presets: [
                        SwaggerUIBundle.presets.apis,
                        SwaggerUIBundle.SwaggerUIStandalonePreset
                    ],
                    layout: "BaseLayout",
                    deepLinking: true,
                    showExtensions: true,
                    showCommonExtensions: true
                }})
            </script>
        </body>
        </html>
        """
    
    @staticmethod
    def get_redoc_html(openapi_url: str, title: str) -> str:
        """Generate HTML for ReDoc."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{title}</title>
            <meta charset="utf-8"/>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                }}
            </style>
        </head>
        <body>
            <redoc spec-url='{openapi_url}'></redoc>
            <script src="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js"></script>
        </body>
        </html>
        """
