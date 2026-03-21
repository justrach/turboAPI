# MagicStack pgbench + TurboAPI pg.zig

Runs MagicStack's [pgbench](https://github.com/MagicStack/pgbench) suite with TurboAPI+pg.zig as an additional driver alongside asyncpg and psycopg3.

## Run

```bash
cd benchmarks/pgbench
docker compose up --build
```

## What it tests

MagicStack's pgbench measures raw driver throughput (queries/sec, latency percentiles). All three drivers talk to Postgres directly using the binary wire protocol. No HTTP involved.

| Driver | Runtime | Concurrency model |
|--------|---------|-------------------|
| asyncpg | Python 3.11 + uvloop | asyncio (single-threaded) |
| psycopg3-async | Python 3.11 + asyncio | asyncio (single-threaded) |
| turbopg (pg.zig) | Python 3.14t + Zig | ThreadPoolExecutor (GIL released) |

## Results (Postgres 18, Docker, concurrency=10, 30s)

| Query | asyncpg | psycopg3-async | turbopg (pg.zig) |
|-------|---------|----------------|------------------|
| SELECT 1+1 | 90,430 q/s | 34,981 q/s | **123,944 q/s (1.37x)** |
| pg_type (619 rows) | 5,856 q/s | 2,211 q/s | **45,712 q/s (7.8x)** |
| generate_series (1000) | 8,339 q/s | 4,238 q/s | **20,356 q/s (2.4x)** |

See [BENCHMARKS.md](BENCHMARKS.md) for detailed analysis.

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

Docker + Docker Compose. Everything runs inside containers (~5 min build, ~5 min benchmark).
