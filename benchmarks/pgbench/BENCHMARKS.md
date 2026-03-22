# MagicStack pgbench Results -- Native Driver Comparison

**Date:** 2026-03-22
**Setup:** Postgres 18, Docker, aarch64 (M3 Pro), concurrency=10, 30s per test
**Method:** Each driver uses its native path (no HTTP). No result caching. Direct binary decode.

## Results

| Query | asyncpg | psycopg3-async | turbopg (pg.zig) | vs asyncpg |
|-------|---------|----------------|------------------|-----------|
| SELECT 1+1 | 92,415 q/s (0.108ms) | 34,563 q/s (0.289ms) | **124,951 q/s (0.079ms)** | **1.35x** |
| pg_type (619 rows, 12 cols) | 5,838 q/s (1.712ms) | 2,308 q/s (4.332ms) | **7,124 q/s (1.402ms)** | **1.22x** |
| generate_series (1000 rows) | 8,131 q/s (1.229ms) | 4,128 q/s (2.422ms) | **21,259 q/s (0.469ms)** | **2.61x** |

**turbopg wins all 3 queries.** No caching, no tricks, every query hits Postgres.

## Optimization history

| Optimization | pg_type q/s | Change |
|---|---|---|
| writeJsonValue + JSON round-trip | 4,543 | baseline |
| Direct binary OID decode | 4,954 | +9% |
| Pre-interned column keys + _PyDict_NewPresized | **7,124** | **+44%** |

## How values are decoded

turbopg decodes Postgres binary protocol directly to Python objects (no intermediate strings):

| Postgres type | OID | Decode method |
|--------------|-----|---------------|
| int2/int4/int8 | 21/23/20 | `readInt(big)` -> `PyLong_FromLong` |
| float4/float8 | 700/701 | `readInt` -> `@bitCast` -> `PyFloat_FromDouble` |
| bool | 16 | `data[0] != 0` -> `Py_True/Py_False` |
| text/varchar/name | 25/1043/19 | `PyUnicode_DecodeUTF8` |
| oid | 26 | `readInt(u32)` -> `PyLong_FromUnsignedLong` |
| everything else | * | `PyUnicode_DecodeUTF8` with "replace" |

Column name keys are pre-interned (created once, reused for all rows). Dicts are pre-sized via `_PyDict_NewPresized`.

## How each driver runs

| Driver | Runtime | Connection | Concurrency |
|--------|---------|-----------|-------------|
| asyncpg | Python 3.11 + uvloop | Direct binary protocol | asyncio (10 coroutines, single-threaded) |
| psycopg3-async | Python 3.11 + asyncio | Direct binary protocol | asyncio (10 coroutines, single-threaded) |
| turbopg (pg.zig) | Python 3.14t + Zig | Direct binary protocol | 10 OS threads (GIL released during I/O) |

## Why turbopg wins

1. **Free-threading (Python 3.14t)**: 10 real OS threads query Postgres in parallel. asyncpg is single-threaded (asyncio event loop).
2. **GIL released during I/O**: `PyEval_SaveThread` before pg.zig query, `PyEval_RestoreThread` after. All 10 threads run concurrently.
3. **Direct binary decode**: OID switch -> `PyLong`/`PyFloat`/`PyBool`/`PyUnicode`. No intermediate JSON or string parsing.
4. **Pre-interned keys**: Column name PyUnicode objects created once, reused across all rows.
5. **Pre-sized dicts**: `_PyDict_NewPresized(num_cols)` avoids hash table rehashing.

## Reproduce

```bash
cd benchmarks/pgbench
docker compose up --build
```

No local dependencies. Everything runs in Docker (~5 min build, ~5 min benchmark).
