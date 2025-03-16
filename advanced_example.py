"""
Advanced TurboAPI application example.

This example demonstrates more advanced features of TurboAPI:
- Complex model validation with nested satya models
- API Routers for route organization
- Middleware usage
- Authentication with dependencies
- Advanced request/response handling
- Exception handling
- Background tasks
- WebSocket support
"""

import sys
import os
import time
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, UTC
import asyncio
import jwt
import bcrypt

# Add the parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import turboapi
from turboapi import (
    TurboAPI, APIRouter, Depends, HTTPException, 
    JSONResponse, Response, Request,
    Body, Query, Path, Header, Cookie,
    BackgroundTasks, WebSocket
)
from satya import Model, Field

# Create a TurboAPI application
app = TurboAPI(
    title="TurboAPI Advanced Example",
    description="A more complex API showing advanced TurboAPI features with satya validation",
    version="0.1.0",
)

# ======================= Satya Models =======================

class Location(Model):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    name: Optional[str] = Field(required=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the location to a dictionary."""
        result = {}
        for field_name in self.__fields__:
            value = getattr(self, field_name)
            if value is not None:
                result[field_name] = value
        return result

class ReviewComment(Model):
    content: str = Field(min_length=3, max_length=500)
    rating: int = Field(ge=1, le=5)
    created_at: datetime = Field(default=datetime.now())
    updated_at: Optional[datetime] = Field(required=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the review comment to a dictionary."""
        result = {}
        for field_name in self.__fields__:
            value = getattr(self, field_name)
            if value is not None:
                if isinstance(value, datetime):
                    result[field_name] = value.isoformat()
                else:
                    result[field_name] = value
        return result

class Product(Model):
    id: Optional[int] = Field(required=False)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=5, max_length=1000)
    price: float = Field(gt=0)
    discount_rate: Optional[float] = Field(required=False, ge=0, le=1)
    stock: int = Field(ge=0)
    is_available: bool = Field(default=True)
    categories: List[str] = Field(default=[])
    location: Optional[Location] = Field(required=False)
    reviews: List[ReviewComment] = Field(default=[])
    metadata: Dict[str, Any] = Field(default={})
    
    def discounted_price(self) -> float:
        """Calculate the discounted price of the product."""
        if self.discount_rate:
            return self.price * (1 - self.discount_rate)
        return self.price
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert the product to a dictionary."""
        result = {}
        for field_name in self.__fields__:
            value = getattr(self, field_name)
            if value is not None:
                if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
                    result[field_name] = value.to_dict()
                elif isinstance(value, list) and value and hasattr(value[0], "to_dict") and callable(getattr(value[0], "to_dict")):
                    result[field_name] = [item.to_dict() for item in value]
                else:
                    result[field_name] = value
        return result

class User(Model):
    id: Optional[int] = Field(required=False)
    username: str = Field(min_length=3, max_length=50)
    email: str = Field(min_length=5, max_length=100)
    full_name: Optional[str] = Field(required=False)
    created_at: datetime = Field(default=datetime.now())
    is_active: bool = Field(default=True)
    role: str = Field(default="user")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the user to a dictionary."""
        result = {}
        for field_name in self.__fields__:
            if field_name == "hashed_password":
                continue  # Skip sensitive fields
            value = getattr(self, field_name)
            if value is not None:
                if isinstance(value, datetime):
                    result[field_name] = value.isoformat()
                else:
                    result[field_name] = value
        return result

class Token(Model):
    access_token: str = Field()
    token_type: str = Field()

    def to_dict(self) -> Dict[str, str]:
        """Convert the token to a dictionary."""
        return {
            "access_token": self.access_token,
            "token_type": self.token_type
        }

class WebSocketMessage(Model):
    event: str = Field()
    data: Dict[str, Any] = Field(default={})
    timestamp: datetime = Field(default=datetime.now())

    def to_dict(self) -> Dict[str, Any]:
        """Convert the message to a dictionary."""
        return {
            "event": self.event,
            "data": self.data,
            "timestamp": self.timestamp.isoformat()
        }

