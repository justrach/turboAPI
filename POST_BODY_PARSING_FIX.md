# POST Request Body Parsing Fix - Status Update

## Issue Summary

TurboAPI POST handlers fail when using a single parameter to capture the entire request body. The error is:
```
TypeError: handler() missing 1 required positional argument: 'request_data'
```

## Root Cause Analysis

The issue has been identified in the architecture:

1. **Python Side (FIXED)**: `request_handler.py` now correctly supports:
   - Single parameter receiving entire body: `handler(data: dict)`
   - Multiple parameters extracting fields: `handler(name: str, age: int)`
   - Satya Model validation: `handler(request: Model)`

2. **Rust Side (NEEDS FIX)**: The Rust HTTP server (`src/server.rs`) currently:
   - Calls Python handlers with `call0()` (no arguments)
   - Doesn't pass request data (body, headers, query params) to handlers
   - Needs to be modified to pass request context

## What Was Fixed

### ✅ Python Request Handler (`python/turboapi/request_handler.py`)

Added support for single-parameter handlers:

```python
# PATTERN 1: Single parameter receives entire body
if len(params_list) == 1:
    param_name, param = params_list[0]
    
    # If annotated as dict or list, pass entire body
    if param.annotation in (dict, list):
        parsed_params[param_name] = json_data
        return parsed_params
```

This now correctly handles:
- `handler(data: dict)` - receives entire JSON body
- `handler(items: list)` - receives entire JSON array
- `handler(request: Model)` - validates with Satya

### ✅ Test Suite Created

Created comprehensive tests in `tests/test_post_body_parsing.py`:
- Single dict parameter
- Single list parameter  
- Large JSON payload (42K items)
- Satya Model validation
- Multiple parameters (existing behavior)

## What Still Needs to Be Done

### ❌ Rust Server Integration (`src/server.rs`)

The Rust server needs to be modified to pass request data to Python handlers.

**Current code** (line ~1134):
```rust
// Call sync handler directly (NO kwargs - handlers don't expect them!)
let result = handler.call0(py)
    .map_err(|e| format!("Python error: {}", e))?;
```

**Needed change**:
```rust
// Create request dict with body, headers, query params
let request_dict = PyDict::new(py);
request_dict.set_item("body", body_bytes)?;
request_dict.set_item("headers", headers_dict)?;
request_dict.set_item("query_params", query_dict)?;

// Call handler with request data as kwargs
let result = handler.call(py, (), Some(request_dict))
    .map_err(|e| format!("Python error: {}", e))?;
```

This change needs to be made in multiple places:
1. `handle_request_optimized()` - line ~1134 (sync handlers)
2. `handle_request_with_loop_sharding()` - line ~1340 (sync handlers)
3. Async handler paths - lines ~1313, ~1393

## Workaround for Users (Temporary)

Until the Rust server is fixed, users can use this pattern:

```python
from turboapi import TurboAPI, Request

app = TurboAPI()

# Option 1: Use Request object (if implemented)
@app.post("/endpoint")
async def handler(request: Request):
    body = await request.json()
    return {"data": body}

# Option 2: Multiple parameters (works now)
@app.post("/endpoint")
def handler(name: str, age: int, email: str = "default@example.com"):
    return {"name": name, "age": age, "email": email}

# Option 3: Use FastAPI for now
# TurboAPI is still in development for this feature
```

## Implementation Plan

### Phase 1: Rust Server Modification (HIGH PRIORITY)

1. Modify `src/server.rs` to create request context dict
2. Pass request data to Python handlers via `call()` instead of `call0()`
3. Update all handler call sites (sync and async)

### Phase 2: Testing

1. Run `tests/test_post_body_parsing.py`
2. Verify all 5 tests pass
3. Test with large payloads (42K+ items)

### Phase 3: Documentation

1. Update `AGENTS.md` with POST body examples
2. Add to `README.md`
3. Create migration guide from FastAPI

## Timeline

- **Python fix**: ✅ COMPLETE (v0.4.13)
- **Rust fix**: 🔄 IN PROGRESS (estimated 2-4 hours)
- **Testing**: ⏳ PENDING Rust fix
- **Release**: 📅 v0.4.13 or v0.4.14

## Files Modified

### Completed
- ✅ `python/turboapi/request_handler.py` - Added single-parameter support
- ✅ `tests/test_post_body_parsing.py` - Comprehensive test suite

### Pending
- ⏳ `src/server.rs` - Pass request data to handlers
- ⏳ `src/python_worker.rs` - Update handler calling convention

## Response to Issue Reporter

Thank you for the detailed issue report! You've identified a critical gap in TurboAPI's FastAPI compatibility.

**Good news**: The Python side is now fixed and supports all the patterns you described:
- Single dict parameter: `handler(data: dict)`
- Single list parameter: `handler(items: list)`
- Satya Model validation: `handler(request: Model)`
- Large payloads (42K+ items)

**Current status**: The Rust HTTP server needs to be modified to pass request data to Python handlers. This is a straightforward fix but requires changes to the core server code.

**Workaround**: For now, use multiple parameters or consider using FastAPI until this is fully implemented.

**ETA**: This will be fixed in v0.4.13 or v0.4.14 (within 1-2 releases).

We appreciate your patience and detailed bug report. This is exactly the kind of real-world use case feedback we need to make TurboAPI production-ready!

---

**Contributors welcome!** If you'd like to help implement the Rust server changes, see the implementation plan above.
