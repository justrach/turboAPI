# asyncpg vs TurboAPI+pg.zig -- Benchmark Results

**Date:** 2026-03-21
**Setup:** Postgres 18, Docker (Colima), aarch64 (M3 Pro), Python 3.14t free-threaded
**Method:** Each test runs in its own subprocess (no resource contention)

## Configuration

| Config | Description |
|--------|-------------|
| asyncpg | Raw Python, asyncio.gather, pool=16, 10k queries |
| Turbo cached | Zig response cache enabled, repeat requests hit cache, wrk -t4 -c100 -d10s |
| Turbo no-cache | Varying IDs via wrk lua script, every request hits Postgres |
| Turbo raw SQL | Custom SQL queries, ORDER BY random() + ILIKE |

## Results

| Test | asyncpg | Turbo cached | Turbo no-cache | Turbo raw |
|------|---------|-------------|----------------|-----------|
| SELECT by ID | 19,585/s | 361,337/s | 83,262/s | 64,342/s |
| SELECT list (20 rows) | 18,385/s | 390,832/s | 352,916/s | 375,569/s |
| Raw ILIKE | 12,217/s | n/a | n/a | 350,025/s |

## Multipliers vs asyncpg

| Test | Multiplier |
|------|-----------|
| Cached by-ID | 18.4x |
| No-cache by-ID | 4.3x |
| Cached list | 21.3x |
| No-cache list | 19.2x |
| Raw ILIKE | 28.7x |

## Latency

| Test | Turbo avg | Turbo p99 |
|------|-----------|-----------|
| Cached by-ID | 52us | 4.45ms |
| Cached list | 60us | 9.24ms |
| No-cache by-ID (varying) | 11.87ms | 610ms |
| No-cache list (random) | 58us | 6.71ms |
| Raw ILIKE search | 55us | 6.07ms |

## Notes

- asyncpg is the fastest pure-Python Postgres client. These numbers represent Python's ceiling for DB throughput.
- TurboAPI+pg.zig bypasses Python entirely on the hot path: HTTP parse, Postgres query (binary protocol), JSON serialization all happen in Zig.
- "No-cache by-ID" is the fairest comparison: every request hits Postgres through Docker networking. Still 4.3x faster than asyncpg.
- List queries cache on the SQL string, so even "no-cache" configs show high throughput for repeated list queries.
- The no-cache by-ID latency (11.87ms avg) includes Docker/Colima VM networking overhead. On native Postgres (unix socket), expect significantly lower latency.
- Raw ILIKE at 350k req/s is cached after the first hit (same query string). For truly uncached ILIKE with varying params, expect numbers closer to the no-cache by-ID range.

## Reproduce

```bash
cd benchmarks/postgres
docker compose up --build
```

No local dependencies needed. Everything runs inside Docker.
