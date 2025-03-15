"""
TurboAPI vs FastAPI Comparison Example.

This example demonstrates the key differences between TurboAPI and FastAPI:
- Performance comparison
- Syntax similarities and differences
- Validation approaches
- Middleware implementation
- Dependency injection patterns

Both frameworks are implemented side-by-side for easy comparison.
"""

import sys
import os
import time
from typing import List, Optional, Dict, Any
from datetime import datetime
import asyncio

# Add the parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    # Import TurboAPI
    from turboapi import (
        TurboAPI, APIRouter as TurboAPIRouter, 
        Depends as TurboDepends, 
        HTTPException as TurboHTTPException
    )
    
    # Import FastAPI (if available)
    from fastapi import (
        FastAPI, APIRouter as FastAPIRouter, 
        Depends as FastDepends, 
        HTTPException as FastHTTPException
    )
    
    # Import validation libraries
    from satya import Model as SatyaModel, Field as SatyaField
    from pydantic import BaseModel as PydanticModel, Field as PydanticField
    
    FASTAPI_AVAILABLE = True
except ImportError:
    print("FastAPI and/or Pydantic not installed. Only TurboAPI examples will work.")
    FASTAPI_AVAILABLE = False

# Define data models
# TurboAPI uses Satya for validation
class TurboItem(SatyaModel):
    id: Optional[int] = SatyaField(required=False)
    name: str = SatyaField(min_length=1)
    description: Optional[str] = SatyaField(required=False)
    price: float = SatyaField(gt=0)
    tags: List[str] = SatyaField(default=[])
    created_at: datetime = SatyaField(default=datetime.now())

# FastAPI uses Pydantic for validation
if FASTAPI_AVAILABLE:
    class FastItem(PydanticModel):
        id: Optional[int] = None
        name: str
        description: Optional[str] = None
        price: float = PydanticField(gt=0)
        tags: List[str] = []
        created_at: datetime = PydanticField(default_factory=datetime.now)

# In-memory database
items_db = {
    1: {
        "id": 1,
        "name": "Example Item",
        "description": "This is an example item",
        "price": 42.99,
        "tags": ["example", "item"],
        "created_at": datetime.now().isoformat()
    }
}

# Create applications
turbo_app = TurboAPI(
    title="TurboAPI Example",
    description="TurboAPI side of the comparison",
    version="1.0.0"
)

if FASTAPI_AVAILABLE:
    fast_app = FastAPI(
        title="FastAPI Example",
        description="FastAPI side of the comparison",
        version="1.0.0"
    )

