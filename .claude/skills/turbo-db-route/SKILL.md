---
name: turbo-db-route
description: Scaffold a Zig-native database route using pg.zig. Use when adding database-backed CRUD endpoints, creating db_get/db_post/db_list/db_delete routes, or writing custom SQL queries with db_query.
argument-hint: <table-name> [crud|query]
---

# Scaffold a Zig-Native DB Route

Create database routes that execute entirely in Zig — no Python, no GIL.

## Steps

1. **Determine the table**: Use `$ARGUMENTS[0]` as the table name
2. **Determine the mode**: `$ARGUMENTS[1]` — `crud` (default) for auto-generated CRUD, or `query` for custom SQL
3. **Read the existing db route API**: Check `python/turboapi/zig_integration.py` for `db_get`, `db_post`, `db_list`, `db_delete`, `db_query`
4. **Ensure `configure_db` is called** before any db routes

## CRUD mode (auto-generated SQL)

```python
from turboapi import TurboAPI
from dhi import BaseModel, Field

app = TurboAPI()
app.configure_db("postgres://user:pass@localhost/mydb", pool_size=16)

class {Resource}(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # add fields matching table columns

@app.db_get("/{table}/{{{table}_id}}", table="{table}", pk="id")
def get_{resource}(): pass

@app.db_list("/{table}", table="{table}")
def list_{table}(): pass

@app.db_post("/{table}", table="{table}", model={Resource})
def create_{resource}(): pass

@app.db_delete("/{table}/{{{table}_id}}", table="{table}", pk="id")
def delete_{resource}(): pass
```

## Custom query mode (raw SQL)

For complex queries — pgvector, JSONB, full-text search, joins, CTEs:

```python
@app.db_query("GET", "/search", sql="""
    SELECT id, title, ts_rank(tsv, plainto_tsquery('english', $1)) AS rank
    FROM articles WHERE tsv @@ plainto_tsquery('english', $1)
    ORDER BY rank DESC LIMIT $2
""", params=["q", "limit"])
def search(): pass

@app.db_query("GET", "/similar/{item_id}", sql="""
    SELECT id, name, 1 - (embedding <=> (SELECT embedding FROM items WHERE id = $1)) AS sim
    FROM items ORDER BY embedding <=> (SELECT embedding FROM items WHERE id = $1) LIMIT $2
""", params=["item_id", "limit"])
def similar(): pass
```

## Performance notes

- **Cached reads**: After first request, GET responses are cached in Zig hashmap (~128k req/s)
- **Writes invalidate cache**: POST/DELETE auto-clear the cache
- **Zero Python**: The entire request cycle (HTTP → validate → query → serialize → respond) runs in Zig
- **Parameterized queries**: All values go through `$N` placeholders — SQL injection safe
- **Table/column validation**: Names validated at registration time (alphanumeric + underscore only)
