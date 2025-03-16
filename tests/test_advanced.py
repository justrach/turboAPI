"""
Tests for the advanced TurboAPI example.

This test suite covers:
- Authentication
- CRUD operations
- WebSocket functionality
- Background tasks
- Middleware
- Exception handling
"""

import sys
import os
import pytest
import asyncio
import json
from datetime import datetime, timedelta
from typing import AsyncGenerator
import websockets
import pytest_asyncio

# Add the parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from httpx import AsyncClient, ASGITransport
from advanced_example import (
    app, products_db, users_db, create_access_token,
    Product, User, Location, ReviewComment
)

# Configure pytest-asyncio
pytest_plugins = ('pytest_asyncio',)

# Test data
test_product = {
    "name": "Test Product",
    "description": "A test product for testing",
    "price": 99.99,
    "stock": 10,
    "categories": ["test"],
    "location": {
        "latitude": 37.7749,
        "longitude": -122.4194,
        "name": "Test Location"
    }
}

test_user = {
    "username": "testuser",
    "email": "test@example.com",
    "password": "testpass123",
    "full_name": "Test User"
}

@pytest.fixture
def admin_token() -> str:
    """Create an admin token for testing."""
    return create_access_token({"sub": "admin"})

@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client."""
    # Reset the products_db to ensure a clean state
    products_db.clear()
    products_db[1] = {
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
    
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac

@pytest.mark.asyncio
async def test_read_root(client: AsyncClient):
    """Test the root endpoint."""
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to TurboAPI Advanced API Example"}

@pytest.mark.asyncio
async def test_auth_flow(client: AsyncClient):
    """Test the authentication flow."""
    # Test login with correct credentials
    response = await client.post("/token", json={
        "username": "admin",
        "password": "admin123"
    })
    assert response.status_code == 200
    token_data = response.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"

    # Test login with incorrect credentials
    response = await client.post("/token", json={
        "username": "admin",
        "password": "wrongpass"
    })
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_product_crud(client: AsyncClient, admin_token: str):
    """Test product CRUD operations."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    print(f"Headers: {headers}")

    # Create product
    response = await client.post("/api/v1/products/", json=test_product, headers=headers)
    print(f"Response: {response.status_code} - {response.text}")
    assert response.status_code == 201
    created_product = response.json()
    product_id = created_product["id"]
    print(f"Created product ID: {product_id}")
    assert created_product["name"] == test_product["name"]

    # Get product
    response = await client.get(f"/api/v1/products/{product_id}")
    print(f"Get product response: {response.status_code} - {response.text}")
    assert response.status_code == 200
    assert response.json()["name"] == test_product["name"]

    # Update product
    updated_data = test_product.copy()
    updated_data["name"] = "Updated Test Product"
    print(f"Update data: {updated_data}")
    print(f"Update URL: /api/v1/products/{product_id}")
    response = await client.put(
        f"/api/v1/products/{product_id}",
        json=updated_data,
        headers=headers
    )
    print(f"Update response: {response.status_code} - {response.text}")
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Test Product"

    # Delete product
    response = await client.delete(f"/api/v1/products/{product_id}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"detail": "Product deleted successfully"}

@pytest.mark.asyncio
async def test_product_validation(client: AsyncClient, admin_token: str):
    """Test product validation."""
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Test invalid price
    invalid_product = test_product.copy()
    invalid_product["price"] = -10
    response = await client.post("/api/v1/products/", json=invalid_product, headers=headers)
    assert response.status_code == 422

    # Test missing required field
    invalid_product = test_product.copy()
    del invalid_product["name"]
    response = await client.post("/api/v1/products/", json=invalid_product, headers=headers)
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_user_endpoints(client: AsyncClient, admin_token: str):
    """Test user-related endpoints."""
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Get current user
    response = await client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 200
    user_data = response.json()
    assert user_data["username"] == "admin"

    # Get all users (admin only)
    response = await client.get("/api/v1/users/", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)

@pytest.mark.asyncio
async def test_websocket():
    """Test WebSocket functionality."""
    uri = "ws://localhost:8000/ws"
    async with websockets.connect(uri) as websocket:
        # Send a test message
        test_message = "Hello, WebSocket!"
        await websocket.send(test_message)

        # Receive the response
        response = await websocket.recv()
        response_data = json.loads(response)
        
        # Verify the response structure
        assert "event" in response_data
        assert "data" in response_data
        assert "timestamp" in response_data
        assert response_data["event"] == "message"
        assert response_data["data"]["content"] == test_message

@pytest.mark.asyncio
async def test_middleware(client: AsyncClient):
    """Test middleware functionality."""
    response = await client.get("/")
    assert "X-Process-Time" in response.headers
    process_time = float(response.headers["X-Process-Time"])
    assert process_time >= 0

@pytest.mark.asyncio
async def test_error_handling(client: AsyncClient, admin_token: str):
    """Test error handling."""
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Test 404 error
    response = await client.get("/api/v1/products/999")
    assert response.status_code == 404
    assert response.json()["detail"] == "The requested resource was not found"

    # Test unauthorized access
    response = await client.post("/api/v1/products/", json=test_product)
    assert response.status_code == 401

    # Test forbidden access (non-admin user)
    non_admin_token = create_access_token({"sub": "testuser"})
    headers = {"Authorization": f"Bearer {non_admin_token}"}
    response = await client.post("/api/v1/products/", json=test_product, headers=headers)
    assert response.status_code == 404  # User not found since testuser doesn't exist

@pytest.mark.asyncio
async def test_background_tasks(client: AsyncClient, admin_token: str):
    """Test background tasks."""
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Create a product which triggers a background task
    response = await client.post("/api/v1/products/", json=test_product, headers=headers)
    assert response.status_code == 201

    # We can't directly test the background task execution,
    # but we can verify the response was immediate
    assert "id" in response.json()

if __name__ == "__main__":
    pytest.main([__file__, "-v"]) 