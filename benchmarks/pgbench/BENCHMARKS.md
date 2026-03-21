# MagicStack pgbench Results -- Native Driver Comparison

**Date:** 2026-03-22
**Setup:** Postgres 18, Docker, aarch64, concurrency=10, 30s per test
**Method:** Each driver uses its native path (no HTTP). No result caching.

## Results

| Query | asyncpg | psycopg3-async | turbopg (pg.zig) | vs asyncpg |
|-------|---------|----------------|------------------|-----------|
| SELECT 1+1 | 93,961 q/s (0.106ms) | 34,785 q/s (0.287ms) | **124,944 q/s (0.079ms)** | **1.33x** |
| pg_type (619 rows) | 5,816 q/s (1.719ms) | 2,248 q/s (4.447ms) | crashes under sustained load | known issue |
| generate_series (1000) | blocked by pg_type crash | - | - | - |

## Known issue: pg_type crash

The pg_type query (619 rows, 12 columns, boolean params) crashes under sustained 30s concurrent load in Docker. Works correctly for individual queries and short bursts (verified: 619 rows returned, 5.5k q/s locally with 10 threads for 100 queries each). The crash appears to be a connection handling issue in pg.zig under sustained load with large result sets in Docker networking.

Tracked at: https://github.com/justrach/pg.zig/issues/59

## How each driver runs

| Driver | Runtime | Connection | Concurrency |
|--------|---------|-----------|-------------|
| asyncpg | Python 3.11 + uvloop | Direct binary protocol | asyncio (10 coroutines) |
| psycopg3-async | Python 3.11 + asyncio | Direct binary protocol | asyncio (10 coroutines) |
| turbopg (pg.zig) | Python 3.14t + Zig | Direct binary protocol | 10 threads (GIL released) |

All drivers talk to Postgres directly. No HTTP server. No result caching.

## Why turbopg wins on SELECT 1+1

- **Python 3.14t free-threading**: 10 real OS threads querying Postgres in parallel with zero GIL contention
- **GIL released during I/O**: pg.zig query runs without holding the GIL
- **Direct dict building**: Results converted to Python dicts in Zig (no JSON intermediate)
- **No caching**: Every query hits Postgres. `TURBO_DISABLE_DB_CACHE` not even needed since `_db_query_raw` doesn't use the DB cache

## Reproduce

```bash
cd benchmarks/pgbench
docker compose up --build
```
