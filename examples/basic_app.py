"""
Basic Tatsat application example.

This example demonstrates the core features of Tatsat:
- Route definition with decorators
- Path and query parameters
- Request body validation with satya models
- Response validation
- Dependency injection
- Automatic documentation
"""

import sys
import os
from typing import List, Optional, Dict

# Add the parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import tatsat
from tatsat import Tatsat, Depends, HTTPException
from satya import Model, Field

# Create a Tatsat application
app = Tatsat(
    title="Tatsat Example API",
    description="A sample API showing Tatsat features with satya validation",
    version="0.1.0",
)

# Define satya models
class Item(Model):
    id: Optional[int] = Field(required=False)
    name: str = Field()
    description: Optional[str] = Field(required=False)
    price: float = Field(gt=0)
    tax: Optional[float] = Field(required=False)
    tags: List[str] = Field(default=[])

class User(Model):
    username: str = Field()
    email: str = Field()
    full_name: Optional[str] = Field(required=False)
    disabled: bool = Field(default=False)

# Simple in-memory database
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

# Define dependencies
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
    return {"message": "Welcome to Tatsat API"}

@app.get("/items/", response_model=List[Item])
def read_items(skip: int = 0, limit: int = 10, db=Depends(get_db)):
    """
    Get a list of items.
    
    - **skip**: Number of items to skip
    - **limit**: Maximum number of items to return
    """
    items = list(db["items"].values())
    return items[skip : skip + limit]

@app.get("/items/{item_id}", response_model=Item)
def read_item(item_id: int, q: Optional[str] = None, db=Depends(get_db)):
    """
    Get details about a specific item.
    
    - **item_id**: The ID of the item
    - **q**: Optional query parameter
    """
    if item_id not in db["items"]:
        raise HTTPException(status_code=404, detail="Item not found")
    
    item = db["items"][item_id]
    if q:
        item.update({"q": q})
    
    return item

@app.post("/items/", response_model=Item)
def create_item(item: Item, db=Depends(get_db)):
    """
    Create a new item.
    
    - **item**: The item data
    """
    # Generate a new ID
    item_id = max(db["items"].keys()) + 1 if db["items"] else 1
    
    # Create a new item with the generated ID
    item_dict = item.to_dict()
    item_dict["id"] = item_id
    
    # Store the item in the database
    db["items"][item_id] = item_dict
    
    return item_dict

@app.put("/items/{item_id}", response_model=Item)
def update_item(item_id: int, item: Item, db=Depends(get_db)):
    """
    Update an existing item.
    
    - **item_id**: The ID of the item to update
    - **item**: The updated item data
    """
    if item_id not in db["items"]:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Update the item
    item_dict = item.to_dict()
    item_dict["id"] = item_id
    db["items"][item_id] = item_dict
    
    return item_dict

@app.delete("/items/{item_id}")
def delete_item(item_id: int, db=Depends(get_db)):
    """
    Delete an item.
    
    - **item_id**: The ID of the item to delete
    """
    if item_id not in db["items"]:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Delete the item
    del db["items"][item_id]
    
    return {"detail": "Item deleted"}

@app.get("/users/me", response_model=User)
def read_user_me(current_user: User = Depends(get_current_user)):
    """Get information about the current user."""
    return current_user

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
