# TurboAPI v1.0 — LinkedIn Post

**Best posting times:**
- Tuesday–Thursday, 7–9 AM PST (US professional morning)
- Tuesday 10 AM PST is the single best slot for dev content on LinkedIn
- Avoid Monday (inbox overload) and Friday (checked out)

---

## Post

**I rebuilt FastAPI's HTTP core in Zig. It's 22x faster.**

FastAPI is the best Python API framework to *write*. But every request flows through:

-> uvicorn -> ASGI -> Starlette -> json.loads -> your handler -> json.dumps -> response

Six layers of Python. GIL-serialized.

**TurboAPI replaces everything below your handler with Zig.**

Same decorators. Same `@app.get()`. Same Depends(). Same Pydantic-style models. Your code doesn't change -- just swap the import:

```python
from turboapi import TurboAPI  # that's it
app = TurboAPI()

@app.post("/users")
def create_user(user: UserModel):
    return {"id": 1, "user": user.model_dump()}
```

**What Zig does under the hood:**

At startup, TurboAPI classifies each route and assigns the lightest dispatch path:

- `simple_sync_noargs` -- response cached after first call, subsequent requests skip Python entirely (150k req/s)
- `simple_sync` -- Zig assembles args via vectorcall, no kwargs dict (143k req/s)
- `model_sync` -- Zig parses + validates JSON before touching Python, single-parse pipeline (124k req/s)
- `static_route` -- response pre-rendered at startup, single writeAll (149k req/s)

**The numbers (Python 3.14 free-threading, wrk 4t/100c/10s, M3 Pro):**

| | TurboAPI | FastAPI |
|---|---|---|
| Req/sec (GET) | 150,000 | 6,847 |
| Req/sec (POST) | 124,000 | 8,200 |
| Avg latency | 0.15ms | 14.6ms |
| CORS overhead | 0% (Zig-native) | N/A |
| JSON parsing | Zig (0 Python calls) | json.loads |
| Validation | Zig-native (dhi) | Pydantic |

**275 tests passing.** FastAPI parity on routing, path params, query params, security (OAuth2, HTTPBearer, APIKey), middleware (CORS, GZip), Depends(), background tasks, response types.

**What's different from just using uvloop/orjson/etc:**

Those optimize within Python. TurboAPI moves the entire HTTP layer *out* of Python. The Zig server handles TCP, HTTP parsing, routing, JSON, validation, and CORS -- Python only runs your business logic.

**Key optimizations in this release:**
- Zero-alloc response pipeline (stack buffers, no heap allocs per request)
- Zig-native CORS (headers pre-rendered once, 0% overhead vs 24% with Python middleware)
- Response caching for noargs handlers (Python called once, cached forever)
- Zero-alloc route params (stack array replaces HashMap)
- Fuzz-tested HTTP parser, router, and JSON validator
- 10 security bugs fixed from community audit

**Stack:**
- Zig 0.15 HTTP core (24-thread pool, keep-alive, radix-trie router)
- dhi for Pydantic-compatible validation (Zig-native)
- Python 3.14 free-threading (no GIL)

Still alpha. WebSocket and HTTP/2 are next.

github.com/justrach/turboAPI

#python #zig #webdev #fastapi #performance #opensource

---

## Alt: Short version (for higher engagement)

**I replaced FastAPI's HTTP core with Zig. Same API. 22x faster.**

Every request in FastAPI flows through 6 layers of Python. GIL-serialized.

TurboAPI moves HTTP, JSON parsing, validation, and CORS into Zig. Python only runs your business logic.

Results (Python 3.14 free-threading, M3 Pro):
- 150,000 req/s vs 6,847 (FastAPI)
- 0.15ms latency vs 14.6ms
- CORS at 0% overhead (Zig-native, pre-rendered headers)
- 275 tests passing, drop-in compatible

Your FastAPI code works unchanged -- just swap the import.

github.com/justrach/turboAPI

#python #zig #opensource
