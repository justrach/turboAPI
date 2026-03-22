# TurboAPI + pg.zig vs FastAPI + asyncpg / SQLAlchemy

Reproducible end-to-end HTTP + DB benchmark running in Docker with Postgres 18.

## Run

```bash
cd benchmarks/postgres
docker compose up --build --abort-on-container-exit bench
```

## What it tests

| # | Config | Description |
|---|--------|-------------|
| 1 | TurboAPI + pg.zig | End-to-end HTTP benchmark with TurboAPI cache off and DB cache off |
| 2 | FastAPI + asyncpg | Same HTTP routes backed by asyncpg |
| 3 | FastAPI + SQLAlchemy | Same HTTP routes backed by SQLAlchemy |

Routes:

- `GET /health`
- `GET /users/{id}` with varying IDs via `wrk` Lua
- `GET /users?age_min=20`
- `GET /search?q=user_42%`

Methodology:

- all three servers expose the same HTTP interface
- TurboAPI runs with `TURBO_DISABLE_CACHE=1`, `TURBO_DISABLE_DB_CACHE=1`, and `TURBO_DISABLE_RATE_LIMITING=1`
- the benchmark measures end-to-end request, query, and serialization throughput
- if you want driver-only numbers, use `benchmarks/pgbench` instead

## Requirements

Everything runs inside Docker. No local dependencies needed.

- Docker + Docker Compose
- ~8GB RAM (Postgres + Python build + benchmark runner)
- ~5 minutes for full run (Python 3.14t builds from source)
