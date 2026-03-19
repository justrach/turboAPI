# TurboAPI — TechEmpower Framework Benchmark

[TurboAPI](https://github.com/justrach/turboAPI) is a drop-in FastAPI replacement with a Zig HTTP core.

## Test URLs

- `/json` — `{"message": "Hello, World!"}`
- `/plaintext` — `Hello, World!`

## Architecture

- **HTTP core**: Zig 0.15, 24-thread pool, zero-alloc response pipeline
- **Python**: 3.14t free-threaded (no GIL)
- **Response caching**: noargs handlers cached after first call
- **CORS**: Zig-native (0% overhead)

## Local numbers (Apple Silicon M3 Pro)

- JSON: 150,000 req/s
- Plaintext: 150,000 req/s
