# TurboAPI Benchmarks

The repo now treats benchmarks as two primary suites only:

## 1. Driver-only benchmark

Path: `benchmarks/pgbench`

Purpose:
- compare `turbopg` / pg.zig directly against `asyncpg` and `psycopg3`
- no HTTP layer
- measures raw query throughput and decode cost

Run:

```bash
cd benchmarks/pgbench
docker compose up --build --abort-on-container-exit pgbench
```

Validation:

```bash
cd benchmarks/pgbench
python3 validate_runs.py --runs 3
```

## 2. End-to-end HTTP + DB benchmark

Path: `benchmarks/postgres`

Purpose:
- compare `TurboAPI + pg.zig/turbopg`
- against `FastAPI + asyncpg`
- and `FastAPI + SQLAlchemy`
- all over HTTP, with TurboAPI response cache and DB cache disabled

Run:

```bash
cd benchmarks/postgres
docker compose up --build --abort-on-container-exit bench
```

## Notes

- Older overlapping benchmark scripts were removed to avoid mixing driver-only, framework-only, and cached-vs-uncached claims.
- Validation microbenchmarks such as `bench_validation.py` and `bench_json.py` can still exist as internal profiling tools, but they are not the headline benchmark suites.
