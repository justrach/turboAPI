# Changelog

All notable changes to TurboAPI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - Unreleased

### Added

- **Async Handler Fast Paths** - True async support via Tokio runtime
  - `SimpleAsyncFast` handler type for GET async handlers
  - `BodyAsyncFast` handler type for POST/PUT async handlers
  - `add_route_async_fast()` method for async handler registration
  - pyo3-async-runtimes integration for Python coroutine conversion
  - Automatic handler classification for sync vs async detection

- **HTTP/2 Support** - Full HTTP/2 implementation
  - `Http2Server` class with h2 protocol support
  - Server push capabilities via `ServerPush`
  - Stream multiplexing for concurrent requests

- **TLS Support** - Secure HTTPS connections
  - rustls backend (default, pure Rust)
  - Optional OpenSSL backend via feature flag
  - PEM certificate and key loading

- **WebSocket Improvements** - Better message handling
  - Improved text message routing to Python handlers
  - Binary message handler support
  - Clean connection lifecycle management

- **Comprehensive Benchmarks** - Performance testing suite
  - `python_benchmark.py` - Full framework benchmarks
  - `async_comparison_bench.py` - Sync vs async comparison
  - `performance_bench.rs` - Low-level Rust benchmarks

- **Documentation**
  - `docs/ASYNC_HANDLERS.md` - Async handler guide
  - `docs/BENCHMARKS.md` - Benchmarking guide
  - `docs/ARCHITECTURE.md` - Internal architecture
  - DeepWiki integration for documentation

### Changed

- Handler classification now detects coroutine functions
- Async handlers route through Tokio instead of Enhanced path
- Simplified TokioRuntime (removed loop sharding complexity)

### Performance

- Async handlers use Tokio work-stealing scheduler
- Sequential latency: 1.3-1.4x faster than FastAPI
- Concurrent latency: 1.2-1.8x faster than FastAPI
- JSON endpoints show largest improvement (1.8x concurrent)

## [0.3.0] - 2025-09-30

### Fixed
- **Windows Unicode Encoding Error**: Fixed critical `UnicodeEncodeError` that prevented TurboAPI from importing on Windows systems with cp1252 encoding
  - Added UTF-8 encoding configuration for Windows stdout
  - Implemented graceful fallback to ASCII symbols when emojis can't be displayed
  - Enhanced CI/CD test scripts to handle Windows encoding properly
- **macOS Wheel Selection**: Improved wheel selection logic in CI to prevent architecture mismatches

### Changed
- `version_check.py` now detects terminal emoji support and falls back to ASCII symbols (`[OK]`, `[X]`, etc.) on incompatible systems
- Updated GitHub Actions workflows to set `PYTHONIOENCODING=utf-8` on Windows
- Enhanced error messages with better traceback reporting in CI tests

## [0.3.1] - 2025-09-29

### Fixed
- **Rate Limiting**: Completely resolved restrictive rate limiting that was blocking high-performance benchmarks
  - Rate limiting now disabled by default for maximum performance
  - Configurable via `app.configure_rate_limiting(enabled=False)`

### Added
- Performance verified at 180K+ RPS with wrk testing
- Stress tested up to 10M theoretical req/s with zero 429 errors
- AGENTS.md documentation for AI assistant integration

### Changed
- Documentation updated with proper v0.3.1 installation instructions
- Version consistency across Cargo.toml and pyproject.toml

## [0.3.0] - 2025-09-28

### Added
- Initial release with FastAPI-compatible syntax
- Rust-powered HTTP core for maximum performance
- Python 3.13+ free-threading support
- 5-10x performance improvement over FastAPI
- Zero-copy optimizations and intelligent caching
- Comprehensive test suite and benchmarking tools

### Features
- FastAPI-compatible decorators and routing
- Sub-millisecond latency under heavy load
- True multi-threading parallelism (no GIL)
- Support for all HTTP methods (GET, POST, PUT, DELETE, PATCH)
- Path parameters, query parameters, and request body support
