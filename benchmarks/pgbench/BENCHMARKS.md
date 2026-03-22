# MagicStack pgbench Results -- Native Driver Comparison

**Date:** 2026-03-22
**Setup:** Postgres 18, Docker, aarch64, concurrency=10, 30s per test
**Method:** Each driver uses its native path (no HTTP). No result caching. Direct binary decode.

## Results

| Query | asyncpg | psycopg3-async | turbopg (pg.zig) | vs asyncpg |
|-------|---------|----------------|------------------|-----------|
| SELECT 1+1 | 88,888 q/s (0.112ms) | 34,899 q/s (0.286ms) | **125,964 q/s (0.079ms)** | **1.42x** |
| pg_type (619 rows) | 5,812 q/s (1.720ms) | 2,236 q/s (4.471ms) | 4,954 q/s (2.016ms) | 0.85x |
| generate_series (1000) | 7,867 q/s (1.271ms) | 4,028 q/s (2.482ms) | **20,285 q/s (0.492ms)** | **2.58x** |

turbopg wins 2 out of 3 queries. No caching, no tricks, every query hits Postgres.

## How values are decoded

turbopg decodes Postgres binary protocol directly to Python objects:

| Postgres type | OID | Python type | Method |
|--------------|-----|-------------|--------|
| int2/int4/int8 | 21/23/20 | int | `readInt` -> `PyLong_FromLong` |
| float4/float8 | 700/701 | float | `readInt` -> `@bitCast` -> `PyFloat_FromDouble` |
| bool | 16 | bool | `data[0] != 0` -> `Py_True/Py_False` |
| text/varchar/name | 25/1043/19 | str | `PyUnicode_DecodeUTF8` |
| oid | 26 | int | `readInt(u32)` -> `PyLong_FromUnsignedLong` |
| everything else | * | str | `PyUnicode_DecodeUTF8` with "replace" |

No intermediate JSON serialization. No string parsing. Binary -> Python object.

## Why turbopg loses on pg_type

asyncpg returns Cython-optimized Record objects (C structs with typed tuple access). turbopg returns Python dicts. For 619 rows * 12 columns = 7,428 values, the dict overhead (PyDict_New + PyDict_SetItem + PyUnicode key creation per value) adds up.

## Reproduce

```bash
cd benchmarks/pgbench
docker compose up --build
```
