# TurboAPI v1.0.0 — LinkedIn Post

**Best posting times:**
- Tuesday–Thursday, 7–9 AM PST (US professional morning)
- Tuesday 10 AM PST is the single best slot for dev content on LinkedIn
- Avoid Monday (inbox overload) and Friday (checked out)

---

## Post

**I rebuilt FastAPI's HTTP core in Zig. It's 7x faster.**

FastAPI is the best Python API framework to *write*. But every request flows through:

→ uvicorn → ASGI → Starlette → json.loads → your handler → json.dumps → response

Six layers of Python. GIL-serialized.

**TurboAPI replaces everything below your handler with Zig.**

Same decorators. Same `@app.get()`. Same Depends(). Same Pydantic-style models. Your code doesn't change — just swap the import:

```python
from turboapi import TurboAPI  # that's it
app = TurboAPI()

@app.post("/users")
def create_user(user: UserModel):
    return {"id": 1, "user": user.model_dump()}
```

**What Zig does under the hood:**

At startup, TurboAPI classifies each route and assigns the lightest dispatch path:

• `simple_sync` — zero-copy response, Zig writes pre-serialized Python string directly to the socket
• `model_sync` — Zig parses JSON via std.json, validates against the schema, passes a Python dict (json.loads never runs)
• `enhanced` — full middleware/Depends support for complex routes

**The numbers (Python 3.14 free-threading, wrk 4t/100c/10s):**

| | TurboAPI | FastAPI |
|---|---|---|
| Req/sec | 71,000 | 10,000 |
| Avg latency | 1.4ms | 10.2ms |
| JSON parsing | Zig (0 Python calls) | json.loads |
| Validation | Zig-native (dhi) | Pydantic |
| Threading | True parallelism | GIL-serialized |

**253 tests passing.** FastAPI parity on routing, path params, query params, security (OAuth2, HTTPBearer, APIKey), middleware (CORS, GZip), Depends(), OpenAPI schema generation, background tasks, response types.

**What's different from just using uvloop/orjson/etc:**

Those optimize within Python. TurboAPI moves the entire HTTP layer *out* of Python. The Zig server handles TCP, HTTP parsing, routing, JSON, and validation — Python only runs your business logic.

**Stack:**
- Zig 0.15 HTTP core (8-thread pool, keep-alive, radix-trie router)
- dhi for Pydantic-compatible validation (Zig-native, 2x faster)  
- Python 3.14 free-threading (no GIL)
- Pre-commit hook: ruff lint + zig compile check

Still alpha. WebSocket and HTTP/2 are next.

⭐ https://github.com/justrach/turboAPI
📦 pip install turboapi (requires Python 3.14+)

Built with Amp and OpenAI Codex via Devswarm (https://github.com/justrach/devswarm)

#python #zig #webdev #fastapi #performance #opensource

---

## Alt: Short version (for higher engagement)

**I replaced FastAPI's HTTP core with Zig. Same API. 7x faster.**

Every request in FastAPI flows through 6 layers of Python. GIL-serialized.

TurboAPI moves HTTP, JSON parsing, and validation into Zig. Python only runs your business logic.

Results (Python 3.14 free-threading):
• 71,000 req/s vs 10,000 (FastAPI)
• 1.4ms latency vs 10.2ms
• 253 tests passing, drop-in compatible

Your FastAPI code works unchanged — just swap the import.

github.com/justrach/turboAPI

#python #zig #opensource
