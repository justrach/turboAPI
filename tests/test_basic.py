"""
Basic tests for the tatsat framework.
"""

import sys
import os
import pytest
from typing import Optional

# Add the parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import tatsat
from tatsat import Tatsat
from satya import Model, Field

# Create a test app
app = Tatsat(title="Test App")

class Item(Model):
    name: str = Field()
    price: float = Field(gt=0)
    is_available: bool = Field(default=True)
    description: Optional[str] = Field(required=False)

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/items/{item_id}")
def read_item(item_id: int, q: Optional[str] = None):
    return {"item_id": item_id, "q": q}

@app.post("/items/", response_model=Item)
def create_item(item: Item):
    return item.to_dict()

# Tests
@pytest.mark.asyncio
async def test_read_root():
    from starlette.testclient import TestClient
    
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"Hello": "World"}

@pytest.mark.asyncio
async def test_read_item():
    from starlette.testclient import TestClient
    
    with TestClient(app) as client:
        response = client.get("/items/1?q=test")
        assert response.status_code == 200
        assert response.json() == {"item_id": 1, "q": "test"}

@pytest.mark.asyncio
async def test_create_item():
    from starlette.testclient import TestClient
    
    with TestClient(app) as client:
        item_data = {
            "name": "Test Item",
            "price": 10.5,
            "description": "This is a test item"
        }
        response = client.post("/items/", json=item_data)
        assert response.status_code == 200
        assert response.json()["name"] == "Test Item"
        assert response.json()["price"] == 10.5
        assert response.json()["description"] == "This is a test item"
        assert response.json()["is_available"] == True

@pytest.mark.asyncio
async def test_create_item_validation_error():
    from starlette.testclient import TestClient
    
    with TestClient(app) as client:
        # Invalid price (must be > 0)
        item_data = {
            "name": "Invalid Item",
            "price": -10
        }
        response = client.post("/items/", json=item_data)
        assert response.status_code == 400  # Should fail validation
