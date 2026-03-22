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

## What it tests

MagicStack's pgbench measures raw driver throughput (queries/sec, latency percentiles). All three drivers talk to Postgres directly using the binary wire protocol. No HTTP involved.

| Driver | Runtime | Concurrency model |
|--------|---------|-------------------|
| asyncpg | Python 3.11 + uvloop | asyncio (single-threaded) |
| psycopg3-async | Python 3.11 + asyncio | asyncio (single-threaded) |
| turbopg (pg.zig) | Python 3.14t + Zig | ThreadPoolExecutor (GIL released) |

## Replicated 3-run medians (Postgres 18, Docker, concurrency=10, 30s)

| Query | asyncpg | psycopg3-async | turbopg (pg.zig) |
|-------|---------|----------------|------------------|
| SELECT 1+1 | 90,752 q/s | 34,333 q/s | **125,755 q/s (1.39x)** |
| pg_type (619 rows) | 5,827 q/s | 2,309 q/s | **6,749 q/s (1.16x)** |
| generate_series (1000) | 8,265 q/s | 4,222 q/s | **21,212 q/s (2.57x)** |

See [BENCHMARKS.md](BENCHMARKS.md) for the full 7-query median table, validation ranges, and raw-artifact workflow.

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
