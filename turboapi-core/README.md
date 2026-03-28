<p align="center">
  <strong>turboapi-core</strong>
</p>

<p align="center">
  <a href="https://github.com/justrach/turboapi-core"><img src="https://img.shields.io/badge/zig-0.15-f7a41d?style=flat-square" alt="Zig 0.15" /></a>
  <img src="https://img.shields.io/badge/deps-zero-brightgreen?style=flat-square" alt="Zero deps" />
  <img src="https://img.shields.io/badge/router-43.5M%20lookups%2Fs-f7a41d?style=flat-square" alt="43.5M lookups/s" />
  <a href="https://github.com/justrach/turboapi-core/blob/main/LICENSE"><img src="https://img.shields.io/github/license/justrach/turboapi-core?style=flat-square" alt="License" /></a>
  <a href="https://deepwiki.com/justrach/turboapi-core"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki" /></a>
</p>

<h1 align="center">turboapi-core</h1>

<h3 align="center">Shared Zig HTTP primitives. Faster than Go's httprouter.</h3>

<p align="center">
  Radix trie router · HTTP utilities · Bounded cache · Fuzz-tested · Zero dependencies
</p>

<p align="center">
  <a href="#benchmarks">Benchmarks</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#modules">Modules</a> ·
  <a href="#consumers">Consumers</a> ·
  <a href="https://turboapi.trilok.ai/httpcore">Live Dashboard</a>
</p>

---

## Benchmarks

Adversarial-verified (anti-DCE, runtime-generated paths, correctness-checked). Apple M3 Pro, `ReleaseFast`, 16 routes, 5M iterations.

### Cross-language router comparison

| Router | Language | lookups/sec | ns/op |
|---|---|---|---|
| **turboapi-core** | **Zig** | **43.5M/s** | **23ns** |
| Go httprouter | Go | 40M/s | 25ns |
| find-my-way (Fastify) | Node.js | 10.5M/s | 95ns |
| Go fasthttp/router | Go | 3.4M/s | 295ns |
| Starlette (FastAPI) | Python | 4M/s | 249ns |

### Route type breakdown

| Route type | ops/sec | ns/op |
|---|---|---|
| Static `GET /health` | 100M/s | 10ns |
| Deep static `GET /api/v1/users` | 91M/s | 11ns |
| 1-param `GET /api/v1/users/42` | 52M/s | 19ns |
| 2-param `GET /users/42/posts/7` | 34M/s | 29ns |
| Wildcard `GET /static/css/app.css` | 15.6M/s | 64ns |
| Miss `GET /nonexistent` | 100M/s | 10ns |

### Adversarial verification

| Test | What it proves | Result |
|---|---|---|
| Anti-DCE | Compiler can't optimize away results | 41.7M/s (24ns) |
| Runtime-generated paths | No string interning inflation | 28.6M/s (35ns) |
| 100-route table | Scaling under many routes | 20M/s (50ns) |
| Correctness | Params extracted, misses return null | PASS |

> **Methodology:** All benchmarks force use of every result (handler key + param values) to prevent dead code elimination. Runtime path tests generate unique paths via `bufPrint` every iteration. Match/miss counts are verified (12 matches + 1 miss per iteration). [Benchmark source](bench_adversarial.zig).

---

## Quick Start

**Requirements:** Zig 0.15+

### Add the dependency

```bash
zig fetch --save=turboapi_core "git+https://github.com/justrach/turboapi-core.git#main"
```

### Wire in build.zig

```zig
const core_dep = b.dependency("turboapi_core", .{});
const core_mod = core_dep.module("turboapi-core");
your_module.addImport("turboapi-core", core_mod);
```

### Use it

