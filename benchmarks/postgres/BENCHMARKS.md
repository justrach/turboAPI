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

## Current replicated results

**Date:** 2026-03-22  
**Setup:** Docker Postgres 18, Python 3.14t, `wrk -t4 -c100 -d10s`  
**TurboAPI runtime state:** `TURBO_DISABLE_CACHE=1`, `TURBO_DISABLE_DB_CACHE=1`, `TURBO_DISABLE_RATE_LIMITING=1`, `TURBO_THREAD_POOL_SIZE=32`  
**Benchmark pool sizing:** `turbo=32`, `competitors=32`  
**Colima:** `Virtualization.Framework`, `aarch64`, `4 vCPU`, `8 GiB RAM`, `100 GiB disk`, `virtiofs`, Docker runtime  
**Host CPU / RAM:** `Apple M3 Ultra`, `256 GiB`

Primary table below is the median of 3 clean Docker reruns from `docker compose down -v`.

| Test | TurboAPI + pg.zig | FastAPI + asyncpg | FastAPI + SQLAlchemy |
|------|-------------------|-------------------|----------------------|
| `GET /health` | `266,351 req/s` | `9,161 req/s` | `5,010 req/s` |
| `GET /users/{id}` varying 1000 IDs | `80,791 req/s` | `5,203 req/s` | `1,983 req/s` |
| `GET /users?age_min=20` | `71,650 req/s` | `3,162 req/s` | `1,427 req/s` |
| `GET /search?q=user_42%` | `13,245 req/s` | `3,915 req/s` | `1,742 req/s` |

What this run shows:

- TurboAPI is dramatically faster on the no-DB route.
- TurboAPI + pg.zig is faster on all three uncached DB routes in this setup.
- On this Colima profile, the fair median uncached end-to-end PK route is about `80.8k req/s` vs `5.2k` for FastAPI + asyncpg.
- These are seeded Docker reruns of the actual benchmark harness, not ad hoc local host-DB numbers.
- This suite is end-to-end HTTP + DB, so do not compare these numbers directly to `benchmarks/pgbench`.

### 3-run ranges

| Test | TurboAPI + pg.zig | FastAPI + asyncpg | FastAPI + SQLAlchemy |
|------|-------------------|-------------------|----------------------|
| `GET /health` | `263,395..323,224 req/s` | `9,110..9,502 req/s` | `4,980..5,037 req/s` |
| `GET /users/{id}` varying 1000 IDs | `77,768..94,248 req/s` | `4,973..5,464 req/s` | `1,896..2,054 req/s` |
| `GET /users?age_min=20` | `70,000..82,502 req/s` | `3,119..3,198 req/s` | `1,394..1,490 req/s` |
| `GET /search?q=user_42%` | `13,182..13,516 req/s` | `3,847..3,924 req/s` | `1,736..1,755 req/s` |

## Turbo-only scaling note

With the same uncached route set on this host, TurboAPI alone scaled materially with a larger DB pool:

| Turbo pool size | `GET /users/{id}` | `GET /users` | `GET /search` |
|----------------|-------------------|--------------|---------------|
| `16` | `13,228 req/s` | `12,567 req/s` | `7,099 req/s` |
| `32` | `19,380 req/s` | `18,375 req/s` | `7,709 req/s` |
| `64` | `25,716 req/s` | `23,590 req/s` | `8,023 req/s` |

This is useful as a Turbo scaling test, but `32` remains the fair shared default on this host because higher competitor pool sizes ran into connection limits.

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
