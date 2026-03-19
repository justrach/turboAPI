---
name: turbo-benchmark
description: Run performance benchmarks for TurboAPI. Use when testing performance, checking for regressions, or comparing against FastAPI.
disable-model-invocation: true
argument-hint: [http|db|all]
---

# Run TurboAPI Benchmarks

## Steps

1. **Determine benchmark type**: `$ARGUMENTS[0]` — `http` (default), `db`, or `all`
2. **Build turbonet**: Run `uv run --python 3.14t python zig/build_turbonet.py --install --release`
3. **Run the benchmark**

## HTTP benchmark (TurboAPI vs FastAPI)

```bash
uv run --python 3.14t python benchmarks/turboapi_vs_fastapi.py --duration 10 --threads 4 --connections 100
```

Requires: `wrk` installed (`brew install wrk` or `apt install wrk`)

## DB benchmark (pg.zig vs SQLAlchemy)

Requires a running Postgres instance:

```bash
# Start Postgres
docker run -d --name bench-pg -p 5432:5432 \
  -e POSTGRES_USER=turbo -e POSTGRES_PASSWORD=turbo -e POSTGRES_DB=turbotest \
  postgres:18-alpine

# Wait and seed
sleep 3
docker exec bench-pg psql -U turbo -d turbotest -c "
  CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, name TEXT, email TEXT, age INTEGER);
  INSERT INTO users (name,email,age) SELECT 'user_' || i, 'user' || i || '@test.com', 20+(i%50) FROM generate_series(1,100) AS s(i);
"

# Run benchmark
uv run --python 3.14t python benchmarks/db_bench_ci.py

# Cleanup
docker stop bench-pg && docker rm bench-pg
```

## Expected numbers (Apple Silicon M3 Pro)

| Endpoint | TurboAPI | FastAPI | Speedup |
|----------|----------|---------|---------|
| GET /health (no DB) | ~128k req/s | ~6k req/s | 20x |
| GET /users/1 (cached DB) | ~128k req/s | ~934 req/s | 107x |
| GET /items/{id} (params) | ~143k req/s | ~8.6k req/s | 16x |
| POST /items (model) | ~124k req/s | ~8.2k req/s | 15x |

## Save results

Benchmark results are saved as JSON artifacts in CI. Check `.github/workflows/benchmark.yml` and `.github/workflows/db-benchmark.yml`.