# ======================= Security Setup =======================

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())

# JWT settings
SECRET_KEY = "your-secret-key"  # In production, use a secure secret key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# ======================= Sample Database =======================

products_db = {
    1: {
        "id": 1,
        "name": "Premium Laptop",
        "description": "High-performance laptop with the latest technology",
        "price": 1299.99,
        "discount_rate": 0.1,
        "stock": 15,
        "is_available": True,
        "categories": ["electronics", "computers"],
        "location": {"latitude": 37.7749, "longitude": -122.4194, "name": "San Francisco Warehouse"},
        "reviews": [
            {
                "content": "Great product, fast delivery!",
                "rating": 5,
                "created_at": datetime.now(),
            }
        ],
        "metadata": {"brand": "TechMaster", "model": "X1-2023", "warranty_years": 2}
    }
}

users_db = {
    1: {
        "id": 1,
        "username": "admin",
        "email": "admin@example.com",
        "full_name": "Admin User",
        "created_at": datetime.now(),
        "is_active": True,
        "role": "admin",
        "hashed_password": hash_password("admin123")
    }
}

# ======================= Security Functions =======================

def create_access_token(data: dict):
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# ======================= Dependencies =======================

def get_token_header(request: Request, authorization: Optional[str] = Header(None)):
    """Validate JWT token from header."""
    from starlette.exceptions import HTTPException as StarletteHTTPException
    
    # Get the authorization header from the request
    auth_header = request.headers.get("Authorization")
    
    if not auth_header:
        raise StarletteHTTPException(status_code=401, detail="Authorization header missing")
    
    # Check if the header starts with "Bearer "
    if not auth_header.startswith("Bearer "):
        raise StarletteHTTPException(status_code=401, detail="Invalid authentication scheme")
    
    # Extract the token
    token = auth_header[7:]  # Remove "Bearer " prefix
    
    try:
        # For testing, we'll allow expired tokens
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
        return payload
    except jwt.PyJWTError as e:
        raise StarletteHTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

def get_current_user(token_data = Depends(get_token_header)):
    """Get the current authenticated user."""
    from starlette.exceptions import HTTPException as StarletteHTTPException
    
    username = token_data.get("sub")
    user = next((u for u in users_db.values() if u["username"] == username), None)
    
    if not user:
        raise StarletteHTTPException(status_code=404, detail="User not found")
    
    return User(**user)

def check_admin_role(current_user: User = Depends(get_current_user)):
    """Check if the current user has admin role."""
    from starlette.exceptions import HTTPException as StarletteHTTPException
    
    if current_user.role != "admin":
        raise StarletteHTTPException(status_code=403, detail="Not enough permissions")
    return current_user

# ======================= Middleware =======================

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add processing time to response headers."""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response

# ======================= Exception Handlers =======================

# Register exception handlers
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle Starlette HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc.detail)},
    )

@app.exception_handler(HTTPException)
async def turboapi_http_exception_handler(request: Request, exc: HTTPException):
    """Handle TurboAPI HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc.detail)},
        headers=exc.headers,
    )

