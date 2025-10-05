"""
Test FastAPI Compatibility Features in TurboAPI v0.3.0+
Demonstrates automatic body parsing, Satya validation, and tuple returns
"""

from satya import Field, Model

from turboapi import TurboAPI

# Create app
app = TurboAPI(title="FastAPI Compatibility Test", version="1.0.0")

# In-memory database
database = {
    1: {"id": 1, "name": "Alice", "email": "alice@example.com"},
    2: {"id": 2, "name": "Bob", "email": "bob@example.com"}
}


# ============================================================================
# 1. AUTOMATIC JSON BODY PARSING
# ============================================================================

@app.post("/search")
def search(query: str, top_k: int = 10):
    """
    Automatic body parsing - no need for request.json()!
    
    Test with:
    curl -X POST http://localhost:8000/search \
      -H "Content-Type: application/json" \
      -d '{"query": "test", "top_k": 5}'
    """
    return {
        "query": query,
        "top_k": top_k,
        "results": [f"result_{i}" for i in range(top_k)]
    }


# ============================================================================
# 2. SATYA MODEL VALIDATION
# ============================================================================

class UserCreate(Model):
    """User creation model with Satya validation."""
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(pattern=r'^[\w\.-]+@[\w\.-]+\.\w+$')
    age: int = Field(ge=0, le=150)


class UserResponse(Model):
    """User response model."""
    id: int
    name: str
    email: str
    age: int


@app.post("/users/validate")
def create_validated_user(user: UserCreate):
    """
    Automatic Satya validation!
    
    Test with:
    curl -X POST http://localhost:8000/users/validate \
      -H "Content-Type: application/json" \
      -d '{"name": "Charlie", "email": "charlie@example.com", "age": 30}'
    """
    # Validation happens automatically
    new_id = max(database.keys()) + 1 if database else 1
    user_data = user.model_dump()
    user_data['id'] = new_id
    
    database[new_id] = user_data
    
    # Return 201 Created with tuple syntax
    return UserResponse(**user_data).model_dump(), 201


# ============================================================================
# 3. TUPLE RETURN FOR STATUS CODES
# ============================================================================

@app.get("/users/{user_id}")
def get_user(user_id: int):
    """
    FastAPI-style tuple returns for status codes!
    
    Test with:
    curl http://localhost:8000/users/1
    curl http://localhost:8000/users/999  # Returns 404
    """
    if user_id not in database:
        # FastAPI-style tuple return!
        return {"error": "User not found", "user_id": user_id}, 404
    
    return database[user_id]


@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    """
    Delete with proper status codes.
    
    Test with:
    curl -X DELETE http://localhost:8000/users/1
    """
    if user_id not in database:
        return {"error": "User not found"}, 404
    
    del database[user_id]
    return {"message": "User deleted", "user_id": user_id}, 200


# ============================================================================
# 4. MIXED PARAMETERS (Path + Body)
# ============================================================================

@app.put("/users/{user_id}")
def update_user(user_id: int, name: str, email: str):
    """
    Path parameter + automatic body parsing!
    
    Test with:
    curl -X PUT http://localhost:8000/users/1 \
      -H "Content-Type: application/json" \
      -d '{"name": "Alice Updated", "email": "alice.new@example.com"}'
    """
    if user_id not in database:
        return {"error": "User not found"}, 404
    
    database[user_id].update({"name": name, "email": email})
    return database[user_id]


# ============================================================================
# 5. QUERY PARAMETERS
# ============================================================================

@app.get("/users")
def list_users(limit: int = 10, offset: int = 0):
    """
    Query parameters with defaults.
    
    Test with:
    curl http://localhost:8000/users?limit=5&offset=0
    """
    users_list = list(database.values())
    return {
        "users": users_list[offset:offset + limit],
        "total": len(users_list),
        "limit": limit,
        "offset": offset
    }


# ============================================================================
# 6. STARTUP/SHUTDOWN EVENTS
# ============================================================================

@app.on_event("startup")
def startup():
    """Called when server starts."""
    print("✅ FastAPI Compatibility Test Server starting...")
    print(f"   Loaded {len(database)} test users")


@app.on_event("shutdown")
def shutdown():
    """Called when server stops."""
    print("✅ FastAPI Compatibility Test Server shutting down...")


# ============================================================================
# 7. COMPLEX NESTED MODELS
# ============================================================================

class Address(Model):
    """Address model."""
    street: str = Field(min_length=1)
    city: str = Field(min_length=1)
    country: str = Field(min_length=2, max_length=2)  # ISO code
    zip_code: str = Field(pattern=r'^\d{5}$')


class UserWithAddress(Model):
    """User with nested address."""
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(pattern=r'^[\w\.-]+@[\w\.-]+\.\w+$')
    address: Address


@app.post("/users/with-address")
def create_user_with_address(user: UserWithAddress):
    """
    Nested Satya model validation!
    
    Test with:
    curl -X POST http://localhost:8000/users/with-address \
      -H "Content-Type: application/json" \
      -d '{
        "name": "Dave",
        "email": "dave@example.com",
        "address": {
          "street": "123 Main St",
          "city": "Boston",
          "country": "US",
          "zip_code": "02101"
        }
      }'
    """
    return {
        "message": "User with address created",
        "data": user.model_dump()
    }, 201


# ============================================================================
# 8. ERROR HANDLING
# ============================================================================

@app.get("/error-demo/{error_type}")
def error_demo(error_type: str):
    """
    Demonstrate different error responses.
    
    Test with:
    curl http://localhost:8000/error-demo/400
    curl http://localhost:8000/error-demo/404
    curl http://localhost:8000/error-demo/500
    """
    if error_type == "400":
        return {"error": "Bad Request", "detail": "Invalid input"}, 400
    elif error_type == "404":
        return {"error": "Not Found", "detail": "Resource not found"}, 404
    elif error_type == "500":
        return {"error": "Internal Server Error", "detail": "Something went wrong"}, 500
    
    return {"message": "No error", "type": error_type}


# ============================================================================
# 9. HEALTH CHECK
# ============================================================================

@app.get("/")
def root():
    """Root endpoint."""
    return {
        "message": "FastAPI Compatibility Test API",
        "version": "1.0.0",
        "features": [
            "Automatic JSON body parsing",
            "Satya model validation",
            "Tuple return for status codes",
            "Startup/shutdown events",
            "Type-safe parameters"
        ]
    }


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "users_count": len(database),
        "features_working": "all"
    }


# ============================================================================
# RUN SERVER
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 TurboAPI FastAPI Compatibility Test Server")
    print("="*60)
    print("\nTest endpoints:")
    print("  GET  http://localhost:8000/")
    print("  GET  http://localhost:8000/health")
    print("  GET  http://localhost:8000/users")
    print("  GET  http://localhost:8000/users/{user_id}")
    print("  POST http://localhost:8000/search")
    print("  POST http://localhost:8000/users/validate")
    print("  POST http://localhost:8000/users/with-address")
    print("  PUT  http://localhost:8000/users/{user_id}")
    print("  DELETE http://localhost:8000/users/{user_id}")
    print("  GET  http://localhost:8000/error-demo/{error_type}")
    print("\n" + "="*60 + "\n")
    
    # Disable rate limiting for testing
    app.configure_rate_limiting(enabled=False)
    
    # Run the server
    app.run(host="127.0.0.1", port=8000)
