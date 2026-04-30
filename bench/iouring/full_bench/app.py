"""Routes for io_uring vs blocking-accept A/B benchmarking.

Intentionally small. Each route does the minimum work that exercises a
different request path so we can check whether the accept-loop change
moves the needle for anything other than the trivial `/` noargs case.

Routes:
  GET /              noargs fast path (baseline)
  GET /user/{id}     path parameter — varied per request by wrk to
                     defeat any per-path lookup caching
  GET /q             query string — echoes a single ?id= param
"""

import os
import sys

from turboapi import TurboAPI

app = TurboAPI(title="iouring-bench")


@app.get("/")
def home():
    return {"ok": True}


@app.get("/user/{id}")
def get_user(id: str):
    return {"id": id}


@app.get("/q")
def get_q(id: str = "0"):
    return {"id": id}


# ~2 KB JSON body (50 records) — exercises more serializer + more bytes
# on the wire than the trivial routes above.
_ITEMS = [
    {"id": i, "name": f"item-{i}", "price": i * 1.5, "in_stock": (i % 3 == 0)}
    for i in range(50)
]


@app.get("/items")
def get_items():
    return {"items": _ITEMS}


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    print(f"[bench-app] starting on {host}:{port}", flush=True)
    sys.stdout.flush()
    app.run(host=host, port=port)
