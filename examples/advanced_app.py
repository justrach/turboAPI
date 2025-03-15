"""
Advanced Tatsat application example.

This example demonstrates more advanced features of Tatsat:
- Complex model validation with nested satya models
- API Routers for route organization
- Middleware usage
- Authentication with dependencies
- Advanced request/response handling
- Exception handling
"""

import sys
import os
import time
from typing import List, Optional, Dict, Any
from datetime import datetime

# Add the parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import tatsat
from tatsat import (
    Tatsat, APIRouter, Depends, HTTPException, 
    JSONResponse, Response, Request,
    Body, Query, Path, Header, Cookie
)
from satya import Model, Field

# Create a Tatsat application
app = Tatsat(
    title="Tatsat Advanced Example",
    description="A more complex API showing advanced Tatsat features with satya validation",
    version="0.1.0",
)

# Define satya models with complex validation
class Location(Model):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    name: Optional[str] = Field(required=False)

class ReviewComment(Model):
    content: str = Field(min_length=3, max_length=500)
    rating: int = Field(ge=1, le=5)
    created_at: datetime = Field(default=datetime.now())
    updated_at: Optional[datetime] = Field(required=False)

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

class User(Model):
    id: Optional[int] = Field(required=False)
    username: str = Field(min_length=3, max_length=50)
    email: str = Field(min_length=5, max_length=100)  # Using length validation instead of regex
    full_name: Optional[str] = Field(required=False)
    created_at: datetime = Field(default=datetime.now())
    is_active: bool = Field(default=True)
    role: str = Field(default="user")

class Token(Model):
    access_token: str = Field()
    token_type: str = Field()

# Sample database
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
    },
    2: {
        "id": 2,
        "name": "Ergonomic Chair",
        "description": "Comfortable office chair with lumbar support",
        "price": 249.99,
        "stock": 30,
        "is_available": True,
        "categories": ["furniture", "office"],
        "reviews": [],
        "metadata": {"brand": "ComfortPlus", "color": "black", "material": "leather"}
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
        "role": "admin"
    },
    2: {
        "id": 2,
        "username": "user",
        "email": "user@example.com",
        "full_name": "Regular User",
        "created_at": datetime.now(),
        "is_active": True,
        "role": "user"
    }
}

# Fake authentication database
tokens_db = {
    "fake-access-token-admin": {"sub": "admin", "role": "admin"},
    "fake-access-token-user": {"sub": "user", "role": "user"}
}

# Middleware
@app.middleware("http")
async def add_process_time_header(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response

# Dependency functions
def get_token_header(authorization: Optional[str] = Header(None)):
    if authorization is None:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    
    if token not in tokens_db:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return tokens_db[token]

def get_current_user(token_data = Depends(get_token_header)):
    username = token_data["sub"]
    user = next((u for u in users_db.values() if u["username"] == username), None)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return User(**user)

def check_admin_role(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user

# Create API routers for organization
router = APIRouter(prefix="/api/v1")

# Exception handlers
@app.exception_handler(404)
async def not_found_exception_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content={"detail": "The requested resource was not found"},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": f"An unexpected error occurred: {str(exc)}"},
    )

# Basic routes
@app.get("/")
def read_root():
    """Return a welcome message."""
    return {"message": "Welcome to Tatsat Advanced API Example"}

# Product routes
@router.get("/products/", response_model=List[Product], tags=["products"])
def get_products(
    skip: int = Query(0, ge=0, description="Number of products to skip"),
    limit: int = Query(10, ge=1, le=100, description="Max number of products to return"),
    category: Optional[str] = Query(None, description="Filter by category")
):
    """
    Get a list of products with optional filtering.
    """
    products = list(products_db.values())
    
    if category:
        products = [p for p in products if category in p.get("categories", [])]
    
    return products[skip:skip + limit]

@router.get("/products/{product_id}", response_model=Product, tags=["products"])
def get_product(product_id: int = Path(..., ge=1, description="The ID of the product to get")):
    """
    Get details about a specific product.
    """
    if product_id not in products_db:
        raise HTTPException(status_code=404, detail="Product not found")
    
    return products_db[product_id]

@router.post("/products/", response_model=Product, status_code=201, tags=["products"])
def create_product(
    product: Product,
    current_user: User = Depends(check_admin_role)
):
    """
    Create a new product (admin only).
    """
    # Generate a new ID
    product_id = max(products_db.keys()) + 1 if products_db else 1
    
    # Save the product with the generated ID
    product_dict = product.to_dict()
    product_dict["id"] = product_id
    products_db[product_id] = product_dict
    
    return product_dict

@router.put("/products/{product_id}", response_model=Product, tags=["products"])
def update_product(
    product_id: int,
    product: Product,
    current_user: User = Depends(check_admin_role)
):
    """
    Update an existing product (admin only).
    """
    if product_id not in products_db:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Update the product
    product_dict = product.to_dict()
    product_dict["id"] = product_id
    products_db[product_id] = product_dict
    
    return product_dict

@router.delete("/products/{product_id}", tags=["products"])
def delete_product(
    product_id: int,
    current_user: User = Depends(check_admin_role)
):
    """
    Delete a product (admin only).
    """
    if product_id not in products_db:
        raise HTTPException(status_code=404, detail="Product not found")
    
    del products_db[product_id]
    return {"detail": "Product deleted successfully"}

# User routes
@router.get("/users/me", response_model=User, tags=["users"])
def get_user_me(current_user: User = Depends(get_current_user)):
    """
    Get information about the current authenticated user.
    """
    return current_user

@router.get("/users/", response_model=List[User], tags=["users"])
def get_users(
    skip: int = 0,
    limit: int = 10,
    current_user: User = Depends(check_admin_role)
):
    """
    Get a list of all users (admin only).
    """
    users = list(users_db.values())
    return users[skip:skip + limit]

# Authentication routes
@app.post("/token", response_model=Token, tags=["auth"])
def login(username: str = Body(...), password: str = Body(...)):
    """
    Generate an access token for a user.
    
    This is a simplified example and does not implement real authentication.
    In a real application, you'd verify credentials against a database.
    """
    # In a real app, verify username and password
    if username == "admin" and password == "admin":
        return {
            "access_token": "fake-access-token-admin",
            "token_type": "bearer"
        }
    elif username == "user" and password == "user":
        return {
            "access_token": "fake-access-token-user",
            "token_type": "bearer"
        }
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")

# Custom route with explicit request handling
@router.post("/echo", tags=["utils"])
async def echo(request: Request):
    """
    Echo back the request body.
    """
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
    print("Application startup")
    # In a real app, you might initialize database connections here

@app.on_event("shutdown")
async def shutdown_event():
    print("Application shutdown")
    # In a real app, you might close database connections here

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
