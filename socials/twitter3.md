# TurboPG + TurboAPI — Twitter/X Thread

**Best times to post (PST):** Tue-Thu, 8-10 AM
**Best times to post (SGT):** Tue-Thu, 11 PM - 1 AM

---

## Tweet 1 (Hook — introduce TurboPG)

Introducing TurboPG — a Zig-native Postgres client for Python.

pip install turbopg

Use it standalone, or pair it with TurboAPI for zero-Python database routes. HTTP request hits Zig, Zig queries Postgres, Zig writes JSON. Python never touches the data.

128k req/s on DB routes. ~100x faster than FastAPI + SQLAlchemy.

---

## Tweet 2 (What is TurboPG)

TurboPG is two things:

1. A standalone Python package — `from turbopg import Database` — query Postgres with $1/$2 params, get dicts back. Works with psycopg2 fallback or Zig native.

2. The DB engine inside TurboAPI — when you use `@app.db_get()`, TurboPG's Zig core handles the entire request. No ORM. No serializer. No GIL.

Same library, two modes. Use what you need.

---

## Tweet 3 (The problem it solves)

FastAPI + SQLAlchemy on a simple SELECT by id:

request → Starlette → Pydantic → SQLAlchemy ORM → psycopg → Postgres → ORM hydrate → Pydantic serialize → JSON encode → response

That's 6 layers of Python on every single row.

TurboAPI + TurboPG:

request → Zig HTTP parse → pg.zig query → writeJsonRow → response

Zero Python. Zero GIL. One syscall out.

---

## Tweet 4 (The fork — credit + why)

pg.zig is Karl Seguin's excellent Postgres client for Zig. Connection pooling, prepared statements, binary protocol — all native.

But we needed things it didn't have. So we forked it:
https://github.com/justrach/pg.zig

Full credit to @karlseguin for the foundation. We built TurboPG on top of it.

---

## Tweet 5 (What we added to the fork)

What we changed in our pg.zig fork:

1. SIMD JSON escaping — @Vector(16, u8) bulk copy, only escapes when the mask fires. Strings go out ~4x faster than byte-at-a-time.

2. writeJsonRow() — takes a pg result row, writes a full JSON object directly. No intermediate allocations, no ORM, no serialize step.

3. pgvector support — binary decode with SIMD float32 batch loads. Vector columns come back as JSON arrays, ready for embedding APIs.

4. Full type coverage — int2/4/8, float4/8, bool, text, bytea, UUID, timestamps, numeric, arrays. One switch statement, zero Python.

---

## Tweet 6 (Numbers)

The numbers (Postgres 16, M3 Pro, wrk 4t/100c/10s):

Endpoint              TurboAPI+TurboPG  FastAPI+SQLAlchemy
-----------------------------------------------------
GET /users/:id        128,000/s         ~1,200/s
GET /users (list)     125,000/s         ~900/s
POST /users           118,000/s         ~1,100/s
custom SQL query      126,000/s         ~800/s

That's ~100x on real DB routes. Not a typo.

(With Zig-side response caching + prepared statements, cached reads hit 140k+)

---

## Tweet 7 (Production features)

This isn't a demo. Production features:

- Connection pooling (pg.zig native, not PgBouncer)
- Prepared statement cache (skip Parse on repeat queries)
- Response cache with TTL + per-table invalidation + LRU eviction at 10k entries
- Thread-safe mutex on all cache ops (24 Zig threads hitting it)
- Unix domain socket support (skip TCP for local Postgres)
- dhi validation runs pre-GIL — bad JSON rejected before Python wakes up

---

## Tweet 8 (Developer experience)

The Python API is still clean:

```python
from turbopg import Database
db = Database("postgres://localhost/mydb")
users = db.query("SELECT * FROM users WHERE age > $1", [18])
```

Or with TurboAPI (zero-Python hot path):

```python
@app.db_get("/users/{id}", table="users", pk="id")
async def get_user(): ...

@app.db_query("/search", sql="SELECT * FROM users WHERE name ILIKE $1")
async def search(q: str): ...
```

Decorators define the route. Zig handles HTTP + Postgres + JSON. Your handler body is optional — for simple CRUD, you don't even need one.

---

## Tweet 9 (CTA)

pip install turbopg
https://github.com/justrach/turboAPI
Fork: https://github.com/justrach/pg.zig

SQLAlchemy is great for prototyping. But if your bottleneck is the framework, not the database — maybe the framework should get out of the way.

Still experimental. PRs welcome.

---

## Alt: Single tweet

Introducing TurboPG — a Zig-native Postgres client for Python. Use standalone or with TurboAPI for zero-Python DB routes.

Forked @karlseguin's pg.zig, added SIMD JSON escaping + pgvector + writeJsonRow. 128k req/s on Postgres routes. ~100x faster than FastAPI + SQLAlchemy.

pip install turbopg
https://github.com/justrach/turboAPI
