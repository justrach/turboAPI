# TurboAPI + pg.zig vs FastAPI + asyncpg / SQLAlchemy

This benchmark suite now measures one thing only:

- end-to-end HTTP + DB performance

It does not mix in:

- driver-only results
- cached TurboAPI routes
- warmed cache comparisons

## Method

- Postgres 18 in Docker
- same HTTP routes exposed by all three stacks
- `wrk` load generation
- TurboAPI response cache disabled via `TURBO_DISABLE_CACHE=1`
- TurboAPI DB cache disabled via `TURBO_DISABLE_DB_CACHE=1`

Compared stacks:

1. `TurboAPI + pg.zig/turbopg`
2. `FastAPI + asyncpg`
3. `FastAPI + SQLAlchemy`

Routes:

1. `GET /health`
2. `GET /users/{id}` with varying IDs
3. `GET /users?age_min=20`
4. `GET /search?q=user_42%`

## One local run

**Date:** 2026-03-22  
**Setup:** local Docker Postgres 18, Python 3.14t, `wrk -t4 -c100 -d5s`  
**TurboAPI runtime state:** `TURBO_DISABLE_CACHE=1`, `TURBO_DISABLE_DB_CACHE=1`, `TURBO_DISABLE_RATE_LIMITING=1`, `TURBO_THREAD_POOL_SIZE=16`

| Test | TurboAPI + pg.zig | FastAPI + asyncpg | FastAPI + SQLAlchemy |
|------|-------------------|-------------------|----------------------|
| `GET /health` | `140,641 req/s` | `11,264 req/s` | `8,425 req/s` |
| `GET /users/{id}` varying 1000 IDs | `13,202 req/s` | `5,523 req/s` | `2,387 req/s` |
| `GET /users?age_min=20` | `12,395 req/s` | `3,751 req/s` | `1,889 req/s` |
| `GET /search?q=user_42%` | `6,825 req/s` | `4,337 req/s` | `2,132 req/s` |

What this run shows:

- TurboAPI is dramatically faster on the no-DB route.
- TurboAPI + pg.zig is faster on all three uncached DB routes in this setup.
- The earlier `GET /users/{id}` result that showed TurboAPI behind asyncpg was not valid; the benchmark harness had not disabled rate limiting, and the `select_one` path was heavier than necessary.
- This suite is end-to-end HTTP + DB, so do not compare these numbers directly to `benchmarks/pgbench`.

## Run

```bash
cd benchmarks/postgres
docker compose up --build --abort-on-container-exit bench
```

## Why this suite exists

Use this benchmark when you want to answer:

- how fast is the full web stack
- how much overhead does FastAPI add on top of the DB client
- how does TurboAPI behave with caches disabled

If you want raw database driver numbers, use `benchmarks/pgbench` instead.
