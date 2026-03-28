# Tweet 10 — turboapi-core: a router library, not a server

**Best times to post (PST):** Tue-Thu, 8-10 AM
**Best times to post (SGT):** Tue-Thu, 11 PM - 1 AM

---

## Tweet 1 (Hook)

I built a URL router in Zig that's faster than Go's httprouter.

43.5M lookups/sec. 23ns per match. Adversarial-verified.

It's not a server. It's not a framework. It's a library — you give it a path, it gives you a match.

---

## Tweet 2 (What it is)

turboapi-core. A Zig library. Zero dependencies.

- Prefix-compressed radix trie (like Go's httprouter, but in Zig)
- Method-indexed trees — one trie per GET/POST/PUT/etc
- `{param}` extraction, `*wildcard` matching, path traversal rejection
- HTTP utilities: percentDecode, queryStringGet, statusText

530 lines of Zig. 23 tests. Fuzz-tested.

Not an HTTP server. Not a framework. Just the routing + HTTP parsing bits that every server needs but nobody wants to rewrite.

---

## Tweet 3 (The benchmark story)

How I got here:

v1: Segment-by-segment trie + StringHashMap → 19M/s (52ns)
v2: Prefix compression + indices array → 37M/s (27ns)
v3: Method-indexed trees → 43.5M/s (23ns)

Go httprouter: 40M/s (25ns)

Each optimization was inspired by reading Go's httprouter source. Zig just let me take the same ideas further — no GC, no interface dispatch, no sync.Pool overhead.

---

## Tweet 4 (Honest numbers)

I also wrote an adversarial benchmark to make sure the numbers aren't fake:

- Anti-DCE: forces use of every result (handler key + params) → 41.7M/s
- Runtime paths: generates new URLs every iteration (no string caching) → 28.6M/s
- 100-route table: scaling test → 20M/s

The 43.5M headline is for a fixed 16-route API. Real traffic with varying param values is closer to 28M. Both beat Go.

---

## Tweet 5 (Who uses it)

Two frameworks share this one library:

turboAPI — Python web framework. 134k req/s. Uses turboapi-core for routing, HTTP utils, response cache.

merjs — Zig full-stack framework. 100/100 Lighthouse. Uses turboapi-core for the router (API method dispatch coming next).

Bug fix in the router → both frameworks get it. Fuzz test finds an edge case → both are covered.

---

## Tweet 6 (CTA)

https://github.com/justrach/turboapi-core

530 lines. Zero deps. Faster than Go. Fuzz-tested.

Add it to your Zig project:
```
zig fetch --save=turboapi_core "git+https://github.com/justrach/turboapi-core.git#main"
```

---

## Alt: Single tweet

Built a URL router in Zig that beats Go's httprouter.

43.5M lookups/sec (23ns). Adversarial-verified — not cached, not fake.

It's not a server. It's a library: prefix-compressed radix trie, method-indexed trees, fuzz-tested. 530 lines, zero deps.

turboAPI and merjs both use it.

https://github.com/justrach/turboapi-core
