# Tweet 10 - turboapi-core: a router library, not a server

**Best times to post (PST):** Tue-Thu, 8-10 AM
**Best times to post (SGT):** Tue-Thu, 11 PM - 1 AM

---

## Tweet 1 (Hook)

I built a URL router in Zig that's faster than Go's httprouter.

43.5M lookups/sec. 23ns per match. Adversarial-verified.

It's not a server. It's not a framework. It's a library. You give it a path, it gives you a match.

---

## Tweet 2 (Why)

I'm building two things in Zig: a Python web framework (turboAPI) and a Zig-native full-stack framework (merjs).

Both need URL routing. Both need percent-decoding. Both need query string parsing.

I was writing the same code twice. So I pulled the shared bits into one library.

---

## Tweet 3 (What it is)

turboapi-core. A Zig library. Zero dependencies.

- Prefix-compressed radix trie (same algorithm as Go's httprouter)
- Method-indexed trees, one trie per GET/POST/PUT/etc
- `{param}` extraction, `*wildcard` matching, path traversal rejection
- HTTP utilities: percentDecode, queryStringGet, statusText

530 lines of Zig. 23 tests. Fuzz-tested.

Not an HTTP server. Not a framework. Just the routing and HTTP parsing bits that every server needs but nobody wants to rewrite.

---

## Tweet 4 (The benchmark story)

How I got here:

v1: Segment-by-segment trie + StringHashMap. 19M/s (52ns)
v2: Prefix compression + indices array. 37M/s (27ns)
v3: Method-indexed trees. 43.5M/s (23ns)

Go httprouter: 40M/s (25ns)

Each optimization came from reading Go's httprouter source. Zig let me take the same ideas further. No GC, no interface dispatch, no sync.Pool overhead.

---

## Tweet 5 (Honest numbers)

I also wrote an adversarial benchmark to make sure the numbers aren't fake:

- Anti-DCE: forces use of every result (handler key + params). 41.7M/s
- Runtime paths: generates new URLs every iteration, no string caching. 28.6M/s
- 100-route table: scaling test. 20M/s

The 43.5M headline is for a fixed 16-route API. Real traffic with varying param values is closer to 28M. Both beat Go.

---

## Tweet 6 (Who uses it)

Two frameworks share this one library:

turboAPI. Python web framework. 134k req/s. Uses turboapi-core for routing, HTTP utils, response cache.

merjs. Zig full-stack framework. 100/100 Lighthouse. Uses turboapi-core for the router, API method dispatch coming next.

Bug fix in the router, both frameworks get it. Fuzz test finds an edge case, both are covered.

---

## Tweet 7 (CTA)

https://github.com/justrach/turboapi-core

530 lines. Zero deps. Faster than Go. Fuzz-tested.

Add it to your Zig project:
```
zig fetch --save=turboapi_core "git+https://github.com/justrach/turboapi-core.git#main"
```

---

## Alt: Single tweet

I'm building a Python web framework and a Zig full-stack framework. Both need URL routing. Both need percent-decoding. Was writing the same code twice.

Pulled it into one library: turboapi-core. 43.5M lookups/sec. Faster than Go's httprouter. 530 lines, zero deps, fuzz-tested.

https://github.com/justrach/turboapi-core
