# TurboAPI v1.0.0 — Twitter/X Thread

**Best posting times (PST):**
- Tuesday–Thursday, 8–10 AM PST (catches US morning + EU afternoon)
- Monday 9 AM PST (week-start dev energy)
- Avoid Friday/weekend for dev content

**Best posting times (SGT):**
- Tuesday–Thursday, 11 PM – 1 AM SGT (= 8–10 AM PST)
- Or post 8–9 AM SGT for Asian dev audience first, US catches up

---

## Tweet 1 (Hook)

FastAPI processes every request through Python. Every. Single. One.

So I replaced the entire HTTP core with Zig. Same API. 7x faster.

It's called TurboAPI.

`pip install turboapi` and your FastAPI code runs unchanged.

Here's how 👇

---

## Tweet 2 (The problem)

FastAPI is amazing to write. But under the hood:

- uvicorn → ASGI → Starlette → your handler
- json.loads() on every request
- json.dumps() on every response  
- GIL serializes all of it

What if the HTTP server, JSON parsing, and validation all happened in Zig — before Python even wakes up?

---

## Tweet 3 (Architecture)

Handler classification at startup. Each route gets the lightest path:

```
simple_sync  → zero-copy, Zig writes directly to socket
model_sync   → Zig parses JSON, validates schema, no json.loads
body_sync    → body params extracted in Zig
enhanced     → full Depends/middleware (still fast)
```

Your code doesn't change. The framework figures out the optimal path.

---

## Tweet 4 (Numbers)

The numbers:

- Req/sec: 71,000 (FastAPI: 10,000)
- Latency: 1.4ms avg (FastAPI: 10.2ms)
- JSON parsing: 0 Python calls (Zig std.json)
- Validation: Zig-native via dhi (2x faster than Pydantic)
- Thread pool: 8 Zig workers, no GIL

Python 3.14 free-threading. True parallelism.

---

## Tweet 5 (Drop-in replacement)

```python
# This is valid TurboAPI code.
# It's also valid FastAPI code.

from turboapi import TurboAPI  # just change this import

app = TurboAPI()

@app.get("/users/{user_id}")
def get_user(user_id: int):
    return {"id": user_id, "name": "Rach"}

@app.post("/items")
def create_item(item: Item):
    return {"item": item.model_dump()}
```

253 tests passing. FastAPI parity on routing, security, middleware, Depends, OpenAPI.

---

## Tweet 6 (The dhi connection)

Validation uses dhi — our Zig-native Pydantic replacement.

```python
from dhi import BaseModel, Field

class User(BaseModel):
    name: str = Field(min_length=1)
    age: int = Field(ge=0)
```

Schema gets compiled to Zig at startup. Validation runs before the GIL is even acquired. Invalid requests never touch Python.

---

## Tweet 7 (Build system)

Zero Node.js. Zero Cargo. Zero maturin.

```bash
# Build
python3.14t zig/build_turbonet.py --install

# Pre-commit hook
make hooks   # ruff lint + zig compile check

# Test
make test    # 253 tests
```

One Zig binary. One Python package. That's it.

---

## Tweet 8 (CTA)

Still alpha. WebSocket and HTTP/2 coming.

But 253 tests pass. FastAPI parity is real. And it's 7x faster.

Python 3.14+ free-threading required.

⭐ github.com/justrach/turboAPI
📦 pip install turboapi

Built with @AmpCodeHQ and @OpenAIDevs codex.

(via Devswarm — github.com/justrach/devswarm)

---

## Alt: Single tweet (if not doing a thread)

FastAPI processes every HTTP request through Python.

I replaced the entire core with Zig. Same decorator API. 7x faster. 253 tests passing.

`from turboapi import TurboAPI` — drop-in replacement.

Python 3.14 free-threading + Zig HTTP core = 71K req/s.

github.com/justrach/turboAPI
