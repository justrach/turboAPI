# TurboAPI v0.5 — Twitter/X Thread

**Best times to post (PST):** Tue-Thu, 8-10 AM
**Best times to post (SGT):** Tue-Thu, 11 PM - 1 AM

---

## Tweet 1 (Hook)

TurboAPI update: 47k → 139k req/s.

Same decorator API. Same Pydantic models. Now 20× faster than FastAPI.

Three changes inside the Zig core. Here's what happened 👇

---

## Tweet 2 (What changed)

**1. Per-worker PyThreadState**

Old: every request called PyGILState_Ensure → OS thread lookup → acquire GIL

New: each of 24 worker threads creates ONE tstate at startup, reuses it every request via PyEval_AcquireThread

Result: zero per-request thread-state allocation

---

## Tweet 3 (PyObject_CallNoArgs)

**2. PyObject_CallNoArgs for zero-arg handlers**

```python
@app.get("/ping")
def ping():
    return {"ok": True}
```

Old: PyTuple_New(0) + PyDict_New() + PyObject_Call
New: PyObject_CallNoArgs — single CPython call, no allocations

TurboAPI detects at startup if your handler takes zero params and routes to the fast path automatically.

---

## Tweet 4 (Tuple ABI)

**3. Tuple response ABI**

Old: Python handler returned a dict → 3× PyDict_GetItemString (hash + lookup per field)

New: Python returns `(status_code, content_type, body_str)` → 3× PyTuple_GetItem (direct index, no hashing)

Your code doesn't change. The fast wrapper is generated automatically.

---

## Tweet 5 (Numbers)

```
Metric          TurboAPI v0.5   FastAPI     Delta
------------    -------------   --------    ------
Req/sec         139,350         6,847       +20x
Avg latency     0.16ms          14.6ms      -99%
p50 latency     0.14ms          14.3ms      -99%
Memory          12MB            89MB        -87%
```

Benchmarked: M3 Pro, Python 3.14t, wrk 4t/100c/8s.

---

## Tweet 6 (How it works now)

At startup, TurboAPI classifies every route:

```
simple_sync_noargs → PyObject_CallNoArgs + tuple ABI
simple_sync        → path params resolved in Zig + tuple ABI
model_sync         → JSON parsed in Zig + tuple ABI
enhanced           → full Depends/middleware
```

Python only runs your business logic. Everything else stays in Zig.

---

## Tweet 7 (Drop-in reminder)

Still just:

```python
from turboapi import TurboAPI
app = TurboAPI()

@app.get("/ping")
def ping():
    return {"ok": True}
```

No annotations. No config. No rewrite.

---

## Tweet 8 (CTA)

⭐ github.com/justrach/turboAPI
📖 turboapi.trilok.ai

Still alpha. But 139k req/s is real.

---

## Alt: Single tweet

TurboAPI hit 139k req/s.

20× faster than FastAPI. 0.16ms avg latency.

Three changes: per-worker tstate, PyObject_CallNoArgs, tuple response ABI.

Same `from turboapi import TurboAPI` migration.

github.com/justrach/turboAPI
