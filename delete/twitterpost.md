# turboapi twitter posts (plain text, no markdown, no formatting, lowercase)

rach
@rachpradhan
·
oct 1

just shipped turboapi v0.3.12 🚀

40,000+ rps consistently across all load levels vs fastapi's 3,000-8,000. that's 5-13x faster.

with python 3.13 free-threading, we're seeing true parallelism - multiple threads executing python code simultaneously. no more gil blocking!

---

rach
@rachpradhan
·
oct 1

the secret sauce? built on rust from day one 🦀

started with hyper http server + satya validation (my other rust library that's 2-7x faster than pydantic).

phase 1: basic http + validation → 1.19x fastapi
phase 2: radix trie routing + deep satya → 1.26x fastapi
phase 3: free-threading unlocked → 2.84x fastapi

---

rach
@rachpradhan
·
oct 1

the numbers are wild 🔥

light load (50 connections):
- turboapi: 43,116 req/s
- fastapi: 8,204 req/s
- 5.3x faster

json processing:
- turboapi: 40,279 req/s
- fastapi: 3,191 req/s
- 12.6x faster

sub-millisecond latency (1.2ms) under load. this is python?

---

rach
@rachpradhan
·
oct 1

remember when people said "python can't be fast"?

watch this space. we're not just competing with fastapi anymore - we're setting new standards for python web performance.

5-13x faster, same familiar api. zero migration effort.

the no-gil future is here, and turboapi is ready for it 🚀

---

rach
@rachpradhan
·
oct 1

for the skeptics: try it yourself

```bash
# install free-threading python 3.13
uv python install 3.13.1+freethreaded
uv venv --python 3.13.1+freethreaded turbo-env

# install turboapi
pip install turboapi

# run benchmark
python tests/wrk_comparison.py
```

see those 40k+ rps numbers for yourself!

---

rach
@rachpradhan
·
oct 1

the architecture that makes this possible:

request flow:
http → rust http core → satya validation → your python code

no python overhead for http parsing, routing, or validation. all the slow parts run at rust speed.

result: python developer experience with rust performance.

---

rach
@rachpradhan
·
oct 1

shoutout to the incredible rust ecosystem that made this possible:

- hyper for battle-tested http
- tokio for async runtime
- pyo3 for seamless rust-python integration
- my own satya for 2-7x faster validation

this is what happens when you bet on the right foundations 🏗️

---

rach
@rachpradhan
·
oct 1

for the technical deep dive:

phase 1: proved rust-python integration works
phase 2: radix trie routing (o(log n) vs o(n)) + satya validation
phase 3: pyo3 0.26.0 + true parallelism with gil disabled

each phase built on the last, creating compound performance gains.

---

rach
@rachpradhan
·
oct 1

the free-threading integration? revolutionary.

multiple threads executing python code simultaneously. this was impossible before python 3.13.

```python
# this now runs with true parallelism!
@app.post("/users")
def create_user(request: user) -> user:
    return process_user(request)  # multiple threads can execute this
```

---

rach
@rachpradhan
·
oct 1

to the python community: this changes everything.

for the first time, python web apps can:
- scale linearly with core count
- handle 40k+ rps consistently
- maintain sub-2ms response times
- keep the developer experience we love

the no-gil future is here. who's ready? 🚀

---

# key speed gains from readme.md (plain text):

## benchmark results vs fastapi (wrk load testing)

light load (50 connections):
- root endpoint: 42,803 req/s (turboapi) vs 8,078 req/s (fastapi) = 5.3x faster
- simple endpoint: 43,375 req/s (turboapi) vs 8,536 req/s (fastapi) = 5.1x faster
- json endpoint: 41,696 req/s (turboapi) vs 3,208 req/s (fastapi) = 13.0x faster

medium load (200 connections):
- root endpoint: 42,874 req/s (turboapi) vs 8,220 req/s (fastapi) = 5.2x faster
- simple endpoint: 43,592 req/s (turboapi) vs 8,542 req/s (fastapi) = 5.1x faster
- json endpoint: 41,822 req/s (turboapi) vs 3,190 req/s (fastapi) = 13.1x faster

heavy load (500 connections):
- root endpoint: 43,057 req/s (turboapi) vs 7,897 req/s (fastapi) = 5.5x faster
- simple endpoint: 43,525 req/s (turboapi) vs 8,092 req/s (fastapi) = 5.4x faster
- json endpoint: 42,743 req/s (turboapi) vs 3,099 req/s (fastapi) = 13.8x faster

summary:
- average speedup: 5-13x faster than fastapi
- consistent 40,000+ rps across all load levels
- json processing: up to 13.8x faster
- true multi-core utilization with python 3.13 free-threading
- sub-millisecond latency under light load

## additional performance highlights:

http performance (phases 3-5)
- throughput: 4,019-7,320 rps vs fastapi's 1,116-2,917 rps
- latency: sub-millisecond p95 response times (0.91-1.29ms vs 2.79-3.00ms)
- improvement: 2.5-3.6x faster across all load levels

middleware performance (phase 5)
- average latency: 0.11ms vs fastapi's 0.71ms (6.3x faster)
- p95 latency: 0.17ms vs fastapi's 0.78ms (4.7x faster)
- concurrent throughput: 22,179 req/s vs fastapi's 2,537 req/s (8.7x faster)
- overall middleware: 7.5x fastapi performance

free-threading results
- true parallelism: multiple threads executing simultaneously
- linear scaling with core count
- no gil blocking for the first time in python web frameworks

## technical architecture benefits:

1. rust-powered http core: zero python overhead for request handling
2. zero middleware overhead: rust-native middleware pipeline
3. free-threading ready: true parallelism for python 3.13+
4. zero-copy optimizations: direct memory access, no python copying
5. intelligent caching: response caching with ttl optimization

## migration benefits:
- zero learning curve: same fastapi syntax
- instant migration: change 1 import line
- 5-10x performance improvement without code changes
- future-proof: ready for python 3.14+ no-gil default

---
these posts showcase turboapi's incredible 5-13x performance gains over fastapi while maintaining identical developer experience. perfect for sharing the revolutionary impact of rust-powered python web frameworks! 🚀
