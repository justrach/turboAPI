# Changelog

All notable changes to TurboAPI are documented here.

## [1.0.33] — 2026-08-05

#### Security

- Request headers can no longer override already-extracted path/query params: implicit header mapping (Issue #132) now only fills params not bound elsewhere, so a client `User-Id` header cannot replace a `{user_id}` path value.
- Added a JSON nesting-depth pre-check (cap 256) before `std.json` parsing and the recursive Python converter — deeply nested bodies previously overflowed the worker stack and killed the process.
- `SO_SNDTIMEO` is now set alongside `SO_RCVTIMEO` — a client that never reads can no longer stall a worker (and the GIL) forever on a blocked `write()`.
- DB route registration now validates column and primary-key names as SQL identifiers (table names already were), closing SQL injection via `db_add_route`; COPY FROM validates table/column names too.
- `execManyDynamic` no longer reuses a fixed prepared-statement cache name for arbitrary SQL — pg.zig ignores `sql` on a cache hit, so different SQL re-executed the first prepared statement.
- Python `None` now maps to SQL NULL in COPY FROM (was the literal string `"None"`); COPY cells escape `\`, tab, newline and CR per the Postgres text format.

#### Fixed

- Stack buffer overflow when a DB row serialized to more than 8 KB of JSON: all pg.zig JSON writers and `serializeFixedSchemaRow` now bounds-check and fail cleanly (500) instead of corrupting the stack.
- Use-after-free in the DB response cache: `cacheGet` returned cache-owned memory that concurrent TTL expiry/invalidation could free mid-send; it now returns a caller-owned copy.
- Use-after-free in `callPythonHandler` when a handler returned a non-str body: the json.dumps temporary was freed before the body was copied out.
- Response-cache key fallback could collapse distinct requests (>512-byte keys) into one entry; oversized keys now skip caching. Same policy for custom-query cache keys.
- `@intCast` on unvalidated Python status codes could panic a worker; invalid codes now map to 500.
- Body read errors/truncated bodies no longer desync keep-alive connections.
- List DB queries no longer emit trailing-comma JSON (`[...,]`) when the 64 KB buffer fills.
- Async handlers: async dependencies (coroutine/async-gen Depends) no longer 500 via `asyncio.run()` inside the running loop; StreamingResponse from async handlers no longer 500s or silently sends an empty body; dependency generator teardown now runs in `finally` (and via `aclose()`) so failing requests don't leak DB sessions.
- Zig vectorcall no longer coerces unparseable int/float params to 0 — returns 400.
- Schema parsing no longer leaks allocations on failure; telemetry init no longer races on an undefined exporter; `_rv_*` response helpers guard against non-dict state.
- benchmarks/postgres Dockerfile pinned to Zig 0.15.2 while the codebase requires 0.16 — bumped to 0.16.0.

#### Performance

- Request validation no longer heap-allocates error paths on the success path (stack-buffer path building) — removed an alloc/free per field and per array element per request.
- `inspect.signature()` for dependencies and route-pattern regex construction are now memoized instead of re-run per request.
- Benchmarks rerun in this session (local Apple Silicon, Colima VM for Docker suites): HTTP regression suite (`bench_regression.py`, WORKERS=4, wrk 4 threads/100 connections/10s per route) averaged 112,547 req/s across its six routes; driver-only pgbench and e2e HTTP+DB Docker suites reran within or above their previously recorded ranges in `benchmarks/pgbench/BENCHMARKS.md` and `benchmarks/postgres/BENCHMARKS.md` — no regressions observed.

## [1.0.27] — 2026-04-01

### Since 1.0.24

#### Compatibility

- Fixed package-level password helper exports so the top-level `turboapi` API no longer mixes implementations between `hash_password` and `verify_password`.
- Added regression coverage that locks the top-level password helpers to the `turboapi.security` implementation.

#### Test Suite

- Removed stale `xfail` markers from the async handler suite for cases that now pass on current `main`.
- Kept the remaining async error-handling gap explicit with a strict `xfail` instead of silently masking newly passing behavior.
- Added release metadata regression coverage so version declarations must stay aligned across packaging files.

#### Release Fixes

- Re-cut the patch release after both `v1.0.25` and `v1.0.26` published stale assets from older tag targets.
- Added workflow checks so tag pushes fail if the tag version and repository version declarations do not match.
- Fixed the manual release workflow so future bump automation updates `pyproject.toml`, `python/setup.py`, and `python/turboapi/__init__.py` together.

#### Closed Issues

- [#116](https://github.com/justrach/turboAPI/issues/116) — package-level `turboapi.verify_password` resolved to the wrong helper
- [#117](https://github.com/justrach/turboAPI/issues/117) — async handler suite contained stale `xfail` markers

## [1.0.26] — 2026-04-01

### Release Fixes

- Re-cut the patch release after `v1.0.25` published assets with stale `1.0.24` version metadata.
- Synced version declarations across `pyproject.toml`, `python/setup.py`, and `python/turboapi/__init__.py`.
- Added a regression test that fails if release metadata files drift out of sync again.

## [1.0.25] — 2026-04-01

### Compatibility

- Fixed package-level password helper exports so the top-level `turboapi` API no longer mixes implementations between `hash_password` and `verify_password`.
- Removed stale `xfail` markers from the async handler suite for cases that now pass on current `main`, while keeping the remaining async error-handling gap explicit.

### Closed Issues

- [#116](https://github.com/justrach/turboAPI/issues/116) — package-level `turboapi.verify_password` resolved to the wrong helper
- [#117](https://github.com/justrach/turboAPI/issues/117) — async handler suite contained stale `xfail` markers

## [1.0.24] — 2026-03-31

### Bug Fixes

- Restored Zig-runtime gzip middleware body passthrough so compressed responses keep the correct `Content-Encoding: gzip` header and the actual compressed body.
- Normalized middleware-visible request headers to lowercase before Python-side processing.
- Preserved raw `bytes` response bodies in the Zig bridge instead of JSON-serializing compressed middleware output to `null`.

### Closed Issues

- [#96](https://github.com/justrach/turboAPI/issues/96) — gzip middleware on Zig runtime dropped or mangled compressed responses

## [1.0.23] — 2026-03-27

### Architecture

- Extracted radix trie router, HTTP utilities (`percentDecode`, `queryStringGet`, `statusText`, `formatHttpDate`), bounded response cache, and shared types into standalone **turboapi-core** Zig library with zero dependencies.
- turboAPI now imports router from turboapi-core (deleted `zig/src/router.zig`).
- [merjs](https://github.com/justrach/merjs) wired as a consumer of turboapi-core — shared routing foundation across both frameworks.
- Zero performance regression: 134k req/s, 0.16ms avg latency unchanged.

### Documentation

- Added "What's New" changelog section to README (visible before benchmarks).
- Updated Architecture section with turboapi-core explanation.
- Updated Project Structure to reflect new `turboapi-core/` directory.

## [1.0.22] — 2026-03-26

### Build Fixes

- Refreshed the pinned `dhi` dependency hash in `zig/build.zig.zon` so `Build & Publish` can build the `turbonet` extension on clean CI runners again.

## [1.0.21] — 2026-03-26

### Bug Fixes

- Restored custom exception-handler dispatch in the runtime/TestClient path.
- Restored execution of `lifespan=` callables during ASGI lifespan startup and shutdown.
- Restored serving of configured `/docs` and `/openapi.json` URLs in the verifier/TestClient path.
- Restored enforcement of router-level dependencies during request handling.
- Restored mounted `StaticFiles` dispatch in the runtime/TestClient path.

### Verification

- Added exact repro coverage for issues `#100` through `#104` in `tests/test_verified_compat_gaps.py`.

## [1.0.22] — 2026-03-26

### Build Fixes

- Refreshed the pinned `dhi` dependency hash in `zig/build.zig.zon` so `Build & Publish` can build the `turbonet` extension on clean CI runners again.

## [1.0.01] — 2026-03-19

### Performance (47k → 150k req/s)

- **Per-worker PyThreadState** — each of 24 threads creates one tstate at startup, reuses via `PyEval_AcquireThread`. Zero per-request thread-state allocation. (`c03e67a`)
- **PyObject_CallNoArgs** for zero-arg handlers — single CPython call, no tuple/dict allocation. (`c03e67a`)
- **Tuple response ABI** — handlers return `(status, content_type, body)` tuple. 3× `PyTuple_GetItem` replaces 3× `PyDict_GetItemString`. (`c03e67a`)
- **Zero-alloc sendResponse** — header formatted into 512-byte stack buffer, body appended into 4KB stack buffer, single `writeAll`. Eliminates 2 heap allocs + 2 frees per response. (`b6fedcb`)
- **Single-parse model_sync** — `validateJsonRetainParsed` returns parsed JSON tree; `callPythonModelHandlerParsed` skips redundant `parseFromSlice`. (`b6fedcb`)
- **Static routes** — `app.static_route("GET", "/health", '{"ok":true}')` pre-renders full HTTP response at startup. Single `writeAll` at dispatch. (`b6fedcb`)
- **Zig-native CORS** — CORS headers pre-rendered once at startup, injected via `memcpy`. 24% overhead → 0%. OPTIONS preflight handled in Zig. (`5126a5c`)
- **Enum handler dispatch** — `HandlerType` enum replaces 4× string comparison per request. (`5126a5c`)
- **Skip header parsing** — route matching moved before `parseHeaders`. `simple_sync_noargs` and `simple_sync` skip header parsing + body read entirely. (`a373a33`)
- **Zero-alloc route params** — `RouteParams` stack array replaces `StringHashMap` in `RouteMatch`. Zero allocator calls per request. (`d09c8eb`)
- **Response caching** — noargs handlers cached after first Python call; param-aware caching for `simple_sync` routes using full path as key. (`2010a74`, `dee1019`)

### Security

- **10 of 13 bugs fixed** from community security audit ([#41](https://github.com/justrach/turboAPI/issues/41)):
  - `py.zig`: `bufPrintZ` for null-terminated C strings (stack over-read fix)
  - `server.zig`: `allocator.dupe` for Python string pointers (dangling pointer fix)
  - `server.zig`: Port range validation 1–65535 before `@intCast` (integer truncation)
  - `middleware.py`: `threading.Lock` on rate limiter dict (data race)
  - `middleware.py`: Prefer `X-Real-IP` over `X-Forwarded-For`
  - `middleware.py`: `ValueError` on CORS wildcard + credentials
  - `security.py`: `NotImplementedError` for password hash placeholders
  - `server.zig`: `handler_tag` set in all route registration functions
- **Slowloris protection** — `SO_RCVTIMEO` 30s on accepted sockets (`dee1019`)
- **Fuzz tests** for HTTP parser, router, JSON validator, URL decoder (`2024239`)
- **12 security regression tests** in `tests/test_security_audit_fixes.py` (`9232cbe`)
- **SECURITY.md** — full threat model, deployment recommendations, known gaps

### New Features

- `app.static_route(method, path, body)` — pre-rendered response routes
- `app.add_middleware(CORSMiddleware, ...)` — auto-routed to Zig-native CORS
- `benchmarks/bench_regression.py` — regression tracker with baseline thresholds
- `CLAUDE.md` — contributor project guide

### Bug Fixes

- Middleware stacking works with all handler types (`367143c`)
- Binary `Response` objects return raw bytes in tuple (`2fdaf70`)
- PyJWT lazy-loaded so turboapi imports without it (`606e666`)
- Linux CI: `continue-on-error` for Zig thread cleanup segfault (`ee7de51`)

### Documentation

- README updated with 150k numbers, new features, architecture
- SECURITY.md with threat model, fuzz status, mitigations table
- "Why Python?" section with decision table vs Go/Rust
- Observability section: OpenTelemetry, Prometheus, structlog examples

### Closed Issues

- [#37](https://github.com/justrach/turboAPI/issues/37) — Fuzz testing
- [#41](https://github.com/justrach/turboAPI/issues/41) — Security audit (10/13 fixed)
- [#25](https://github.com/justrach/turboAPI/issues/25) — Zero-copy optimizations
- [#34](https://github.com/justrach/turboAPI/issues/34) — Static/native routes
- [#35](https://github.com/justrach/turboAPI/issues/35) — Double JSON parse
- [#5](https://github.com/justrach/turboAPI/issues/5) — Naming conflict (resolved)
- [#6](https://github.com/justrach/turboAPI/issues/6) — Middleware questions (resolved)

---

## [0.5.0] — 2026-03-14

- Initial Zig HTTP core with 24-thread pool
- FastAPI-compatible decorators
- dhi model validation
- 47k req/s baseline
