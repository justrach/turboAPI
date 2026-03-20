---
name: turbopg
description: Use TurboPG for standalone Postgres queries. Use when writing database code outside of TurboAPI routes, running migrations, seeding data, or building scripts that talk to Postgres.
---

# TurboPG — Standalone Postgres Client

TurboPG ships with TurboAPI and works independently for any Python Postgres work.

## Quick start

```python
from turbopg import Database

db = Database("postgres://user:pass@localhost/mydb", pool_size=16)

# Multiple rows
users = db.query("SELECT * FROM users WHERE age > $1 LIMIT $2", [18, 10])

# Single row (or None)
user = db.query_one("SELECT * FROM users WHERE id = $1", [42])

# Execute (INSERT/UPDATE/DELETE) — returns affected row count
db.execute("INSERT INTO users (name, email) VALUES ($1, $2)", ["Alice", "a@b.com"])
affected = db.execute("DELETE FROM users WHERE id = $1", [99])

# Context manager
with Database("postgres://...") as db:
    count = db.query_one("SELECT count(*) as n FROM users")
```

## Parameters

Use `$1`, `$2`, ... for parameterized queries (Postgres-native, SQL injection safe):

```python
db.query("SELECT * FROM users WHERE name = $1 AND age > $2", ["Alice", 18])
```

## Return types

- `query()` → `list[dict]` — each row as a dict with column names as keys
- `query_one()` → `dict | None` — first row or None
- `execute()` → `int` — number of affected rows
- Decimals → `float`, datetimes → ISO string, memoryview → decoded string

## Connection modes

1. **With TurboAPI installed**: Uses Zig pg.zig connection pool (zero overhead for TurboAPI db routes)
2. **Standalone**: Falls back to psycopg2/psycopg (requires `pip install psycopg2-binary`)

## Unix sockets

```python
db = Database("postgres://user:pass@/var/run/postgresql/mydb")
```

## With TurboAPI

TurboPG powers TurboAPI's `db_get`, `db_post`, `db_list`, `db_delete`, and `db_query` decorators. The Zig-native path runs the entire request cycle without Python.
