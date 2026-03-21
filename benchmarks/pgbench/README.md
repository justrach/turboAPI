# MagicStack pgbench + TurboAPI pg.zig

Runs MagicStack's [pgbench](https://github.com/MagicStack/pgbench) suite with TurboAPI+pg.zig as an additional driver alongside asyncpg and psycopg3.

## Run

```bash
cd benchmarks/pgbench
docker compose up --build
```

## What it tests

MagicStack's pgbench measures raw driver throughput (queries/sec, latency percentiles) using the Postgres wire protocol directly. Three drivers are compared on the same queries:

| Driver | Runtime | Protocol |
|--------|---------|----------|
| asyncpg | Python 3.11 + uvloop | Binary (native) |
| psycopg3-async | Python 3.11 + asyncio | Binary |
| turbopg (pg.zig) | Python 3.14t + Zig | Binary (via HTTP*) |

*turbopg runs through TurboAPI's HTTP server, so includes HTTP overhead that the other drivers don't have. This is NOT an apples-to-apples comparison. See `benchmarks/postgres/BENCHMARKS.md` for our own benchmark that accounts for this.

## Queries

From MagicStack's suite:
- `7-oneplusone.json`: `SELECT 1+1` (minimal query, measures driver overhead)
- `1-pg_type.json`: `SELECT ... FROM pg_type WHERE ...` (619 rows, boolean params)
- `2-generate_series.json`: `SELECT i FROM generate_series(1, $1)` (1000 rows)

## Results (Postgres 18, Docker, concurrency=10, 30s)

| Query | asyncpg | psycopg3-async | turbopg (pg.zig)* |
|-------|---------|----------------|-------------------|
| SELECT 1+1 | 95,341 q/s | 34,995 q/s | 20,019 q/s |
| pg_type (619 rows) | 5,932 q/s | 2,274 q/s | needs bool fix |
| generate_series (1000) | 8,273 q/s | 4,236 q/s | needs bool fix |

*turbopg numbers include full HTTP round-trip overhead

## Architecture

```
Docker Compose:
  postgres:18        -- Postgres server (trust auth)
  pgbench:           -- Python 3.11 (asyncpg/psycopg3) + Python 3.14t (TurboAPI)
    run.sh           -- orchestrates all drivers
    pgbench_zig      -- custom runner for TurboAPI+pg.zig
```

## Requirements

Docker + Docker Compose. Everything runs inside containers.
