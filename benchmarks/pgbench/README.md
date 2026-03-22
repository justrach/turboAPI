# MagicStack pgbench + TurboAPI pg.zig

Runs MagicStack's [pgbench](https://github.com/MagicStack/pgbench) suite with TurboAPI+pg.zig as an additional driver alongside asyncpg and psycopg3.

## Run

```bash
cd benchmarks/pgbench
docker compose up --build
```

## Validate

For anything you plan to publish or defend, use clean reruns and medians instead of a single run:

```bash
cd benchmarks/pgbench
python3 validate_runs.py --runs 3
```

This writes raw logs to `benchmarks/pgbench/artifacts/` and prints a median summary table.

Important: this suite is environment-sensitive. The local Apple Silicon /
Colima results in this directory do not exactly match the GitHub Actions Ubuntu
runner. CI still runs the same suite for regression visibility, but those
numbers should be read as a separate environment rather than averaged into the
local table below.

## What it tests

MagicStack's pgbench measures raw driver throughput (queries/sec, latency percentiles). All three drivers talk to Postgres directly using the binary wire protocol. No HTTP involved.

| Driver | Runtime | Concurrency model |
|--------|---------|-------------------|
| asyncpg | Python 3.11 + uvloop | asyncio (single-threaded) |
| psycopg3-async | Python 3.11 + asyncio | asyncio (single-threaded) |
| turbopg (pg.zig) | Python 3.14t + Zig | ThreadPoolExecutor (GIL released) |

## Current clean rerun (Postgres 18, Docker, concurrency=10, 30s)

| Query | asyncpg | psycopg3-async | turbopg (pg.zig) |
|-------|---------|----------------|------------------|
| SELECT 1+1 | 92,715 q/s | 33,726 q/s | **99,431 q/s (1.07x)** |
| pg_type (619 rows) | 5,450 q/s | 2,273 q/s | **7,152 q/s (1.31x)** |
| generate_series (1000) | 8,282 q/s | 3,992 q/s | **21,173 q/s (2.56x)** |
| COPY FROM (10k rows/op) | **516 q/s** | 111 q/s | 313 q/s |
| batch INSERT (1k rows) | **1,101 q/s** | 34 q/s | 1,021 q/s |

See [BENCHMARKS.md](BENCHMARKS.md) for the full 7-query table, notes on the runner fixes, and the older superseded validation tables.

## Architecture

```
Docker Compose:
  postgres:18       -- Postgres server (trust auth)
  pgbench:          -- Two-stage build:
    Stage 1: Python 3.14t + Zig (builds TurboAPI + pg.zig)
    Stage 2: Python 3.11 + uvloop (runs asyncpg/psycopg3)
    run.sh          -- orchestrates all drivers sequentially
    pgbench_zig     -- native TurboPG runner (ThreadPoolExecutor, GIL released)
```

## Requirements

Docker + Docker Compose. Everything runs inside containers (~5 min build, ~15 min benchmark for one full suite).
