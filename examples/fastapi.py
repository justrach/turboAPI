"""
FastAPI equivalent of the TurboAPI example.

This example demonstrates the core features of FastAPI:
- Route definition with decorators
- Path and query parameters
- Request body validation with Pydantic models
- Response validation
- Dependency injection
- Automatic documentation (Swagger UI and ReDoc)
"""

import uvicorn
from typing import List, Optional, Dict

from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field

# Create a FastAPI application
app = FastAPI(
    title="FastAPI Example API",
    description="A sample API showing FastAPI features with Pydantic validation",
    version="0.1.0",
)

# Define Pydantic models (equivalent to satya models)
class Item(BaseModel):
    id: Optional[int] = Field(default=None)
    name: str
    description: Optional[str] = Field(default=None)
    price: float = Field(gt=0)
    tax: Optional[float] = Field(default=None)
    tags: List[str] = Field(default_factory=list)

class User(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = Field(default=None)
    disabled: bool = Field(default=False)

# Simple in-memory database (same as in turboapi1.py)
db = {
    "users": {
        "johndoe": {
            "username": "johndoe",
            "email": "johndoe@example.com",
            "full_name": "John Doe",
            "disabled": False,
        }
    },
    "items": {
        1: {
            "id": 1,
            "name": "Foo",
            "description": "The first item",
            "price": 50.2,
            "tax": 10.5,
            "tags": ["foo", "bar"],
        },
        2: {
            "id": 2,
            "name": "Bar",
            "price": 62.0,
            "tags": ["bar"],
        },
    }
}

# Define dependencies (same as in turboapi1.py, but using FastAPI's HTTPException)
def get_current_user(username: str = "johndoe"):
    if username not in db["users"]:
        raise HTTPException(status_code=404, detail="User not found")
    user_data = db["users"][username]
    return User(**user_data)

def get_db():
    return db

# Define route handlers
@app.get("/")
def read_root():
    """Return a welcome message."""
    return {"message": "Welcome to FastAPI"}

@app.get("/items/", response_model=List[Item])
def read_items(skip: int = 0, limit: int = 10, db_session: dict = Depends(get_db)):
    """
    Get a list of items.
    
    - **skip**: Number of items to skip
    - **limit**: Maximum number of items to return
    """
    items_list = list(db_session["items"].values())
    # Pydantic models will be created from dicts automatically by FastAPI for response_model
    return [Item(**item) for item in items_list[skip : skip + limit]]

@app.get("/items/{item_id}", response_model=Item)
def read_item(item_id: int, q: Optional[str] = None, db_session: dict = Depends(get_db)):
    """
    Get details of a specific item.
    
    - **item_id**: The ID of the item to retrieve
    - **q**: Optional query string
    """
    if item_id not in db_session["items"]:
        raise HTTPException(status_code=404, detail="Item not found")
    
    item_data = db_session["items"][item_id]
    if q:
        # Ensure we return a new dict if 'q' is present, to avoid modifying in-memory db directly for this response
        return Item(**{**item_data, "q": q})
    
    return Item(**item_data)

@app.post("/items/", response_model=Item, status_code=201)
def create_item(item: Item, db_session: dict = Depends(get_db)):
    """
    Create a new item.
    
    - **item**: The item data
    """
    item_dict = item.model_dump(exclude_unset=True) # Use model_dump for Pydantic
    
    if item_dict.get("id") is None:
        if not db_session["items"]: # Handle empty items DB
            item_id = 1
        else:
            item_id = max(db_session["items"].keys()) + 1
        item_dict["id"] = item_id
    else:
        item_id = item_dict["id"]
        if item_id in db_session["items"]:
            raise HTTPException(status_code=400, detail="Item already exists")
    
    db_session["items"][item_id] = item_dict
    return Item(**item_dict)

@app.put("/items/{item_id}", response_model=Item)
def update_item(item_id: int, item: Item, db_session: dict = Depends(get_db)):
    """
    Update an existing item.
    
    - **item_id**: The ID of the item to update
    - **item**: The updated item data
    """
    if item_id not in db_session["items"]:
        raise HTTPException(status_code=404, detail="Item not found")
    
    item_dict = item.model_dump(exclude_unset=True)
    item_dict["id"] = item_id  # Ensure ID remains consistent
    
    db_session["items"][item_id] = item_dict
    return Item(**item_dict)

@app.delete("/items/{item_id}")
def delete_item(item_id: int, db_session: dict = Depends(get_db)):
    """
    Delete an item.
    
    - **item_id**: The ID of the item to delete
    """
    if item_id not in db_session["items"]:
        raise HTTPException(status_code=404, detail="Item not found")
    
    del db_session["items"][item_id]
    return {"message": "Item deleted successfully"}

@app.get("/users/me", response_model=User)
def read_user_me(current_user: User = Depends(get_current_user)):
    """Get information about the current user."""
    return current_user

if __name__ == "__main__":
    print("Starting FastAPI example app...")
    print("Access the API docs at http://localhost:8001/docs")
    uvicorn.run(app, host="0.0.0.0", port=8001)
