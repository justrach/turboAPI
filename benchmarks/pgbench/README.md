# MagicStack pgbench + TurboAPI pg.zig

Runs MagicStack's [pgbench](https://github.com/MagicStack/pgbench) suite with TurboAPI+pg.zig as an additional driver alongside asyncpg and psycopg3.

## Run

```bash
cd benchmarks/pgbench
docker compose up --build
```

## What it tests

MagicStack's pgbench measures raw driver throughput (queries/sec, latency percentiles) using the Postgres wire protocol. Three drivers compared on the same queries:

| Driver | Runtime | Protocol |
|--------|---------|----------|
| asyncpg | Python 3.11 + uvloop | Binary (native) |
| psycopg3-async | Python 3.11 + asyncio | Binary |
| turbopg (pg.zig) | Python 3.14t + Zig | Binary (via HTTP*) |

*turbopg runs through TurboAPI's HTTP server, so includes HTTP overhead that the other drivers don't have.

## Results (Postgres 18, Docker, concurrency=10, 30s each)

| Query | asyncpg | psycopg3-async | turbopg (pg.zig)* |
|-------|---------|----------------|-------------------|
| SELECT 1+1 | 93,613 q/s (0.106ms) | 34,888 q/s (0.286ms) | 19,659 q/s (0.508ms) |
| pg_type (619 rows) | 5,844 q/s (1.711ms) | 2,275 q/s (4.394ms) | 19,599 q/s (0.509ms) |
| generate_series (1000) | 8,239 q/s (1.213ms) | 4,180 q/s (2.391ms) | 217 q/s (46ms) |

*turbopg numbers include full HTTP round-trip + JSON serialization overhead.

### Notes

- asyncpg and psycopg3 talk to Postgres directly (no HTTP). turbopg goes HTTP request -> Zig parse -> pg.zig query -> JSON serialize -> HTTP response. Not apples-to-apples.
- On SELECT 1+1, turbopg is slower because the HTTP overhead dominates for tiny results.
- On pg_type (619 rows), turbopg shows high q/s because the result caches after the first call.
- On generate_series (1000 rows), turbopg is slow because serializing 1000 rows to JSON through HTTP is expensive.
- For a fairer comparison, see `benchmarks/postgres/BENCHMARKS.md` which benchmarks the full HTTP stack (wrk) where TurboAPI is 4-20x faster than asyncpg-backed frameworks.

## Architecture

```
Docker Compose:
  postgres:18        -- Postgres server (trust auth)
  pgbench:           -- Two-stage build:
    Stage 1: Python 3.14t + Zig (builds TurboAPI)
    Stage 2: Python 3.11 + uvloop (runs asyncpg/psycopg3)
    run.sh           -- orchestrates all drivers sequentially
    pgbench_zig      -- custom runner for TurboAPI+pg.zig
```

## Requirements

Docker + Docker Compose. Everything runs inside containers (~5 min build, ~5 min benchmark).
