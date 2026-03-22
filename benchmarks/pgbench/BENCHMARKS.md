# MagicStack pgbench Results -- Native Driver Comparison

**Date:** 2026-03-22
**Setup:** Postgres 18, Docker, aarch64 (M3 Pro), concurrency=10, 30s per test
**Method:** Each driver uses its native path (no HTTP). No result caching. Direct binary decode.
**Validation:** Results below are from a clean rerun after `docker compose down -v --remove-orphans`. `COPY FROM` for `asyncpg` is marked unverified on this host because the rerun reproduced a Docker/Postgres `DiskFullError`.

## Results — All 7 MagicStack pgbench Queries

| Query | asyncpg | psycopg3-async | turbopg (pg.zig) | vs asyncpg |
|-------|---------|----------------|------------------|-----------|
| SELECT 1+1 | 94,790 q/s (0.105ms) | 34,638 q/s (0.288ms) | **130,837 q/s (0.076ms)** | **1.38x** |
| pg_type (619 rows, 12 cols) | 5,803 q/s (1.723ms) | 2,264 q/s (4.415ms) | **7,090 q/s (1.409ms)** | **1.22x** |
| generate_series (1000 rows) | 8,229 q/s (1.215ms) | 4,008 q/s (2.494ms) | **19,725 q/s (0.506ms)** | **2.40x** |
| large_object (100 bytea rows) | 26,688 q/s (0.374ms) | 3,107 q/s (3.218ms) | **28,578 q/s (0.349ms)** | **1.07x** |
| arrays (100 int[] rows) | 9,676 q/s (1.033ms) | 3,417 q/s (2.925ms) | **13,763 q/s (0.726ms)** | **1.42x** |
| COPY FROM (10k rows/op) | FAILED (`DiskFullError`) | 114 q/s (87.483ms) | **366 q/s (27.326ms)** | unverified on this host |
| batch INSERT (1k rows) | 1,089 q/s (9.181ms) | 32 q/s (308.693ms) | **31,004 q/s (0.321ms)** | **28.5x** |

**turbopg wins 6/6 queries it completed against asyncpg in the clean rerun.** `COPY FROM` remains inconclusive versus `asyncpg` on this machine because `asyncpg` failed twice with `DiskFullError`. Against `psycopg3-async`, turbopg also wins `COPY FROM` (`366 q/s` vs `114 q/s`, `3.21x`).

### Rows/sec (throughput)

| Query | asyncpg | turbopg | Ratio |
|-------|---------|---------|-------|
| SELECT 1+1 | 94,790 | 130,837 | 1.38x |
| pg_type | 3,592,281 | 4,388,951 | 1.22x |
| generate_series | 8,228,586 | 19,724,529 | 2.40x |
| large_object | 2,668,752 | 2,857,808 | 1.07x |
| arrays | 967,624 | 1,376,323 | 1.42x |
| COPY FROM | failed | 3,656,253 | unverified |
| batch INSERT | 1,088,866 | -- | 28.5x (q/s) |

## Validation notes

- The full suite was rerun from a clean Docker state using `docker compose -f benchmarks/pgbench/docker-compose.yml down -v --remove-orphans` followed by `docker compose -f benchmarks/pgbench/docker-compose.yml up --abort-on-container-exit pgbench`.
- The second run reproduced the same ranking shape for all non-`COPY FROM` queries, with expected run-to-run drift of a few percent.
- `asyncpg` `COPY FROM` failed again during the clean rerun with `asyncpg.exceptions.DiskFullError: could not extend file ... No space left on device`, so any direct `COPY FROM` comparison against `asyncpg` should be treated as unverified until the Docker storage limit is addressed.
- On the clean rerun, `COPY FROM` was still valid for `psycopg3-async` and `turbopg`, where turbopg measured `366 q/s` vs `114 q/s`.

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
6. **COPY FROM STDIN**: Native pg.zig `copyFrom()` sends tab-separated CopyData messages directly over the wire.

## Reproduce

```bash
cd benchmarks/pgbench
docker compose down -v --remove-orphans
docker compose up --build --abort-on-container-exit pgbench
```

No local dependencies. Everything runs in Docker (~5 min build, ~15 min benchmark). For publication-quality numbers, run the suite at least 3 times and report the median.
