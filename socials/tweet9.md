# Tweet 9 — turboapi-core: shared Zig HTTP library

## Context

We extracted the generic HTTP layer from turboAPI into a standalone Zig library called **turboapi-core**. Both turboAPI (Python framework) and merjs (Zig full-stack framework) now share the same router, HTTP utilities, and caching primitives. Zero performance regression.

This is an architecture post, not a benchmark post. The angle: two frameworks, one shared Zig core.

---

## Main Post

We just extracted the Zig HTTP core from turboAPI into its own library: **turboapi-core**.

Two frameworks — turboAPI (Python) and merjs (Zig full-stack) — now share the same:

- radix trie router (fuzz-tested, `{param}` + `*wildcard`)
- HTTP utilities (percent-decode, query parsing, date formatting)
- bounded response cache (thread-safe, generic)

The router was already 530 lines of pure Zig with zero Python deps. Extracting it was a clean cut — delete the file from turboAPI, import from the shared library, done.

No performance regression. Same 134k req/s, same 0.16ms avg latency. The import resolves at compile time so there's zero runtime cost to the split.

Why do this:

turboAPI is a Python web framework with a Zig HTTP backend. merjs is a Zig-native full-stack framework. They had separate routers, separate HTTP parsing, separate everything — even though the core problems (match a URL, decode a query string, format a Date header) are identical.

Now they share that code. Bug fix in the router? Both frameworks get it. Fuzz test finds an edge case? Both frameworks are covered.

The TCP/server layer is NOT shared — turboAPI uses raw `std.net.Stream` with manual HTTP/1.1 parsing, merjs uses `std.http.Server` from the Zig stdlib. Those are different abstractions for different use cases. We only extracted what genuinely belongs in a shared library.

turboapi-core has zero dependencies. Pure Zig. 23 tests including fuzz seeds for the router, percent-decoder, and query parser. Any Zig project can use it.

Links:

- `github.com/justrach/turboAPI` (branch: `feature/core-extraction`)
- `github.com/justrach/merjs`

---

## Shorter Version (Twitter-length)

Extracted the Zig HTTP core from turboAPI into a standalone library: **turboapi-core**.

Both turboAPI (Python framework) and merjs (Zig full-stack) now share the same radix trie router, HTTP utilities, and response cache.

530 lines of pure Zig, zero deps, fuzz-tested. No perf regression — still 134k req/s.

Two frameworks, one shared core. Bug fix in the router fixes both.

---

## Thread Version

### 1/5

Extracted the Zig HTTP core from turboAPI into its own library.

Both turboAPI (Python web framework) and merjs (Zig-native full-stack framework) now import the same router, HTTP utils, and cache from **turboapi-core**.

### 2/5

What's shared:

- Radix trie router — method-aware, `{param}` and `*wildcard`, fuzz-tested
- `percentDecode`, `queryStringGet`, `statusText`, `formatHttpDate`
- Generic bounded cache with mutex + max entry cap

What's NOT shared: the TCP server layer. turboAPI does raw socket I/O with manual HTTP parsing. merjs uses Zig's stdlib `std.http.Server`. Different tools for different jobs.

### 3/5

The extraction was clean because the router was already fully generic — 530 lines of Zig with zero Python deps. It takes an allocator, stores string handler keys, returns matches with path params. Both frameworks just wire in their own dispatch.

### 4/5

Performance: identical. 134k req/s, 0.16ms avg latency. The module import resolves at compile time — the generated code is byte-for-byte the same as before the split.

### 5/5

This is the architecture I wanted from the start: a shared Zig HTTP core with framework-specific adapters on top. turboAPI adapts it for Python. merjs adapts it for Zig SSR + WASM.

Next: merjs gets method-based API routing via the shared radix trie.

`github.com/justrach/turboAPI`
`github.com/justrach/merjs`

---

## Likely Questions

### "Why not share the server too?"

turboAPI's connection pool manages Python thread states (PyThreadState per worker). merjs uses `std.Thread.Pool` with `std.http.Server`. Trying to share the TCP layer would create a leaky abstraction that helps neither framework.

### "Can other Zig projects use turboapi-core?"

Yes. Zero deps, pure Zig. Add it to your `build.zig.zon` and `@import("turboapi-core").Router`.

### "Does merjs actually use the router yet?"

The dependency is wired and builds pass. The immediate integration is HTTP utilities. Method-based API routing via the radix trie is the next step (tracked in justrach/merjs#66).

### "Why not use an existing Zig HTTP library?"

turboAPI's router is battle-tested at 134k+ req/s with fuzz testing. It's already proven in production. Swapping to an external router would be a regression risk for zero gain.