@app.exception_handler(404)
async def not_found_exception_handler(request: Request, exc):
    """Handle 404 errors."""
    return JSONResponse(
        status_code=404,
        content={"detail": "The requested resource was not found"},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    return JSONResponse(
        status_code=500,
        content={"detail": f"An unexpected error occurred: {str(exc)}"},
    )

# ======================= Background Tasks =======================

async def send_email_notification(email: str, subject: str, content: str):
    """Simulate sending an email notification."""
    await asyncio.sleep(1)  # Simulate email sending
    print(f"Email sent to {email}: {subject}")

# ======================= API Routes =======================

# Create API router for organization
router = APIRouter(prefix="/api/v1")

# Basic routes
@app.get("/")
def read_root():
    """Return a welcome message."""
    return {"message": "Welcome to TurboAPI Advanced API Example"}

# Product routes
@router.get("/products/", response_model=List[Product], tags=["products"])
def get_products(
    skip: int = Query(0, ge=0, description="Number of products to skip"),
    limit: int = Query(10, ge=1, le=100, description="Max number of products to return"),
    category: Optional[str] = Query(None, description="Filter by category")
):
    """Get a list of products with optional filtering."""
    products = list(products_db.values())
    
    if category:
        products = [p for p in products if category in p.get("categories", [])]
    
    return products[skip:skip + limit]

@router.get("/products/{product_id}", response_model=Product, tags=["products"])
async def get_product(request: Request, product_id: int = Path(..., ge=1, description="The ID of the product to get")):
    """Get details about a specific product."""
    from starlette.exceptions import HTTPException as StarletteHTTPException
    
    # Print the products_db for debugging
    print(f"Products DB: {products_db}")
    print(f"Looking for product ID: {product_id}, type: {type(product_id)}")
    
    # Convert product_id to int if it's a string
    if isinstance(product_id, str):
        try:
            product_id = int(product_id)
        except ValueError:
            raise StarletteHTTPException(status_code=400, detail="Invalid product ID")
    
    if product_id not in products_db:
        raise StarletteHTTPException(status_code=404, detail="Product not found")
    
    return products_db[product_id]

@router.post("/products/", response_model=Product, status_code=201, tags=["products"])
async def create_product(
    request: Request,
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(check_admin_role)
):
    """Create a new product (admin only)."""
    from starlette.exceptions import HTTPException as StarletteHTTPException
    
    # Get the request body
    try:
        product_data = await request.json()
    except Exception as e:
        raise StarletteHTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
    
    # Check required fields
    required_fields = ["name", "description", "price", "stock"]
    for field in required_fields:
        if field not in product_data:
            raise StarletteHTTPException(status_code=422, detail=f"Missing required field: {field}")
    
    # Validate product data using satya
    try:
        # Check for negative price explicitly
        if "price" in product_data and product_data["price"] <= 0:
            raise StarletteHTTPException(status_code=422, detail="Price must be greater than 0")
            
        product = Product(**product_data)
    except ValueError as e:
        raise StarletteHTTPException(status_code=422, detail=str(e))
    
    # Generate a new ID
    product_id = max(products_db.keys()) + 1 if products_db else 1
    
    # Save the product with the generated ID
    product_dict = product.to_dict()
    product_dict["id"] = product_id
    products_db[product_id] = product_dict
    
    # Add background task to notify admin
    if background_tasks:
        background_tasks.add_task(
            send_email_notification,
            email=current_user.email,
            subject="New Product Created",
            content=f"Product {product.name} has been created."
        )
    
    return product_dict

@router.put("/products/{product_id}", response_model=Product, tags=["products"])
async def update_product(
    request: Request,
    product_id: int,
    current_user: User = Depends(check_admin_role)
):
    """Update an existing product (admin only)."""
    from starlette.exceptions import HTTPException as StarletteHTTPException
    
    # Debug information
    print(f"Update product called with ID: {product_id}, type: {type(product_id)}")
    print(f"Products DB keys: {list(products_db.keys())}")
    
    # Convert product_id to int if it's a string
    if isinstance(product_id, str):
        try:
            product_id = int(product_id)
        except ValueError:
            raise StarletteHTTPException(status_code=400, detail="Invalid product ID")
    
    if product_id not in products_db:
        raise StarletteHTTPException(status_code=404, detail=f"Product not found with ID: {product_id}")
    
    # Get the request body
    try:
        product_data = await request.json()
        print(f"Update product data: {product_data}")
    except Exception as e:
        raise StarletteHTTPException(status_code=400, detail=f"Invalid JSON body: {str(e)}")
    
    # Validate product data using satya
    try:
        # Check for negative price explicitly
        if "price" in product_data and product_data["price"] <= 0:
            raise StarletteHTTPException(status_code=422, detail="Price must be greater than 0")
            
        # Merge with existing product data
        updated_data = products_db[product_id].copy()
        updated_data.update(product_data)
        
        product = Product(**updated_data)
    except ValueError as e:
        raise StarletteHTTPException(status_code=422, detail=str(e))
    
    # Update the product
    product_dict = product.to_dict()
    product_dict["id"] = product_id
    products_db[product_id] = product_dict
    
    return product_dict

@router.delete("/products/{product_id}", tags=["products"])
async def delete_product(
    request: Request,
    product_id: int,
    current_user: User = Depends(check_admin_role)
):
    """Delete a product (admin only)."""
    from starlette.exceptions import HTTPException as StarletteHTTPException
    
    # Debug information
    print(f"Delete product called with ID: {product_id}, type: {type(product_id)}")
    print(f"Products DB keys: {list(products_db.keys())}")
    
    # Convert product_id to int if it's a string
    if isinstance(product_id, str):
        try:
            product_id = int(product_id)
        except ValueError:
            raise StarletteHTTPException(status_code=400, detail="Invalid product ID")
    
    if product_id not in products_db:
        raise StarletteHTTPException(status_code=404, detail=f"Product not found with ID: {product_id}")
    
    del products_db[product_id]
    return {"detail": "Product deleted successfully"}

# User routes
@router.get("/users/me", response_model=User, tags=["users"])
async def get_user_me(current_user: User = Depends(get_current_user)):
    """Get information about the current authenticated user."""
    return current_user.to_dict()

@router.get("/users/", response_model=List[User], tags=["users"])
async def get_users(
    skip: int = 0,
    limit: int = 10,
    current_user: User = Depends(check_admin_role)
):
    """Get a list of all users (admin only)."""
    users = list(users_db.values())
    return [User(**user).to_dict() for user in users[skip:skip + limit]]

# Authentication routes
@app.post("/token", response_model=Token, tags=["auth"])
async def login(username: str = Body(...), password: str = Body(...)):
    """Generate an access token for a user."""
    from starlette.exceptions import HTTPException as StarletteHTTPException
    
    user = next((u for u in users_db.values() if u["username"] == username), None)
    if not user or not verify_password(password, user["hashed_password"]):
        raise StarletteHTTPException(
            status_code=401,
            detail="Invalid credentials"
        )
    
    access_token = create_access_token({"sub": user["username"]})
    token = Token(access_token=access_token, token_type="bearer")
    return token.to_dict()

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle WebSocket connections."""
    await websocket.accept()
    try:
        while True:
            # Receive and parse message
            data = await websocket.receive_text()
            message = WebSocketMessage(
                event="message",
                data={"content": data},
                timestamp=datetime.now()
            )
            
            # Echo back the message
            await websocket.send_json(message.to_dict())
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await websocket.close()

# Custom route with explicit request handling
@router.post("/echo", tags=["utils"])
async def echo(request: Request):
    """Echo back the request body."""
    try:
        body = await request.json()
        return JSONResponse(content=body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")

# Include the router in the main app
app.include_router(router)

# Add event handlers
@app.on_event("startup")
async def startup_event():
    """Handle application startup."""
    print("Application startup")
    # In a real app, you might initialize database connections here

@app.on_event("shutdown")
async def shutdown_event():
    """Handle application shutdown."""
    print("Application shutdown")
    # In a real app, you might close database connections here

if __name__ == "__main__":
    import uvicorn
    print("Starting TurboAPI advanced example app...")
    print("Access the API docs at http://localhost:8000/docs")
    print("Default admin credentials: username='admin', password='admin123'")
    uvicorn.run(app, host="0.0.0.0", port=8000) 