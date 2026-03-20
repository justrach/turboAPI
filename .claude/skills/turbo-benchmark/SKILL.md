---
name: turbo-benchmark
description: Run performance benchmarks for TurboAPI. Use when testing performance, checking for regressions, or comparing against FastAPI.
disable-model-invocation: true
argument-hint: [http|db|full|all]
---

# Run TurboAPI Benchmarks

## Steps

1. **Determine benchmark type**: `$ARGUMENTS[0]` — `http` (default), `db`, `full`, or `all`
2. **Build turbonet**: Run `uv run --python 3.14t python zig/build_turbonet.py --install --release`
3. **Run the benchmark**

## HTTP benchmark (TurboAPI vs FastAPI)

```bash
uv run --python 3.14t python benchmarks/turboapi_vs_fastapi.py --duration 10 --threads 4 --connections 100
```

## DB benchmark (pg.zig vs SQLAlchemy)

```bash
docker run -d --name bench-pg -p 5432:5432 \
  -e POSTGRES_USER=turbo -e POSTGRES_PASSWORD=turbo -e POSTGRES_DB=turbotest \
  postgres:18-alpine
sleep 3
# Seed, then:
uv run --python 3.14t python benchmarks/db_bench_ci.py
docker stop bench-pg && docker rm bench-pg
```

## Full comparison (all query patterns)

```bash
# Needs Postgres running on :5432
uv run --python 3.14t python benchmarks/full_comparison.py
```

Tests: baseline, SELECT by PK, paginated list, full-text search, GROUP BY, and more.

## Varying IDs benchmark (cache spread test)

```bash
wrk -t2 -c50 -d5s -s benchmarks/varying_ids.lua http://127.0.0.1:8000
```

## Expected numbers (Apple Silicon M3 Pro)

| Endpoint | TurboAPI | FastAPI+SQLAlchemy | Speedup |
|----------|----------|-------------------|---------|
| Baseline (no DB) | ~133k req/s | ~9.8k req/s | 14x |
| SELECT by PK (cached) | ~133k req/s | ~2.6k req/s | 48x |
| Full-text search | ~110k req/s | ~2.5k req/s | 44x |
| GROUP BY sum/avg | ~129k req/s | ~1.4k req/s | 96x |
| Auth + Depends | ~116k req/s | — | — |
| Varying IDs (100 keys) | ~126k req/s | — | — |

## Regression threshold

CI fails if cached PK drops below 10k req/s. See `.github/workflows/db-benchmark.yml`.
