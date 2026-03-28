# Tweet 10 — turboapi-core: two frameworks, one Zig core

**Best times to post (PST):** Tue-Thu, 8-10 AM
**Best times to post (SGT):** Tue-Thu, 11 PM - 1 AM

---

## Tweet 1 (Hook)

I was maintaining two routers in two repos doing the exact same thing.

turboAPI (Python framework, 134k req/s) and merjs (Zig full-stack, 100/100 Lighthouse) both needed URL matching, percent-decoding, query parsing. Same code, different files.

So I ripped the Zig HTTP core out into its own library.

---

## Tweet 2 (What it is)

turboapi-core. Zero-dep Zig library.

- Radix trie router with `{param}` + `*wildcard`
- `percentDecode`, `queryStringGet`, `statusText`, `formatHttpDate`
- Bounded thread-safe response cache

530 lines. 23 tests. Fuzz-tested.

Both frameworks now import it. Bug fix in the router? Both get it.

---

## Tweet 3 (What's NOT shared)

I didn't try to share the TCP server. That would've been a mistake.

turboAPI does raw socket I/O with manual HTTP/1.1 parsing and Python thread states per worker. merjs uses Zig's stdlib `std.http.Server`.

Different runtimes, different concurrency. But both need the same URL matcher and the same percent-decoder.

---

## Tweet 4 (Numbers)

Zero perf regression on turboAPI. Still 134k req/s, 0.16ms avg.

The import resolves at compile time. Same binary. Same benchmarks.

merjs: all routes still 200, builds clean, Lighthouse still 100.

---

## Tweet 5 (Use it yourself)

turboapi-core is its own repo. Any Zig project can use it:

```zig
const core = @import("turboapi-core");
var router = core.Router.init(allocator);
try router.addRoute("GET", "/users/{id}", "get_user");
```

https://github.com/justrach/turboapi-core

---

## Tweet 6 (CTA)

Shipped today:
- turboAPI v1.0.23
- merjs v0.2.1
- turboapi-core v0.1.0

https://github.com/justrach/turboAPI
https://github.com/justrach/merjs
https://github.com/justrach/turboapi-core

---

## Alt: Single tweet

I was copy-pasting router code between two Zig frameworks. Same radix trie, same percent-decoder, different repos.

Ripped it into its own library: turboapi-core. 530 lines, zero deps, fuzz-tested.

turboAPI v1.0.23 and merjs v0.2.1 both import it now. Zero perf regression. 134k req/s unchanged.

https://github.com/justrach/turboapi-core
