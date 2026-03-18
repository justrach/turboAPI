# TurboAPI - Twitter/X Thread

**Best times to post (PST):** Tue-Thu, 8-10 AM
**Best times to post (SGT):** Tue-Thu, 11 PM - 1 AM

---

## Tweet 1 (Hook)

I replaced FastAPI's entire HTTP core with Zig.

Same decorator API. Same Pydantic models. 7× faster.

47,832 req/s vs FastAPI's 6,800. 2.09ms p50 latency.

It's called TurboAPI. Here's the story 👇

---

## Tweet 2 (The problem)

FastAPI is beautiful to write. But every single request goes:

uvicorn → ASGI → Starlette → your handler

JSON parsed in Python. Response serialized in Python. GIL held throughout.

At inference-serving scale, this hurts.

---

## Tweet 3 (The idea)

What if the HTTP server, routing, JSON parsing, and validation all happened in Zig - before Python even wakes up?

The handler path gets classified at startup:

```
simple_sync  → Zig writes directly to socket
model_sync   → Zig parses + validates, no json.loads()
body_sync    → params extracted in Zig
enhanced     → full Depends/middleware (still fast)
```

Your code doesn't change. TurboAPI picks the optimal path.

---

## Tweet 4 (Drop-in)

```python
# was:
from fastapi import FastAPI
app = FastAPI()

# now:
from turboapi import TurboAPI
app = TurboAPI()
```

That's the migration.

Same routes. Same Pydantic models. Same OpenAPI docs at /docs.
253 tests passing against FastAPI's test suite.

---

## Tweet 5 (Numbers)

```
Metric         TurboAPI   FastAPI    Delta
-----------    --------   -------    ------
Req/sec        47,832     6,800      +7x
p50 latency    2.09ms     14.3ms     -85%
p99 latency    5ms        89ms       -94%
Memory         12MB       89MB       -87%
```

Benchmarked on Apple M3 Pro, Python 3.14t (free-threading).

---

## Tweet 6 (Stack)

Under the hood:

- Zig HTTP server - zero-copy request parsing
- dhi - Zig-native validation (Pydantic drop-in, 2× faster)
- Python 3.14 free-threading - true parallelism, no GIL
- One binary. No Rust. No Node. No maturin.

`pip install turboapi` - that's it.

---

## Tweet 7 (Status + CTA)

Still alpha. WebSocket and HTTP/2 in progress.

But the core is real and the numbers are real.

If you're building inference endpoints, high-throughput APIs, or just tired of Python bottlenecks:

⭐ github.com/justrach/turboAPI
📖 turboapi.trilok.ai

---

## Alt: Single tweet

I replaced FastAPI's HTTP core with Zig.

Same API. Same Pydantic models. 7× faster.

47,832 req/s. 2.09ms p50. 253 tests passing.

`from turboapi import TurboAPI` - that's the migration.

github.com/justrach/turboAPI
