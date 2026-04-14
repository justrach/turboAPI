---
name: turbo-route
description: Scaffold a new TurboAPI route with handler, model, and tests. Use when adding a new API endpoint, creating a new route, or scaffolding CRUD for a resource.
argument-hint: <resource-name> [GET|POST|PUT|DELETE]
---

# Scaffold a TurboAPI Route

Create a new route for the TurboAPI application based on the resource name and HTTP method.

## Steps

1. **Determine the resource**: Use `$ARGUMENTS[0]` as the resource name (e.g., `users`, `items`, `orders`)
2. **Determine the method**: Use `$ARGUMENTS[1]` if provided, otherwise scaffold all CRUD methods (GET, POST, PUT, DELETE)
3. **Check existing routes**: Read `python/turboapi/zig_integration.py` to understand the current route registration pattern
4. **Create the model**: If it's a POST/PUT route, create a dhi BaseModel for the request body

## Template

For each route, generate code following this pattern:

```python
from turboapi import TurboAPI
from dhi import BaseModel, Field

app = TurboAPI()

class {Resource}(BaseModel):
    # fields based on resource name
    name: str = Field(min_length=1, max_length=100)

@app.get("/{resource_plural}")
def list_{resource_plural}():
    return {"{resource_plural}": []}

@app.get("/{resource_plural}/{{{resource}_id}}")
def get_{resource}({resource}_id: int):
    return {"{resource}_id": {resource}_id}

@app.post("/{resource_plural}")
def create_{resource}({resource}: {Resource}):
    return {"{resource}": {resource}.model_dump(), "created": True}

@app.delete("/{resource_plural}/{{{resource}_id}}")
def delete_{resource}({resource}_id: int):
    return {"deleted": True}
```

## Also generate a test file

Create `tests/test_{resource_plural}.py` with TestClient-based tests for each endpoint. Include both success and error cases.

## Handler classification

When creating routes, note which Zig dispatch path they'll use:
- No params, sync → `simple_sync_noargs` (fastest, cached)
- Path/query params, sync → `simple_sync` (vectorcall)
- Body with dhi model → `model_sync` (Zig-native validation)
- `Depends()` or middleware → `enhanced` (full Python)