# Middleware example for timing requests
@turbo_app.middleware("http")
async def turbo_timing_middleware(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response

if FASTAPI_AVAILABLE:
    @fast_app.middleware("http")
    async def fast_timing_middleware(request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        return response

# Dependencies
def turbo_get_item_from_db(item_id: int):
    if item_id not in items_db:
        raise TurboHTTPException(status_code=404, detail="Item not found")
    return items_db[item_id]

if FASTAPI_AVAILABLE:
    def fast_get_item_from_db(item_id: int):
        if item_id not in items_db:
            raise FastHTTPException(status_code=404, detail="Item not found")
        return items_db[item_id]

# TurboAPI Routes
@turbo_app.get("/")
def turbo_read_root():
    return {"message": "Hello from TurboAPI!", "framework": "TurboAPI"}

@turbo_app.get("/items", response_model=List[TurboItem])
def turbo_read_items(skip: int = 0, limit: int = 10):
    items = list(items_db.values())
    return items[skip:skip+limit]

@turbo_app.get("/items/{item_id}", response_model=TurboItem)
def turbo_read_item(item_id: int, item = TurboDepends(turbo_get_item_from_db)):
    return item

@turbo_app.post("/items", response_model=TurboItem)
def turbo_create_item(item: TurboItem):
    item_dict = item.to_dict()
    if not item_dict.get("id"):
        item_id = max(items_db.keys()) + 1 if items_db else 1
        item_dict["id"] = item_id
    
    # Convert datetime to ISO format for storage
    if isinstance(item_dict["created_at"], datetime):
        item_dict["created_at"] = item_dict["created_at"].isoformat()
    
    items_db[item_dict["id"]] = item_dict
    return item_dict

@turbo_app.put("/items/{item_id}", response_model=TurboItem)
def turbo_update_item(item_id: int, item: TurboItem):
    if item_id not in items_db:
        raise TurboHTTPException(status_code=404, detail="Item not found")
    
    item_dict = item.to_dict()
    item_dict["id"] = item_id
    
    # Convert datetime to ISO format for storage
    if isinstance(item_dict["created_at"], datetime):
        item_dict["created_at"] = item_dict["created_at"].isoformat()
    
    items_db[item_id] = item_dict
    return item_dict

@turbo_app.delete("/items/{item_id}")
def turbo_delete_item(item_id: int):
    if item_id not in items_db:
        raise TurboHTTPException(status_code=404, detail="Item not found")
    
    del items_db[item_id]
    return {"message": "Item deleted"}

# FastAPI Routes (only if FastAPI is available)
if FASTAPI_AVAILABLE:
    @fast_app.get("/")
    def fast_read_root():
        return {"message": "Hello from FastAPI!", "framework": "FastAPI"}
    
    @fast_app.get("/items", response_model=List[FastItem])
    def fast_read_items(skip: int = 0, limit: int = 10):
        items = list(items_db.values())
        return items[skip:skip+limit]
    
    @fast_app.get("/items/{item_id}", response_model=FastItem)
    def fast_read_item(item = FastDepends(fast_get_item_from_db)):
        return item
    
    @fast_app.post("/items", response_model=FastItem)
    def fast_create_item(item: FastItem):
        item_dict = item.model_dump()
        if not item_dict.get("id"):
            item_id = max(items_db.keys()) + 1 if items_db else 1
            item_dict["id"] = item_id
        
        # Convert datetime to ISO format for storage
        if isinstance(item_dict["created_at"], datetime):
            item_dict["created_at"] = item_dict["created_at"].isoformat()
        
        items_db[item_dict["id"]] = item_dict
        return item_dict
    
    @fast_app.put("/items/{item_id}", response_model=FastItem)
    def fast_update_item(item_id: int, item: FastItem):
        if item_id not in items_db:
            raise FastHTTPException(status_code=404, detail="Item not found")
        
        item_dict = item.model_dump()
        item_dict["id"] = item_id
        
        # Convert datetime to ISO format for storage
        if isinstance(item_dict["created_at"], datetime):
            item_dict["created_at"] = item_dict["created_at"].isoformat()
        
        items_db[item_id] = item_dict
        return item_dict
    
    @fast_app.delete("/items/{item_id}")
    def fast_delete_item(item_id: int):
        if item_id not in items_db:
            raise FastHTTPException(status_code=404, detail="Item not found")
        
        del items_db[item_id]
        return {"message": "Item deleted"}

# Run both applications with different ports
def start_turbo_app():
    import uvicorn
    uvicorn.run(turbo_app, host="0.0.0.0", port=8000)

def start_fast_app():
    import uvicorn
    uvicorn.run(fast_app, host="0.0.0.0", port=8001)

if __name__ == "__main__":
    import multiprocessing
    
    # Print instructions
    print("\n=== TurboAPI vs FastAPI Comparison ===")
    
    if FASTAPI_AVAILABLE:
        print("\nBoth frameworks will be started:")
        print("- TurboAPI: http://localhost:8000")
        print("- FastAPI: http://localhost:8001")
        print("\nAccess the /docs endpoints to see the interactive API documentation:")
        print("- TurboAPI Docs: http://localhost:8000/docs")
        print("- FastAPI Docs: http://localhost:8001/docs")
        
        # Start both servers
        turbo_process = multiprocessing.Process(target=start_turbo_app)
        fast_process = multiprocessing.Process(target=start_fast_app)
        
        turbo_process.start()
        fast_process.start()
        
        try:
            # Wait for termination
            turbo_process.join()
            fast_process.join()
        except KeyboardInterrupt:
            print("\nShutting down servers...")
            turbo_process.terminate()
            fast_process.terminate()
    else:
        print("\nOnly TurboAPI will be started (FastAPI not available):")
        print("- TurboAPI: http://localhost:8000")
        print("\nAccess the /docs endpoint to see the interactive API documentation:")
        print("- TurboAPI Docs: http://localhost:8000/docs")
        
        # Start TurboAPI server
        start_turbo_app()
