# MagicStack pgbench Results -- Driver-Only Native Postgres Comparison

**Date:** 2026-03-22  
**Setup:** Postgres 18, Docker on Colima, aarch64, concurrency=10, 30s per test  
**Colima:** `Virtualization.Framework`, `aarch64`, `4 vCPU`, `8 GiB RAM`, `100 GiB disk`, `virtiofs`, Docker runtime  
**Host CPU / RAM:** `Apple M3 Ultra`, `256 GiB`  
**Method:** Each driver uses its native path only, with no HTTP server involved. No result caching. Direct binary decode.

This file is intentionally driver-only. If you want end-to-end web stack numbers, use `benchmarks/postgres/BENCHMARKS.md` instead.

For reference, the separate end-to-end HTTP + DB benchmark on this branch
currently reports the following local 3-run medians:

| Route | TurboAPI + pg.zig | FastAPI + asyncpg | FastAPI + SQLAlchemy |
|---|---|---|---|
| GET /health | **266,351/s** | 9,161/s | 5,010/s |
| GET /users/{id} varying 1000 IDs | **80,791/s** | 5,203/s | 1,983/s |
| GET /users?age_min=20 | **71,650/s** | 3,162/s | 1,427/s |
| GET /search?q=user_42% | **13,245/s** | 3,915/s | 1,742/s |

Those numbers come from `benchmarks/postgres/BENCHMARKS.md` and should not be
mixed into the driver-only table below.

These results are local to this Apple Silicon / Colima environment. The same
suite in GitHub Actions runs on `ubuntu-latest` x86_64 inside Docker and shows
different rankings. On the PR CI run, `turbopg` won `generate_series` and
`arrays`, while `asyncpg` led `SELECT 1+1`, `pg_type`, `large_object`,
`COPY FROM`, and `batch INSERT`. Treat local and CI runs as separate benchmark
environments, not a single pooled dataset.

## Current Primary Results

The primary table below is from a full clean rerun after fixing the Turbo runner issues that previously invalidated parts of the suite:

- `pgbench_zig` no longer crashes on non-batch queries due to the `batch_info` bug
- the suite was rerun from a wiped Docker state via `docker compose down -v`
- the old Turbo `batch INSERT` claim (`~30k q/s`) is obsolete and should not be cited

### Clean full-suite rerun

| Query | asyncpg | psycopg3-async | turbopg (pg.zig) | vs asyncpg |
|-------|---------|----------------|------------------|-----------|
| SELECT 1+1 | 92,715 q/s (0.107ms) | 33,726 q/s (0.296ms) | **99,431 q/s (0.100ms)** | **1.07x** |
| pg_type (619 rows, 12 cols) | 5,450 q/s (1.834ms) | 2,273 q/s (4.399ms) | **7,152 q/s (1.397ms)** | **1.31x** |
| generate_series (1000 rows) | 8,282 q/s (1.207ms) | 3,992 q/s (2.504ms) | **21,173 q/s (0.471ms)** | **2.56x** |
| large_object (100 bytea rows) | 30,368 q/s (0.329ms) | 3,359 q/s (2.977ms) | **33,634 q/s (0.296ms)** | **1.11x** |
| arrays (100 int[] rows) | 9,902 q/s (1.009ms) | 3,397 q/s (2.943ms) | **13,363 q/s (0.747ms)** | **1.35x** |
| COPY FROM (10k rows/op) | **516 q/s (19.388ms)** | 111 q/s (90.189ms) | 313 q/s (31.973ms) | 0.61x |
| batch INSERT (1k rows) | **1,101 q/s (9.083ms)** | 34 q/s (293.366ms) | 1,021 q/s (9.788ms) | 0.93x |

**Current evidence:** on this clean corrected run, turbopg wins 5/7 driver-only queries against asyncpg. `asyncpg` still leads on `COPY FROM` and narrowly leads on `batch INSERT` on this host.

## Notes on Older Results

Older tables in this file are kept below for historical reference only. They should not be used as the primary citation because:

- earlier `batch INSERT` numbers were taken before the Turbo runner matched the workload correctly
- earlier validation runs were recorded before the `pgbench_zig` runner bug was fixed
- some older `COPY FROM` runs were affected by Docker storage failures on this machine

### First full run captured earlier (reference only)

