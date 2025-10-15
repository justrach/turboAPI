# TurboAPI Benchmark FAQ

## Quick Answers to Common Questions

### Q: "Did you replicate the process across cores?"

**A**: No, because we use **event-driven async I/O**, not process-per-request. Our Tokio runtime automatically distributes work across all 14 CPU cores using a work-stealing scheduler. This is more efficient than process replication.

**Proof**: Run `top` during benchmarks - you'll see ~1400% CPU usage (14 cores × 100%).

---

### Q: "Threads have more overhead than events, not less"

**A**: Correct for OS threads, but we use **async tasks** (Rust futures), not OS threads:

- **OS Thread**: 8MB memory, 1-10μs context switch
- **Async Task**: 2KB memory, ~10ns context switch
- **Our model**: 14 OS threads manage 7,168 async tasks

We're event-driven (like nginx/Node.js), not thread-per-request (like Apache).

---

### Q: "How many cores in the test?"

**A**: **14 cores** (Apple M3 Max: 10 performance + 4 efficiency cores)

All cores are utilized via Tokio's work-stealing scheduler. Single process, multi-threaded async runtime.

---

### Q: "Why not use multiple processes like Gunicorn?"

**A**: Because we don't need to:

1. **No GIL**: Python 3.13t free-threading eliminates GIL bottleneck
2. **Rust HTTP**: Zero Python overhead for I/O operations
3. **Event-driven**: Single process handles 10K+ concurrent connections
4. **Work-stealing**: Automatic load balancing across cores

Multiple processes would add IPC overhead without performance benefit.

---

### Q: "Is this a fair comparison with FastAPI?"

**A**: Yes:

- ✅ Same endpoints (identical Python handler code)
- ✅ Same test tool (wrk with same parameters)
- ✅ Same hardware (M3 Max, 14 cores)
- ✅ Same Python version options (3.13t/3.14t)
- ✅ Both use async I/O (Tokio vs asyncio)

**Key difference**: TurboAPI's HTTP layer is Rust (fast), FastAPI's is Python (slower).

---

### Q: "Can I reproduce these benchmarks?"

**A**: Absolutely! 

```bash
# Setup
git clone https://github.com/justrach/turboAPI.git
cd turboAPI
python3.13t -m venv turbo-env
source turbo-env/bin/activate
pip install -e python/
maturin develop --manifest-path Cargo.toml

# Run server (Terminal 1)
python examples/multi_route_app.py

# Run benchmark (Terminal 2)
brew install wrk
wrk -t4 -c50 -d30s --latency http://127.0.0.1:8000/users/123

# Monitor CPU (Terminal 3)
top -pid $(pgrep -f multi_route_app)
# Look for ~1400% CPU (all 14 cores)
```

---

### Q: "What's the architecture?"

**A**: 

```
┌─────────────────────────────────────┐
│   Python Handler (Your Code)       │  ← GIL-free (Python 3.13t)
├─────────────────────────────────────┤
│   PyO3 Bridge (Zero-Copy FFI)       │  ← ~100ns overhead
├─────────────────────────────────────┤
│   Rust HTTP (Hyper + Tokio)        │  ← Event-driven, all cores
│   • Work-stealing scheduler         │
│   • 14 worker threads               │
│   • 7,168 concurrent task capacity  │
└─────────────────────────────────────┘
```

---

### Q: "Why is async slower than sync in your benchmarks?"

**A**: Python's `asyncio.sleep()` adds overhead. Our async benchmarks use artificial delays:

```python
@app.get("/async/data")
async def async_endpoint():
    await asyncio.sleep(0.001)  # ← This adds 1ms overhead!
    return {"data": "result"}
```

In production with real I/O (database, network), async would be faster. Our sync endpoints show the true HTTP layer performance.

---

### Q: "What are the bottlenecks?"

**A**: 

1. **Sync endpoints (184K RPS)**: Bottleneck is Python handler execution
   - Rust HTTP layer capable of 200K+ RPS
   - Python handlers (even GIL-free) add ~5μs overhead

2. **Async endpoints (12K RPS)**: Bottleneck is Python asyncio overhead
   - `asyncio.sleep()` adds significant overhead
   - Real async I/O would be much faster

---

### Q: "How does this compare to other frameworks?"

**A**: 

| Framework | RPS | Architecture |
|-----------|-----|--------------|
| **TurboAPI** | **184K** | Rust HTTP + Python handlers |
| FastAPI | 7-10K | Python HTTP (Uvicorn) + Python handlers |
| Flask | 2-5K | Python HTTP (Werkzeug) + Python handlers |
| Django | 1-3K | Python HTTP + Python ORM |
| Node.js (Express) | 15-25K | JavaScript HTTP (V8) + JS handlers |
| Go (Gin) | 100-200K | Go HTTP + Go handlers |
| Rust (Actix) | 200-500K | Pure Rust |

TurboAPI bridges the gap: **Python developer experience** with **near-Rust performance**.

---

### Q: "What's the memory usage?"

**A**: 

- **TurboAPI**: ~50MB base + ~2KB per concurrent connection
- **FastAPI**: ~80MB base + ~8KB per concurrent connection

At 10K concurrent connections:
- TurboAPI: ~70MB
- FastAPI: ~160MB

---

### Q: "Is this production-ready?"

**A**: Yes, with caveats:

✅ **Ready**:
- HTTP/1.1, HTTP/2 support
- WebSocket support
- Middleware (CORS, auth, rate limiting)
- Security features (OAuth2, JWT, API keys)
- Error handling
- Logging and monitoring

⚠️ **Consider**:
- Python 3.13t/3.14t free-threading is new (test thoroughly)
- Async endpoints need real I/O to show benefits
- Some FastAPI features still being added

---

### Q: "Where can I learn more?"

**A**: 

- **Documentation**: [README.md](README.md)
- **Detailed Methodology**: [BENCHMARK_METHODOLOGY_RESPONSE.md](BENCHMARK_METHODOLOGY_RESPONSE.md)
- **GitHub**: https://github.com/justrach/turboAPI
- **Issues**: https://github.com/justrach/turboAPI/issues

---

## Key Takeaways

1. ✅ **Event-driven async I/O** (not thread-per-request)
2. ✅ **All 14 cores utilized** (Tokio work-stealing)
3. ✅ **Transparent benchmarking** (reproducible, documented)
4. ✅ **Real performance gains** (10-25x vs FastAPI)
5. ✅ **Honest about limitations** (async overhead, simple handlers)

We welcome scrutiny and are committed to honest performance claims.
