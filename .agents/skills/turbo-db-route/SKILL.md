---
name: turbo-db-route
description: Scaffold Zig-native database routes using pg.zig + TurboPG. Use when adding database-backed CRUD endpoints, custom SQL queries (pgvector, JSONB, full-text search, JOINs, CTEs), or standalone TurboPG usage.
argument-hint: <table-name> [crud|query|standalone]
---

# Scaffold a Zig-Native DB Route

Create database routes that execute entirely in Zig — no Python, no GIL.
Supports CRUD auto-generation, custom SQL, and standalone TurboPG usage.

## Steps

1. **Determine the table**: Use `$ARGUMENTS[0]` as the table name
2. **Determine the mode**: `$ARGUMENTS[1]` — `crud` (default), `query` for custom SQL, or `standalone` for TurboPG
3. **Ensure `configure_db` is called** before any db routes

## CRUD mode (auto-generated SQL)

```python
from turboapi import TurboAPI
from dhi import BaseModel, Field

app = TurboAPI()
app.configure_db("postgres://user:pass@localhost/mydb", pool_size=16)

class User(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str
    age: int = Field(gt=0)

@app.db_get("/users/{user_id}", table="users", pk="id")
def get_user(): pass

@app.db_list("/users", table="users")
def list_users(): pass

@app.db_post("/users", table="users", model=User)
def create_user(): pass

@app.db_delete("/users/{user_id}", table="users", pk="id")
def delete_user(): pass
```

## Custom query mode (any SQL — pgvector, JSONB, FTS, JOINs, CTEs)

```python
# Full-text search
@app.db_query("GET", "/search", sql="""
    SELECT id, title, ts_rank(tsv, plainto_tsquery('english', $1)) AS rank
    FROM articles WHERE tsv @@ plainto_tsquery('english', $1)
    ORDER BY rank DESC LIMIT $2
""", params=["q", "limit"])
def search(): pass

# pgvector nearest neighbors
@app.db_query("GET", "/similar/{item_id}", sql="""
    SELECT id, name, 1 - (embedding <=> (SELECT embedding FROM items WHERE id = $1)) AS sim
    FROM items ORDER BY embedding <=> (SELECT embedding FROM items WHERE id = $1) LIMIT $2
""", params=["item_id", "limit"])
def similar(): pass

# JSONB filter
@app.db_query("GET", "/admins", sql="""
    SELECT id, name, metadata->>'plan' AS plan
    FROM users WHERE metadata @> '{"role": "admin", "active": true}'
""")
def admins(): pass

# Multi-table JOIN + aggregation
@app.db_query("GET", "/users/{user_id}/stats", sql="""
    SELECT u.name, count(DISTINCT p.id) AS posts, sum(o.total) AS revenue
    FROM users u LEFT JOIN posts p ON u.id = p.user_id
    LEFT JOIN orders o ON u.id = o.user_id WHERE u.id = $1
    GROUP BY u.name
""", params=["user_id"], single=True)
def user_stats(): pass

# Array column query
@app.db_query("GET", "/posts/tagged", sql="""
    SELECT id, title, tags FROM posts WHERE $1 = ANY(tags) LIMIT 10
""", params=["tag"])
def tagged(): pass
```

## Standalone TurboPG mode (no TurboAPI needed)

```python
from turbopg import Database

db = Database("postgres://user:pass@localhost/mydb")

users = db.query("SELECT * FROM users WHERE age > $1 LIMIT $2", [18, 10])
user = db.query_one("SELECT * FROM users WHERE id = $1", [42])
affected = db.execute("INSERT INTO users (name, email) VALUES ($1, $2)", ["Alice", "a@b.com"])

with Database("postgres://...") as db:
    result = db.query("SELECT count(*) as n FROM users")
```

## Performance notes

- **Cached reads**: ~130k req/s (30s TTL, per-table invalidation, thread-safe, LRU)
- **Writes invalidate cache**: POST/DELETE clear only the affected table's cache entries
- **Prepared statements**: auto-enabled, skip SQL parse on repeat queries
- **Unix sockets**: use `host=/var/run/postgresql` for ~50% less latency
- **SIMD**: JSON string escaping uses @Vector(16, u8) for bulk copy
- **pgvector**: SIMD float32 batch decode, auto-detected in results
- **All Postgres types**: int, float, numeric, bool, JSON/JSONB, TEXT[], INT[], timestamps

## Type support via pg.zig fork (justrach/pg.zig)

The forked pg.zig includes `writeJsonRow()` which handles every Postgres type:
- Integers (int2/int4/int8) → JSON numbers
- Floats (float4/float8) → JSON numbers  
- Numeric/Decimal → f64
- Bool → true/false
- JSON → passthrough
- JSONB → nested JSON objects (not escaped strings)
- TEXT[] → `["a", "b"]`
- INT[] → `[1, 2, 3]`
- Timestamps → epoch strings
- pgvector → `[0.1, 0.2, 0.3]`
