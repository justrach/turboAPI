# Tatsat Framework Routes Guide

This document provides a comprehensive overview of the route patterns and functionality available in the Tatsat framework, based on the examples in this project.

## Table of Contents
- [Basic Routes](#basic-routes)
- [Item Management Routes](#item-management-routes)
- [User Routes](#user-routes)
- [Advanced Routes](#advanced-routes)
- [Product Routes](#product-routes)
- [Authentication Routes](#authentication-routes)
- [Custom Request Handling](#custom-request-handling)
- [Route Organization with APIRouter](#route-organization-with-apirouter)
- [Best Practices](#best-practices)

## Basic Routes

### Root Endpoint
```python
@app.get("/")
def read_root():
    return {"message": "Welcome to Tatsat API"}
```
Returns a welcome message. This is the simplest route possible and serves as an entry point to your API.

## Item Management Routes

### Get Multiple Items
```python
@app.get("/items/", response_model=List[Item])
def read_items(skip: int = 0, limit: int = 10, db=Depends(get_db)):
    """
    Get a list of items.
    
    - **skip**: Number of items to skip
    - **limit**: Maximum number of items to return
    """
    items = list(db["items"].values())
    return items[skip : skip + limit]
```
Retrieves a paginated list of items from the database.

### Get Single Item
```python
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
```
Retrieves a single item by its ID, with optional query parameter support.

### Create Item
```python
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
```
Creates a new item with validation using Satya models.

### Update Item
```python
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
```
Updates an existing item with new data, maintaining the same ID.

### Delete Item
```python
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
```
Deletes an item by its ID.

## User Routes

### Get Current User
```python
@app.get("/users/me", response_model=User)
def read_user_me(current_user: User = Depends(get_current_user)):
    """Get information about the current user."""
    return current_user
```
Returns information about the currently authenticated user.

### Get All Users (Admin Only)
```python
@app.get("/api/v1/users/", response_model=List[User])
def get_users(
    skip: int = 0,
    limit: int = 10,
    current_user: User = Depends(check_admin_role)
):
    """
    Get a list of all users (admin only).
    """
    users = list(users_db.values())
    return users[skip : skip + limit]
```
Returns a list of all users, restricted to admin users only.

## Advanced Routes

## Product Routes

### Get Products
```python
@app.get("/api/v1/products/", response_model=List[Product])
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
        
    return products[skip : skip + limit]
```
Returns a filtered list of products with pagination and category filtering.

### Get Product
```python
@app.get("/api/v1/products/{product_id}", response_model=Product)
def get_product(product_id: int = Path(..., ge=1, description="The ID of the product to get")):
    """
    Get details about a specific product.
    """
    if product_id not in products_db:
        raise HTTPException(status_code=404, detail="Product not found")
        
    return products_db[product_id]
```
Returns details about a specific product by its ID.

### Create Product (Admin Only)
```python
@app.post("/api/v1/products/", response_model=Product, status_code=201)
def create_product(
    product: Product,
    current_user: User = Depends(check_admin_role)
):
    """
    Create a new product (admin only).
    """
    # Generate a new ID
    product_id = max(products_db.keys()) + 1 if products_db else 1
    
    # Create a new product with the generated ID
    product_dict = product.to_dict()
    product_dict["id"] = product_id
    
    # Store the product in the database
    products_db[product_id] = product_dict
    
    return product_dict
```
Creates a new product, restricted to admin users only.

### Update Product (Admin Only)
```python
@app.put("/api/v1/products/{product_id}", response_model=Product)
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
```
Updates an existing product, restricted to admin users only.

### Delete Product (Admin Only)
```python
@app.delete("/api/v1/products/{product_id}", status_code=204)
def delete_product(
    product_id: int,
    current_user: User = Depends(check_admin_role)
):
    """
    Delete a product (admin only).
    """
    if product_id not in products_db:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Delete the product
    del products_db[product_id]
    
    return Response(status_code=204)
```
Deletes a product, restricted to admin users only.

## Authentication Routes

### Login
```python
@app.post("/api/v1/login", response_model=Token)
def login(username: str = Body(...), password: str = Body(...)):
    """
    Generate an access token for a user.
    
    This is a simplified example and does not implement real authentication.
    In a real application, you'd verify credentials against a database.
    """
    # In a real app, verify the username and password against a database
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
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
```
Generates an authentication token based on username and password.

## Custom Request Handling

### Echo Request
```python
@app.post("/api/v1/echo")
async def echo(request: Request):
    """
    Echo back the request body.
    """
    body = await request.json()
    return {
        "method": request.method,
        "url": str(request.url),
        "headers": dict(request.headers),
        "body": body,
    }
```
Demonstrates how to access and manipulate the raw request object.

## Route Organization with APIRouter

Tatsat supports organizing routes using the `APIRouter` class, similar to FastAPI:

```python
# Create API routers for organization
router = APIRouter(prefix="/api/v1")

# Add routes to the router
@router.get("/products/")
def get_products():
    # ...

# Include the router in the main app
app.include_router(router)
```

This allows you to:
- Group related routes together
- Add common prefixes to routes
- Apply common dependencies to groups of routes
- Keep code organized in large applications

## Best Practices

### Path Parameters
Use path parameters for required values that identify a specific resource:

```python
@app.get("/items/{item_id}")
def read_item(item_id: int):
    # ...
```

### Query Parameters
Use query parameters for optional filters, pagination, or sorting:

```python
@app.get("/items/")
def read_items(skip: int = 0, limit: int = 10, sort_by: Optional[str] = None):
    # ...
```

### Status Codes
Use appropriate status codes for different actions:

```python
@app.post("/items/", status_code=201)  # Created
def create_item(item: Item):
    # ...

@app.delete("/items/{item_id}", status_code=204)  # No Content
def delete_item(item_id: int):
    # ...
```

### Response Models
Always specify response models when possible to ensure type safety and documentation:

```python
@app.get("/items/{item_id}", response_model=Item)
def read_item(item_id: int):
    # ...
```

### Dependency Injection
Use dependency injection for database access, authentication, and other shared functionality:

```python
@app.get("/items/", response_model=List[Item])
def read_items(db=Depends(get_db), current_user=Depends(get_current_user)):
    # ...
```

### Request Validation
Always use Satya models for request validation to ensure data integrity:

```python
@app.post("/items/", response_model=Item)
def create_item(item: Item):
    # item is already validated thanks to Satya
    # ...
```