```zig
const core = @import("turboapi-core");

// Router
var router = core.Router.init(allocator);
defer router.deinit();

try router.addRoute("GET", "/", "index");
try router.addRoute("GET", "/users/{id}", "get_user");
try router.addRoute("POST", "/users", "create_user");
try router.addRoute("GET", "/files/*path", "serve_file");

// Lookup
if (router.findRoute("GET", "/users/42")) |*match| {
    defer match.deinit();
    // match.handler_key == "get_user"
    // match.params.get("id") == "42"
}

// HTTP utilities
var buf: [256]u8 = undefined;
const decoded = core.http.percentDecode("hello+world%21", &buf);
// decoded == "hello world!"

const val = core.http.queryStringGet("q=zig&page=2", "page");
// val == "2"

const status = core.http.statusText(404);
// status == "Not Found"

var date_buf: [40]u8 = undefined;
const date = core.http.formatHttpDate(&date_buf);
// date == "Fri, 28 Mar 2026 05:00:00 GMT"
```

---

## Modules

### `router` — Prefix-compressed radix trie

Method-indexed trees (one trie per HTTP method). Prefix compression stores `/api/v1/users` as one node. Child lookup via `indices` byte array. Priority ordering for hot routes.

- `{param}` — named path parameters
- `*wildcard` — catch-all (matches rest of path, rejects `..` and `.`)
- Zero-alloc param extraction — fixed-size stack array (up to 16 params)
- Static > param > wildcard priority
- Fuzz-tested with adversarial inputs (null bytes, deep nesting, path traversal)

### `http` — Pure HTTP utility functions

| Function | What it does |
|---|---|
| `queryStringGet(qs, key)` | Fast `key=value&...` lookup, no allocation |
| `percentDecode(src, buf)` | `%XX` and `+` decoding into caller's buffer |
| `hexNibble(ch)` | Hex char to nibble (`'a'` → `10`) |
| `statusText(code)` | `404` → `"Not Found"` |
| `formatHttpDate(buf)` | RFC 2822 date for `Date:` header |

### `cache` — Bounded thread-safe cache

`BoundedCache(V)` — generic string-keyed cache with mutex and configurable max entries. Silently drops inserts at capacity. Used for response caching in turboAPI.

### `types` — Shared types

`HeaderPair` — HTTP header name/value pair (borrows from request buffer).

---

## Consumers

| Project | What it is | How it uses turboapi-core |
|---|---|---|
| [turboAPI](https://github.com/justrach/turboAPI) | Python web framework (134k req/s) | Router + HTTP utils + cache |
| [merjs](https://github.com/justrach/merjs) | Zig full-stack framework (100/100 Lighthouse) | Router (wired, API routing next) |

---

## Running Tests

```bash
# Unit tests (includes fuzz seed corpus)
zig build test

# Continuous fuzzing (runs indefinitely)
zig build test --fuzz

# Benchmark (original)
zig build-exe bench.zig -OReleaseFast -lc && ./bench

# Adversarial benchmark (anti-DCE, runtime paths, correctness)
zig build-exe bench_adversarial.zig -OReleaseFast -lc && ./bench_adversarial
```

---

## Project Structure

```
turboapi-core/
├── src/
│   ├── root.zig       # Public API surface — the only import consumers use
│   ├── router.zig     # Prefix-compressed radix trie, method-indexed
│   ├── http.zig       # percentDecode, queryStringGet, statusText, formatHttpDate
│   ├── cache.zig      # BoundedCache(V) — thread-safe bounded map
│   └── types.zig      # HeaderPair
├── bench.zig          # Router benchmark (per-route-type breakdown)
├── bench_adversarial.zig  # Anti-DCE + runtime paths + scaling + correctness
├── build.zig          # Zig build system
└── build.zig.zon      # Zero external dependencies
```

---

## How it got fast

Three optimizations inspired by [Go's httprouter](https://github.com/julienschmidt/httprouter), adapted for Zig:

1. **Prefix compression** — consecutive static path segments stored as one node. `/api/v1/users` is a single prefix comparison, not 4 hash lookups.

2. **Method-indexed trees** — one radix trie per HTTP method. `findRoute("GET", ...)` goes directly to the GET tree. No per-node method HashMap.

3. **Indices array** — first byte of each child's path stored in a flat array. Child lookup scans <16 bytes instead of hashing.

See [issue #1](https://github.com/justrach/turboapi-core/issues/1) for the full analysis.

---

## License

MIT
