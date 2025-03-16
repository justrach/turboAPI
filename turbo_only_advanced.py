"""
Advanced example of using the TurboAPI framework without direct Starlette imports.

This example demonstrates using TurboAPI's components exclusively, avoiding
direct Starlette imports to ensure maximum portability and compatibility.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any

from jose import JWTError, jwt
from passlib.context import CryptContext
from satya import Model, Field

from turboapi import (
    TurboAPI, APIRouter, Depends, HTTPException, 
    JSONResponse, Request, Response, WebSocket,
    BackgroundTasks, Middleware
)
from turboapi.middleware import AuthenticationMiddleware
from turboapi.authentication import AuthCredentials, BaseUser, BaseAuthentication

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize API
app = TurboAPI(
    title="TurboAPI Advanced Example",
    description="A more complex API showing advanced TurboAPI features without direct Starlette imports",
    version="0.1.0",
)

# Initialize router
router = APIRouter()

# JWT Configuration
SECRET_KEY = "your-secret-key-keep-it-secret"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Model definitions
class Location(Model):
    """Location model with coordinates."""
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    name: Optional[str] = Field(required=False)
    
    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "name": self.name
        }

class ReviewComment(Model):
    """Review comment model."""
    content: str = Field(min_length=3, max_length=500)
    rating: int = Field(ge=1, le=5)
    created_at: datetime = Field(default=datetime.now())
    
    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "content": self.content,
            "rating": self.rating,
            "created_at": self.created_at.isoformat()
        }

class Product(Model):
    """Product model with validation."""
    id: Optional[int] = Field(required=False)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=5, max_length=1000)
    price: float = Field(gt=0)
    stock: int = Field(ge=0)
    is_available: bool = Field(default=True)
    categories: List[str] = Field(default=[])
    location: Optional[Location] = Field(required=False)
    reviews: List[ReviewComment] = Field(default=[])
    created_by: Optional[str] = Field(required=False)
    
    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "price": self.price,
            "stock": self.stock,
            "is_available": self.is_available,
            "categories": self.categories,
            "location": self.location.to_dict() if self.location else None,
            "reviews": [r.to_dict() for r in self.reviews] if self.reviews else [],
            "created_by": self.created_by
        }

class User(Model):
    """User model with validation."""
    username: str = Field(min_length=3, max_length=50)
    email: str = Field(min_length=5, max_length=100)
    full_name: Optional[str] = Field(required=False)
    disabled: bool = Field(default=False)
    
    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "disabled": self.disabled
        }

class Token(Model):
    """Token model for authentication."""
    access_token: str = Field()
    token_type: str = Field()
    username: str = Field()
    expires_in: int = Field()
    
    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "access_token": self.access_token,
            "token_type": self.token_type,
            "username": self.username,
            "expires_in": self.expires_in
        }

# Mock databases
users_db = {
    "john": {
        "username": "john",
        "email": "john@example.com",
        "full_name": "John Doe",
        "hashed_password": pwd_context.hash("secret"),
        "disabled": False,
    },
    "jane": {
        "username": "jane",
        "email": "jane@example.com",
        "full_name": "Jane Smith",
        "hashed_password": pwd_context.hash("password"),
        "disabled": True,
    },
    "admin": {
        "username": "admin",
        "email": "admin@example.com",
        "full_name": "Admin User",
        "hashed_password": pwd_context.hash("admin123"),
        "disabled": False,
    }
}

products_db = {}


def verify_password(plain_password, hashed_password):
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def get_user(username: str):
    """Get a user from the database."""
    if username in users_db:
        user_data = users_db[username]
        return User(
            username=user_data["username"],
            email=user_data["email"],
            full_name=user_data["full_name"],
            disabled=user_data["disabled"],
        )
    return None


def authenticate_user(username: str, password: str):
    """Authenticate a user with username and password."""
    user_dict = users_db.get(username)
    if not user_dict:
        return False
    if not verify_password(password, user_dict["hashed_password"]):
        return False
    return User(
        username=user_dict["username"],
        email=user_dict["email"],
        full_name=user_dict["full_name"],
        disabled=user_dict["disabled"],
    )


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create an access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_token_header(request: Request):
    """Extract and validate the token from the Authorization header."""
    try:
        auth = request.headers.get("Authorization")
        if not auth:
            raise HTTPException(
                status_code=401,
                detail="Authorization header missing",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        scheme, token = auth.split()
        if scheme.lower() != "bearer":
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication scheme",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid token payload",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return username
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(token: str = Depends(get_token_header)):
    """Get the current user from the token."""
    user = get_user(token)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_active_user(current_user = Depends(get_current_user)):
    """Get the current active user."""
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


class TokenAuthBackend(BaseAuthentication):
    """Token authentication backend."""
    
    async def authenticate(self, request: Request):
        """Authenticate the request."""
        try:
            username = await get_token_header(request)
            user = get_user(username)
            if user:
                return AuthCredentials(["authenticated"]), user
        except HTTPException:
            pass
        
        return AuthCredentials(), None


@router.get("/")
async def read_root():
    """Root endpoint."""
    return {"message": "Welcome to TurboAPI Advanced API Example"}


@router.post("/token")
async def login(request: Request):
    """Login and get access token."""
    try:
        body = await request.json()
        username = body.get("username")
        password = body.get("password")
        
        if not username or not password:
            raise HTTPException(
                status_code=400,
                detail="Missing username or password",
            )
        
        user = authenticate_user(username, password)
        if not user:
            raise HTTPException(
                status_code=401,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user.username}, expires_delta=access_token_expires
        )
        
        token = Token(
            access_token=access_token,
            token_type="bearer",
            username=user.username,
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
        
        return token.to_dict()
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/api/v1/users/me")
async def get_user_me(current_user = Depends(get_current_active_user)):
    """Get current user information."""
    return current_user.to_dict()


@router.get("/api/v1/users/")
async def get_users(current_user = Depends(get_current_active_user)):
    """Get all users."""
    return [User(
        username=user_data["username"],
        email=user_data["email"],
        full_name=user_data["full_name"],
        disabled=user_data["disabled"]
    ).to_dict() for user_data in users_db.values()]


@router.post("/api/v1/products/", status_code=201)
async def create_product(
    request: Request, 
    background_tasks: BackgroundTasks, 
    current_user = Depends(get_current_active_user)
):
    """Create a new product."""
    try:
        body = await request.json()
        
        # Validate required fields in product data
        if not all(key in body for key in ["name", "description", "price"]):
            raise ValueError("Missing required fields: name, description, price")
        
        # Validate price is not negative
        if body.get("price", 0) < 0:
            raise ValueError("Price cannot be negative")
        
        # Create a new product
        product_id = len(products_db) + 1
        
        # Handle location data if provided
        location = None
        if "location" in body and body["location"]:
            location_data = body["location"]
            location = Location(
                latitude=location_data.get("latitude"),
                longitude=location_data.get("longitude"),
                name=location_data.get("name")
            )
        
        # Handle reviews data if provided
        reviews = []
        if "reviews" in body and body["reviews"]:
            for review_data in body["reviews"]:
                review = ReviewComment(
                    content=review_data.get("content"),
                    rating=review_data.get("rating"),
                    created_at=datetime.now()
                )
                reviews.append(review)
        
        # Create the product
        product = Product(
            id=product_id,
            name=body["name"],
            description=body["description"],
            price=body["price"],
            stock=body.get("stock", 0),
            is_available=body.get("is_available", True),
            categories=body.get("categories", []),
            location=location,
            reviews=reviews,
            created_by=current_user.username,
        )
        
        # Save to db
        products_db[product_id] = product
        
        # Add background task to notify admin
        background_tasks.add_task(notify_admin_new_product, product)
        
        return product.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating product: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/api/v1/products/{product_id}")
async def get_product(product_id: int):
    """Get a product by ID."""
    try:
        # If product_id is a string, convert to int
        if isinstance(product_id, str):
            try:
                product_id = int(product_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid product ID")
        
        # Check if product exists
        if product_id not in products_db:
            raise HTTPException(status_code=404, detail=f"Product not found with ID: {product_id}")
        
        return products_db[product_id].to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving product: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.put("/api/v1/products/{product_id}")
async def update_product(
    product_id: int, 
    request: Request, 
    current_user = Depends(get_current_active_user)
):
    """Update a product."""
    try:
        # If product_id is a string, convert to int
        if isinstance(product_id, str):
            try:
                product_id = int(product_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid product ID")
        
        # Check if product exists
        if product_id not in products_db:
            raise HTTPException(status_code=404, detail=f"Product not found with ID: {product_id}")
        
        # Get existing product
        product = products_db[product_id]
        
        # Parse request body
        body = await request.json()
        
        # Update fields
        if "name" in body:
            product.name = body["name"]
        if "description" in body:
            product.description = body["description"]
        if "price" in body:
            # Validate price is not negative
            if body["price"] < 0:
                raise ValueError("Price cannot be negative")
            product.price = body["price"]
        if "stock" in body:
            product.stock = body["stock"]
        if "is_available" in body:
            product.is_available = body["is_available"]
        if "categories" in body:
            product.categories = body["categories"]
        
        # Handle location update if provided
        if "location" in body and body["location"]:
            location_data = body["location"]
            product.location = Location(
                latitude=location_data.get("latitude"),
                longitude=location_data.get("longitude"),
                name=location_data.get("name")
            )
        
        # Save to db
        products_db[product_id] = product
        
        return product.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating product: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/api/v1/products/{product_id}")
async def delete_product(
    product_id: int, 
    current_user = Depends(get_current_active_user)
):
    """Delete a product."""
    try:
        # If product_id is a string, convert to int
        if isinstance(product_id, str):
            try:
                product_id = int(product_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid product ID")
        
        # Check if product exists
        if product_id not in products_db:
            raise HTTPException(status_code=404, detail=f"Product not found with ID: {product_id}")
        
        # Delete from db
        del products_db[product_id]
        
        return {"detail": "Product deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting product: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/api/v1/products")
async def list_products(current_user = Depends(get_current_active_user)):
    """List all products."""
    return [product.to_dict() for product in products_db.values()]


async def notify_admin_new_product(product):
    """Background task to notify admin about new product."""
    logger.info(f"A new product was created: {product.name} by {product.created_by}")
    # Simulate some delay for the background task
    await asyncio.sleep(2)
    logger.info(f"Admin notification sent for product: {product.name}")


# WebSocket messages format
class WebSocketMessage:
    """Helper class to format WebSocket messages."""
    
    @staticmethod
    def format_message(event, data):
        """Format a message with timestamp."""
        return json.dumps({
            "event": event,
            "data": data,
            "timestamp": datetime.now().isoformat()
        })


async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            # Echo the received data back to the client
            await websocket.send_text(
                WebSocketMessage.format_message("message", {"content": data})
            )
            # Send current time
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            await websocket.send_text(
                WebSocketMessage.format_message("time_update", {"server_time": current_time})
            )
            # Wait a bit
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")


# Apply middleware
app.add_middleware(
    AuthenticationMiddleware, backend=TokenAuthBackend()
)


# Custom exception handler for 404 errors
@app.exception_handler(404)
async def not_found_exception_handler(request, exc):
    """Custom handler for 404 errors."""
    return JSONResponse(
        status_code=404,
        content={"detail": "The requested resource was not found"}
    )


# Custom exception handler for HTTP exceptions
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom handler for HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc.detail)}
    )


# General exception handler
@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """General exception handler."""
    logger.error(f"Unexpected error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred"}
    )


# Add custom middleware for timing requests
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Middleware for timing the request processing time."""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


# Add WebSocket route
app.add_route("/ws", websocket_endpoint, methods=["GET"])


# Include the router
app.include_router(router)


# Event handlers
@app.on_event("startup")
async def startup_event():
    """Startup event handler."""
    logger.info("Application startup - TurboAPI version")
    # Initialize product with ID 1
    product_id = 1
    product = Product(
        id=product_id,
        name="Sample Product",
        description="This is a sample product to demonstrate TurboAPI",
        price=99.99,
        stock=10,
        categories=["sample", "demo"],
        location=Location(
            latitude=37.7749,
            longitude=-122.4194,
            name="Sample Location"
        )
    )
    products_db[product_id] = product
    logger.info(f"Initialized product database with sample product (ID: {product_id})")


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler."""
    logger.info("Application shutdown - TurboAPI version")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 