# Tweet 10 — Two frameworks, one Zig core

## Context

turboAPI v1.0.23 and merjs v0.2.1 shipped on the same day. The headline: both frameworks now share the same Zig HTTP primitives via turboapi-core, a new standalone library. This is the "two repos converge" story.

---

## Main Post

Shipped two framework releases today that share the same Zig HTTP core.

**turboAPI v1.0.23** — Python web framework, 134k req/s
**merjs v0.2.1** — Zig-native full-stack framework, 100/100 Lighthouse

Both now import **turboapi-core**: a zero-dep Zig library with a radix trie router, HTTP utilities, and a bounded response cache.

The idea: I was maintaining two separate routers, two separate query parsers, two separate percent-decoders. Same problems, same solutions, different files. That's a bug waiting to happen.

So I extracted the shared primitives into one library. 530-line radix trie router with `{param}` + `*wildcard` matching, fuzz-tested. Pure HTTP utilities — `percentDecode`, `queryStringGet`, `statusText`, `formatHttpDate`. Generic bounded cache with mutex.

turboAPI uses it for its Python-to-Zig bridge. merjs uses it for its Zig-native server. The router doesn't know about Python or WASM or SSR — it takes a path, returns a match. Each framework wires its own dispatch on top.

What's NOT shared: the TCP server layer. turboAPI does raw `std.net.Stream` with manual HTTP/1.1 parsing and a Python thread pool. merjs uses `std.http.Server` from the Zig stdlib. Different concurrency models for different runtimes. Trying to share that would've been a leaky abstraction.

Zero performance regression on turboAPI. The import resolves at compile time — same binary, same benchmarks.

turboapi-core is its own repo now. Any Zig project can use it:

```zig
// build.zig.zon
.turboapi_core = .{
    .url = "git+https://github.com/justrach/turboapi-core.git#<commit>",
    .hash = "...",
},

// your code
const core = @import("turboapi-core");
var router = core.Router.init(allocator);
try router.addRoute("GET", "/users/{id}", "get_user");
```

Repos:

- `github.com/justrach/turboapi-core` — the shared library
- `github.com/justrach/turboAPI` — Python framework (v1.0.23)
- `github.com/justrach/merjs` — Zig full-stack framework (v0.2.1)

---

## Shorter Version

Shipped turboAPI v1.0.23 and merjs v0.2.1 today.

Both frameworks now share the same Zig HTTP core: **turboapi-core**.

One radix trie router. One set of HTTP utilities. One bounded cache. Zero-dep, fuzz-tested, 530 lines of Zig.

turboAPI wraps it for Python. merjs wraps it for Zig SSR. Bug fix in the router fixes both.

No performance regression. 134k req/s unchanged. The import resolves at compile time.

`github.com/justrach/turboapi-core`

---

## Thread Version

### 1/4

Shipped two framework releases today:

- turboAPI v1.0.23 (Python, 134k req/s)
- merjs v0.2.1 (Zig full-stack, 100/100 Lighthouse)

Both now import the same Zig library for routing and HTTP parsing.

### 2/4

**turboapi-core** is a zero-dep Zig library:

- Radix trie router — `{param}`, `*wildcard`, method-aware, fuzz-tested
- HTTP utils — `percentDecode`, `queryStringGet`, `statusText`, `formatHttpDate`
- Bounded cache — thread-safe, generic, configurable max entries

530 lines. 23 tests. Any Zig project can use it.

### 3/4

What I didn't share: the TCP server. turboAPI manages Python thread states per worker and writes raw HTTP/1.1 to sockets. merjs uses Zig's stdlib `std.http.Server`.

Different runtimes need different concurrency. But both runtimes need the same URL matching and the same percent-decoder.

### 4/4

The real win isn't code reuse — it's that the router now has two consumers exercising it in production. turboAPI's fuzz tests found edge cases. merjs's file-based routing will stress the dynamic matching.

One library, two stress testers, zero duplication.

`github.com/justrach/turboapi-core`
`github.com/justrach/turboAPI`
`github.com/justrach/merjs`

---

## Likely Questions

### "Why not just use a popular Zig HTTP library?"

turboAPI's router handles 134k req/s in production with fuzz testing. Swapping to an unproven library is a regression risk. Also, most Zig HTTP libs bundle a full server — I only needed routing and utilities.

### "Is turboapi-core production-ready?"

It's the same code that's been serving turboAPI since v1.0.01. The extraction was a reorganization, not a rewrite.

### "Will merjs fully switch to turboapi-core's router?"

The dependency is wired and the build passes. Next step is method-based API routing for `api/` endpoints. Page routes keep merjs's file-based router for now. Tracked in justrach/merjs#66.

### "Can I use turboapi-core without either framework?"

Yes. `zig fetch --save=turboapi_core "git+https://github.com/justrach/turboapi-core.git#..."` and you're set. It's a pure Zig module with zero dependencies.