| Query | asyncpg | psycopg3-async | turbopg (pg.zig) | vs asyncpg |
|-------|---------|----------------|------------------|-----------|
| SELECT 1+1 | 97,842 q/s (0.102ms) | 34,384 q/s (0.290ms) | **126,979 q/s (0.078ms)** | **1.30x** |
| pg_type (619 rows, 12 cols) | 5,761 q/s (1.735ms) | 2,310 q/s (4.328ms) | **7,084 q/s (1.410ms)** | **1.23x** |
| generate_series (1000 rows) | 8,093 q/s (1.235ms) | 4,218 q/s (2.370ms) | **20,783 q/s (0.480ms)** | **2.57x** |
| large_object (100 bytea rows) | FAILED / stale table | FAILED / stale table | **29,987 q/s** | n/a |
| arrays (100 int[] rows) | 9,685 q/s (1.032ms) | 3,306 q/s (3.024ms) | **13,638 q/s (0.732ms)** | **1.41x** |
| COPY FROM (10k rows/op) | FAILED / disk full | 116 q/s (86.3ms) | **372 q/s (26.9ms)** | n/a |
| batch INSERT (1k rows) | 1,020 q/s (9.8ms) | 33 q/s (300ms) | **29,387 q/s (0.339ms)** | **28.8x** |

### Validation comparison: first run vs clean rerun

| Query | Metric | First run | Clean rerun | Delta |
|-------|--------|-----------|-------------|-------|
| SELECT 1+1 | turbopg q/s | 126,979 | 130,837 | +3.0% |
| SELECT 1+1 | asyncpg q/s | 97,842 | 94,790 | -3.1% |
| pg_type | turbopg q/s | 7,084 | 7,090 | +0.1% |
| pg_type | asyncpg q/s | 5,761 | 5,803 | +0.7% |
| generate_series | turbopg q/s | 20,783 | 19,725 | -5.1% |
| generate_series | asyncpg q/s | 8,093 | 8,229 | +1.7% |
| arrays | turbopg q/s | 13,638 | 13,763 | +0.9% |
| arrays | asyncpg q/s | 9,685 | 9,676 | -0.1% |
| batch INSERT | turbopg q/s | 29,387 | 31,004 | +5.5% |
| batch INSERT | asyncpg q/s | 1,020 | 1,089 | +6.8% |

### Rows/sec (throughput)

| Query | asyncpg | turbopg | Ratio |
|-------|---------|---------|-------|
| SELECT 1+1 | 90,752 | 125,755 | 1.39x |
| pg_type | 3,606,968 | 4,177,662 | 1.16x |
| generate_series | 8,264,817 | 21,211,858 | 2.57x |
| large_object | 2,975,014 | 3,157,501 | 1.06x |
| arrays | 978,039 | 1,353,787 | 1.38x |
| COPY FROM | failed | 3,656,253 | unverified |
| batch INSERT | 1,064,465 | -- | 28.8x (q/s) |

### COPY FROM verified comparison on this host

| Driver | Queries/sec | Rows/sec | Mean latency |
|--------|-------------|----------|--------------|
| psycopg3-async | 116 | 1,157,329 | 86.276ms |
| turbopg (pg.zig) | **375** | **3,745,327** | **26.646ms** |
| asyncpg | FAILED in 3/3 runs | FAILED | `DiskFullError` |

## Validation notes

- The full suite was rerun from a clean Docker state using `docker compose -f benchmarks/pgbench/docker-compose.yml down -v --remove-orphans` followed by `docker compose -f benchmarks/pgbench/docker-compose.yml up --abort-on-container-exit pgbench`.
- Three validation runs were completed from a clean Docker state, and the primary table in this file now reports medians rather than a hand-selected single run.
- Non-`COPY FROM` queries reproduced the same ranking shape across all three validation runs.
- `asyncpg` `COPY FROM` failed in all 3 validation runs with `asyncpg.exceptions.DiskFullError: could not extend file ... No space left on device`, so any direct `COPY FROM` comparison against `asyncpg` should be treated as unverified until the Docker storage limit is addressed.
- Across the 3 validation runs, `COPY FROM` remained valid for `psycopg3-async` and `turbopg`, where turbopg's median was `375 q/s` vs `116 q/s`.
- Raw artifacts are available under `benchmarks/pgbench/artifacts/`.

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

No local dependencies. Everything runs in Docker (~5 min build, ~15 min benchmark).

## Publication workflow

```bash
cd benchmarks/pgbench
python3 validate_runs.py --runs 3
```

This saves raw logs under `benchmarks/pgbench/artifacts/` and prints a median table suitable for copying into a paper or review doc.
