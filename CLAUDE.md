# TurboAPI — Project Guide

## What is this?

A high-performance Python web framework with a Zig HTTP backend. Drop-in FastAPI-compatible API.

## Requirements

- **Python 3.14+** (free-threaded `3.14t` recommended)
- **Zig 0.15+** (for building the native backend)
- **uv** (Python package manager)

## Building

```bash
# Build the Zig native backend (auto-detects Python include paths)
python zig/build_turbonet.py

# Install the Python package in dev mode
uv pip install -e ".[dev]"
```

## Running Tests

```bash
# Python tests (requires Python 3.14t)
uv run --python 3.14t python -m pytest tests/ -p no:anchorpy \
  --deselect tests/test_fastapi_parity.py::TestWebSocket

# Zig unit tests (includes fuzz seed corpus)
cd zig && zig build test

# Zig continuous fuzzing (runs indefinitely)
cd zig && zig build test --fuzz
```

**Known test exclusions:**
- WebSocket tests (`TestWebSocket`) — pre-existing failure, deselect
- `anchorpy` plugin — causes import error, disable with `-p no:anchorpy`

## Benchmarks

```bash
uv run --python 3.14t python benchmarks/run_benchmarks.py
```

Current numbers: ~140k req/s, 0.16ms avg latency, 8-9x faster than FastAPI.

## Project Structure

```
zig/src/
  server.zig         — HTTP server core (TCP, parsing, dispatch)
  router.zig         — Radix trie router
  dhi_validator.zig  — JSON schema validator (pre-GIL)
  py.zig             — Python C API helpers
zig/build.zig        — Zig build system

python/turboapi/
  main_app.py        — TurboAPI class (public API)
  middleware.py       — CORS, rate limiting, gzip, etc.
  security.py        — Auth helpers (OAuth2, JWT, API keys)
  models.py          — Request/Response models
  routing.py         — Router and APIRouter
  request_handler.py — Python-side request handling

tests/               — pytest test suite (275+ tests)
benchmarks/          — Performance benchmarks
```

## Key Conventions

- Zig backend builds via `python zig/build_turbonet.py` (NOT `zig build` directly — it needs `-Dpy-include`)
- Pre-commit hooks run ruff lint + Zig build + smoke test
- The `feature/community-feedback` branch has the latest security fixes and fuzz tests
- FFI native handlers use borrowed pointers (no heap alloc) — see ABI contract in `server.zig`
