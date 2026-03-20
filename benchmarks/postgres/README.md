# asyncpg vs TurboAPI+pg.zig Benchmark

Reproducible head-to-head benchmark running in Docker with Postgres 18.

## Run

```bash
cd benchmarks/postgres
docker compose up --build
```

## What it tests

| # | Config | Description |
|---|--------|-------------|
| 1 | asyncpg | Raw Python, asyncio.gather, pool=16, 10k queries |
| 2 | Turbo cached | Zig response cache enabled, repeat requests hit cache |
| 3 | Turbo no-cache | Varying IDs via wrk lua script, every request hits Postgres |
| 4 | Turbo raw SQL | Custom SQL, ORDER BY random() + ILIKE queries |

## Requirements

Everything runs inside Docker. No local dependencies needed.

- Docker + Docker Compose
- ~8GB RAM (Postgres + Python build + benchmark runner)
- ~5 minutes for full run (Python 3.14t builds from source)
