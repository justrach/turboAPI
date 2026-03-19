# TurboAPI v0.5 — Twitter/X Thread

**Best times to post (PST):** Tue-Thu, 8-10 AM
**Best times to post (SGT):** Tue-Thu, 11 PM - 1 AM

---

## Tweet 1 (Hook)

TurboAPI hit 150k req/s.

Same decorator API. Same Pydantic models. 22x faster than FastAPI.

Here's what changed since v0.4 👇

---

## Tweet 2 (Zero-alloc hot path)

**1. Zero allocations on the hot path**

Old: 2 heap allocs + 2 frees per response (header + concat buffer)
New: stack buffers only. Header formatted via bufPrint, body appended, single write syscall.

Route params: replaced StringHashMap with a fixed stack array. Zero allocator calls per request.

---

## Tweet 3 (Response caching)

**2. Response caching for noargs handlers**

```python
@app.get("/ping")
def ping():
    return {"ok": True}
```

First request: Python runs, response bytes cached in Zig.
Every request after: single writeAll from cache. Zero Python, zero GIL.

150k req/s — matching static routes.

---

## Tweet 4 (Zig-native CORS)

**3. CORS moved from Python to Zig**

Old: CORSMiddleware forced ALL routes to the slow "enhanced" path.
144k -> 110k. 24% overhead.

New: CORS headers pre-rendered once at startup, injected via memcpy.
144k -> 139k. ~0% overhead.

OPTIONS preflight handled in Zig before touching Python.

---

## Tweet 5 (Numbers)

```
Endpoint              TurboAPI     FastAPI     Delta
-----------------     ---------    --------    ------
GET / (cached)        150,000/s    6,847/s     +22x
GET /users/{id}       143,000/s    8,666/s     +16x
POST /items (dhi)     124,000/s    8,200/s     +15x
Static /health        149,000/s    —           pure Zig

Avg latency           0.15ms       14.6ms      -99%
CORS overhead         ~0%          N/A
```

M3 Pro, Python 3.14t, wrk 4t/100c/10s. 275 tests passing.

---

## Tweet 6 (Security)

Also fixed 10 security bugs from a community audit:
- Null terminator stack over-read in FFI
- Dangling pointers from Python string internals
- Integer truncation on port
- Rate limiter data race
- CORS wildcard + credentials violation
- Plaintext password hash placeholder

Full report: SECURITY.md

---

## Tweet 7 (Architecture)

At startup, TurboAPI classifies every route:

```
static_route       -> pre-rendered bytes, writeAll
simple_sync_noargs -> cached after 1st call
simple_sync        -> Zig vectorcall, no kwargs dict
model_sync         -> single JSON parse + dhi validation
enhanced           -> full Depends/middleware
```

Python only runs your business logic. Everything else stays in Zig.

---

## Tweet 8 (CTA)

github.com/justrach/turboAPI

150k req/s. 275 tests. Drop-in FastAPI replacement.

Still alpha — but the numbers are real.

---

## Alt: Single tweet

TurboAPI hit 150k req/s — 22x faster than FastAPI.

Zero heap allocs per request. Response caching. Zig-native CORS at 0% overhead.

Same `from turboapi import TurboAPI` migration. 275 tests passing.

github.com/justrach/turboAPI
