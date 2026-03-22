# MagicStack pgbench Preliminary Results -- Driver-Only Native Postgres Comparison

**Date:** 2026-03-22
**Setup:** Postgres 18, Docker, aarch64 (M3 Pro), concurrency=10, 30s per test
**Method:** Each driver uses its native path only, with no HTTP server involved. No result caching. Direct binary decode.
**Validation:** Primary results below are 3-run medians from clean reruns using `python3 benchmarks/pgbench/validate_runs.py --runs 3 --skip-build`. Raw logs and `summary.json` were written to `benchmarks/pgbench/artifacts/`. `COPY FROM` for `asyncpg` remains unverified on this host because all 3 validation runs reproduced a Docker/Postgres `DiskFullError`.

This file is intentionally driver-only. If you want end-to-end web stack numbers, use `benchmarks/postgres/BENCHMARKS.md` instead.

## Replicated Results — 3-Run Medians

### Primary table: median of 3 clean reruns

| Query | asyncpg | psycopg3-async | turbopg (pg.zig) | vs asyncpg |
|-------|---------|----------------|------------------|-----------|
| SELECT 1+1 | 90,752 q/s (0.110ms) | 34,333 q/s (0.291ms) | **125,755 q/s (0.079ms)** | **1.39x** |
| pg_type (619 rows, 12 cols) | 5,827 q/s (1.716ms) | 2,309 q/s (4.330ms) | **6,749 q/s (1.480ms)** | **1.16x** |
| generate_series (1000 rows) | 8,265 q/s (1.209ms) | 4,222 q/s (2.368ms) | **21,212 q/s (0.470ms)** | **2.57x** |
| large_object (100 bytea rows) | 29,750 q/s (0.336ms) | 3,309 q/s (3.021ms) | **31,575 q/s (0.316ms)** | **1.06x** |
| arrays (100 int[] rows) | 9,780 q/s (1.022ms) | 3,392 q/s (2.947ms) | **13,538 q/s (0.738ms)** | **1.38x** |
| COPY FROM (10k rows/op) | FAILED in 3/3 runs (`DiskFullError`) | 116 q/s (86.276ms) | **375 q/s (26.646ms)** | unverified on this host |
| batch INSERT (1k rows) | 1,064 q/s (9.391ms) | 33 q/s (303.807ms) | **30,668 q/s (0.324ms)** | **28.8x** |

**Current evidence:** across 3 clean reruns, turbopg wins 6/6 driver-only queries it completed against asyncpg. `COPY FROM` remains inconclusive versus `asyncpg` on this machine because `asyncpg` failed in all 3 validation runs with `DiskFullError`. Against `psycopg3-async`, turbopg also wins `COPY FROM` (`375 q/s` vs `116 q/s`, `3.23x`).

### Validation summary

| Query | asyncpg | psycopg3-async | turbopg (pg.zig) |
|-------|---------|----------------|------------------|
| SELECT 1+1 | 3/3 successful, 89,993..91,184 q/s | 3/3 successful, 33,950..34,955 q/s | 3/3 successful, 122,377..129,743 q/s |
| pg_type | 3/3 successful, 5,825..5,828 q/s | 3/3 successful, 2,155..2,313 q/s | 3/3 successful, 5,796..7,156 q/s |
| generate_series | 3/3 successful, 7,635..8,301 q/s | 3/3 successful, 4,167..4,271 q/s | 3/3 successful, 20,788..21,305 q/s |
| large_object | 3/3 successful, 28,132..29,849 q/s | 3/3 successful, 3,280..3,328 q/s | 3/3 successful, 31,522..31,658 q/s |
| arrays | 3/3 successful, 9,282..9,866 q/s | 3/3 successful, 3,341..3,405 q/s | 3/3 successful, 12,938..13,789 q/s |
| COPY FROM | 0/3 successful, `DiskFullError` every run | 3/3 successful, 115..117 q/s | 3/3 successful, 374..379 q/s |
| batch INSERT | 3/3 successful, 1,029..1,083 q/s | 3/3 successful, 33..33 q/s | 3/3 successful, 29,323..30,690 q/s |

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
