# MagicStack pgbench Results -- Native Driver Comparison

**Date:** 2026-03-22
**Setup:** Postgres 18, Docker, aarch64, concurrency=10, 30s per test
**Method:** Each driver uses its native path (no HTTP). No result caching.

## Results

| Query | asyncpg | psycopg3-async | turbopg (pg.zig) | vs asyncpg |
|-------|---------|----------------|------------------|-----------|
| SELECT 1+1 | 88,351 q/s (0.113ms) | 34,532 q/s (0.289ms) | **128,309 q/s (0.077ms)** | **1.45x** |
| pg_type (619 rows) | 5,803 q/s (1.723ms) | 2,276 q/s (4.393ms) | 4,543 q/s (2.199ms) | 0.78x |
| generate_series (1000) | 8,160 q/s (1.225ms) | 4,158 q/s (2.404ms) | **20,665 q/s (0.483ms)** | **2.53x** |

turbopg wins 2 out of 3 queries. No caching, no tricks, every query hits Postgres.

## Why turbopg wins on SELECT 1+1 and generate_series

- **Python 3.14t free-threading**: 10 real OS threads querying Postgres in parallel, zero GIL contention
- **GIL released during I/O**: pg.zig query runs without holding the GIL (via C shim for PyEval_SaveThread)
- **Direct dict building**: Results converted to Python dicts in Zig, no JSON intermediate
- **No caching**: `_db_query_raw` does not use the DB result cache at all

## Why turbopg loses on pg_type

pg_type returns 619 rows with 12 columns. For each value, turbopg calls `writeJsonValue` to get a string representation, then parses it back into Python types (int/float/string/bool). asyncpg decodes binary protocol directly into native Record objects with Cython. The intermediate string step costs ~0.5ms per query on wide result sets.

## How each driver runs

| Driver | Runtime | Connection | Concurrency |
|--------|---------|-----------|-------------|
| asyncpg | Python 3.11 + uvloop | Direct binary protocol | asyncio (10 coroutines) |
| psycopg3-async | Python 3.11 + asyncio | Direct binary protocol | asyncio (10 coroutines) |
| turbopg (pg.zig) | Python 3.14t + Zig | Direct binary protocol | 10 threads (GIL released) |

## Reproduce

```bash
cd benchmarks/pgbench
docker compose up --build
```

No local dependencies. Everything runs in Docker (~5 min build, ~5 min benchmark).
