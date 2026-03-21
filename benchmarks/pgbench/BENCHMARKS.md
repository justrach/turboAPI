# MagicStack pgbench Results -- Native Driver Comparison

**Date:** 2026-03-21
**Setup:** Postgres 18, Docker, aarch64, concurrency=10, 30s per test
**Method:** Each driver uses its native path (no HTTP for any driver)

## Results

| Query | asyncpg | psycopg3-async | turbopg (pg.zig) | turbopg vs asyncpg |
|-------|---------|----------------|------------------|-------------------|
| SELECT 1+1 | 90,430 q/s (0.110ms) | 34,981 q/s (0.285ms) | **123,944 q/s (0.080ms)** | **1.37x** |
| pg_type (619 rows) | 5,856 q/s (1.707ms) | 2,211 q/s (4.522ms) | **45,712 q/s (0.218ms)** | **7.8x** |
| generate_series (1000) | 8,339 q/s (1.199ms) | 4,238 q/s (2.359ms) | **20,356 q/s (0.490ms)** | **2.4x** |

## How each driver runs

| Driver | Runtime | Connection | Concurrency |
|--------|---------|-----------|-------------|
| asyncpg | Python 3.11 + uvloop | Direct binary protocol | asyncio (10 coroutines) |
| psycopg3-async | Python 3.11 + asyncio | Direct binary protocol | asyncio (10 coroutines) |
| turbopg (pg.zig) | Python 3.14t + Zig | Direct binary protocol | 10 threads (GIL released) |

All drivers talk to Postgres directly. No HTTP server involved for any driver.

## Why turbopg wins

- **Python 3.14t free-threading**: 10 real OS threads querying Postgres in parallel with zero GIL contention. asyncpg uses asyncio which is single-threaded.
- **pg.zig binary protocol**: Zig-native Postgres client using binary encoding/decoding. No Python in the query hot path.
- **GIL released during I/O**: `PyEval_SaveThread` before query, `PyEval_RestoreThread` after. Postgres I/O runs without holding the GIL.
- **Direct dict building**: Results converted to Python dicts in Zig (no JSON intermediate).
- **Prepared statement cache**: pg.zig caches Parse results. Repeat queries skip the Parse phase.

## Reproduce

```bash
cd benchmarks/pgbench
docker compose up --build
```

No local dependencies. Everything runs in Docker (~5 min build, ~5 min benchmark).
