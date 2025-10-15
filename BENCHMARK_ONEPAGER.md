# TurboAPI Benchmark Methodology - One Pager

## The Question
> "Did you not replicate the process across the cores? Threads have more overhead than events."

## Our Answer
**We agree - that's why we use events, not threads!** 🎯

---

## Architecture

```
┌─────────────────────────────────────┐
│  Single Process (50MB memory)       │
│                                     │
│  ┌───────────────────────────────┐ │
│  │  Tokio Runtime                │ │
│  │  ├─ 14 worker threads         │ │
│  │  ├─ 7,168 async tasks         │ │
│  │  └─ Work-stealing scheduler   │ │
│  └───────────────────────────────┘ │
│                                     │
│  ┌───────────────────────────────┐ │
│  │  Rust HTTP (Hyper)            │ │
│  │  └─ Event-driven I/O          │ │
│  └───────────────────────────────┘ │
└─────────────────────────────────────┘
         ▲
         │ All 14 cores utilized
         │ ~1400% CPU usage
         └─ Verified with `top`
```

---

## Key Facts

| Metric | Value |
|--------|-------|
| **Architecture** | Event-driven async I/O |
| **CPU** | M3 Max (14 cores) |
| **Utilization** | ~1400% (all cores) |
| **Model** | Async tasks (2KB each) |
| **NOT** | OS threads (8MB each) |
| **Processes** | 1 (single process) |
| **Threads** | 14 (Tokio workers) |
| **Capacity** | 7,168 concurrent tasks |

---

## Comparison

### ❌ Thread-Per-Request (What We DON'T Do)
```
Request → OS Thread (8MB)
├─ Blocking I/O
├─ Kernel context switch (1-10μs)
└─ Max ~10K connections

Needs multiple processes to use all cores
```

### ✅ Event-Driven (What We DO)
```
Request → Async Task (2KB)
├─ Non-blocking I/O
├─ Userspace switch (~10ns)
└─ Max ~10M connections

Single process uses all cores automatically
```

---

## Performance

- **Sync Endpoints**: 184,370 RPS (0.24ms latency)
- **Async Endpoints**: 12,269 RPS (3.93ms latency)
- **vs FastAPI**: 10-25× faster
- **CPU Usage**: All 14 cores at 100%

---

## Why No Multiple Processes?

✅ **Event-driven I/O**: Single process handles 10K+ connections  
✅ **Tokio work-stealing**: Automatic multi-core load balancing  
✅ **No GIL**: Python 3.13t/3.14t free-threading  
✅ **Rust HTTP**: Zero Python overhead for I/O  
✅ **More efficient**: No IPC overhead, shared memory  

---

## Verification

```bash
# Start server
python examples/multi_route_app.py &

# Check CPU usage
top -pid $(pgrep -f multi_route_app)
# Shows ~1400% CPU (14 cores × 100%)

# Run benchmark
wrk -t4 -c50 -d30s http://127.0.0.1:8000/users/123
# Result: 184K RPS
```

---

## We're Transparent

✅ All code is open source  
✅ All benchmarks are reproducible  
✅ All hardware specs documented  
✅ All methodology explained  
✅ We document limitations honestly  

---

## Learn More

- **Quick FAQ**: [BENCHMARK_FAQ.md](BENCHMARK_FAQ.md)
- **Full Response**: [BENCHMARK_METHODOLOGY_RESPONSE.md](BENCHMARK_METHODOLOGY_RESPONSE.md)
- **Architecture**: [docs/ARCHITECTURE_DIAGRAM.md](docs/ARCHITECTURE_DIAGRAM.md)
- **GitHub**: https://github.com/justrach/turboAPI

---

## Bottom Line

**We use events (async I/O), not threads.**  
**All 14 cores are utilized automatically.**  
**Single process is more efficient than multiple processes.**  
**We welcome scrutiny and questions!** 🚀

---

*TurboAPI: FastAPI syntax with Rust performance*
