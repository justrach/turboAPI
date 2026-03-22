# zigprofiler — Agent-first Zig profiler & debugger

## Problem

Profiling Zig code today is painful:
- `perf` and `Instruments.app` work but give assembly-level output — hard to map back to Zig source
- No built-in memory profiler — `GeneralPurposeAllocator` tracks leaks but not allocation patterns
- Segfaults in Zig give a stack trace but no context (what values, what state)
- No tool understands Zig's comptime, error unions, or optional types natively
- Profiling Zig→Python C extensions (like our faster-boto3/faster-redis) is especially hard — the call stack crosses language boundaries

## Vision

A **CLI profiler built for Zig developers** that's also **agent-friendly** (structured output, machine-parseable, composable with Claude Code / AI agents).

```
zigprofiler run ./my-program          # CPU profile + flamegraph
zigprofiler mem ./my-program          # allocation tracking
zigprofiler segfault ./my-program     # catch + analyze segfaults
zigprofiler bench ./my-program        # micro-benchmark with stats
zigprofiler diff old.profile new.profile  # regression detection
```

## Core Features

### 1. CPU Profiler (`zigprofiler run`)

- Sampling profiler using `SIGPROF` / Instruments
- **Zig-aware**: maps addresses back to Zig source lines, shows function names (not mangled)
- **Scope-aware**: groups by Zig function, shows time per scope
- **Flamegraph output**: SVG + JSON for visualization
- **Agent mode**: `--json` output for AI agents to analyze

```
zigprofiler run --json ./my-program
{
  "total_time_us": 1234567,
  "functions": [
    {"name": "resp.parse", "file": "src/resp.zig", "line": 42, "self_us": 45000, "total_us": 89000, "calls": 500000},
    {"name": "resp.findCRLF", "file": "src/resp.zig", "line": 15, "self_us": 32000, "total_us": 32000, "calls": 1500000}
  ],
  "hotspots": [
    {"file": "src/resp.zig", "line": 28, "instruction": "simd_compare", "us": 12000, "pct": 0.97}
  ]
}
```

### 2. Memory Profiler (`zigprofiler mem`)

- Wraps Zig allocators to track every allocation/free
- **Live dashboard**: shows heap size, allocation rate, largest live objects
- **Leak detection**: with source location of the leak
- **Allocation flamegraph**: where memory is allocated from
- **Peak tracking**: max heap size and what caused it

```
zigprofiler mem ./my-program
Peak heap: 4.2MB at t=1.3s
  2.1MB — resp.zig:parseArray (allocator.alloc)
  1.8MB — client.zig:readResponse (read_buf)
  0.3MB — main.zig:py_parse_resp (c_allocator)

Leaked: 0 bytes (clean)
Allocations: 1,234,567 total (345MB throughput)
  Hot: resp.zig:parseArray — 800K allocs (avg 2.6KB)
```

### 3. Segfault Analyzer (`zigprofiler segfault`)

- Catches SIGSEGV/SIGBUS and produces a rich report
- **Register dump**: with Zig variable names mapped to registers
- **Stack unwinding**: full Zig stack trace with source lines
- **Memory map**: shows what's near the faulting address
- **Root cause hints**: "null pointer dereference on optional", "slice out of bounds", "use-after-free"

```
zigprofiler segfault ./my-program
SEGFAULT at 0x0000000000000008 (null + 8)

Likely cause: null optional dereference
  → self.stream.?.write(data)
  → self.stream is null

Stack:
  client.zig:92  RedisClient.send
  client.zig:57  RedisClient.command
  main.zig:78    py_command

Registers:
  x0 = 0x0000000000000000 (null — this is `self.stream`)
  x1 = 0x000000016fdfc000 (stack — `data` slice ptr)
```

### 4. Micro-benchmark (`zigprofiler bench`)

- Built-in benchmarking with statistical rigor
- **Warmup detection**: auto-detects when JIT/cache is warm
- **Outlier removal**: trims top/bottom percentiles
- **Comparison mode**: A/B two builds side-by-side
- **Regression detection**: fails CI if perf regresses

```
zigprofiler bench --compare old_binary new_binary
                    old          new       change
parse_simple     58ns ±2%     52ns ±1%    -10.3% (p=0.001)
parse_bulk       61ns ±3%     55ns ±2%     -9.8% (p=0.002)
pack_SET        104ns ±1%    101ns ±1%     -2.9% (p=0.04)

VERDICT: 2 significant improvements, 0 regressions
```

### 5. Cross-language profiler (`zigprofiler ffi`)

- Profiles Zig code called from Python via C extension
- **Unified flamegraph**: Python frames + Zig frames in one view
- **Boundary markers**: shows where Python→Zig transition happens
- **GIL tracking**: shows when GIL is held vs released

```
zigprofiler ffi python my_script.py
  Python: my_script.py:10 — parse_resp()         2.3us
    → [C boundary: PyArg_ParseTuple]              0.1us
    → Zig: main.zig:15 — py_parse_resp()          0.05us
      → Zig: resp.zig:42 — parse()                0.03us
        → Zig: resp.zig:15 — findCRLF() [SIMD]    0.02us
    → [C boundary: PyUnicode_FromStringAndSize]    0.08us
  Python: return value                             0.01us
```

## Architecture

```
zigprofiler (CLI)
├── cmd/          — CLI commands (run, mem, segfault, bench, diff, ffi)
├── core/
│   ├── sampler.zig     — SIGPROF-based CPU sampling
│   ├── allocator.zig   — Wrapping allocator for memory tracking
│   ├── unwinder.zig    — Stack unwinder using DWARF debug info
│   ├── symbolizer.zig  — Address → Zig source line mapping
│   ├── segfault.zig    — SIGSEGV handler + analysis
│   └── stats.zig       — Statistical analysis (mean, stdev, t-test)
├── output/
│   ├── json.zig        — Structured JSON output (agent-friendly)
│   ├── flamegraph.zig  — SVG flamegraph generator
│   ├── terminal.zig    — Rich terminal output (colors, tables)
│   └── diff.zig        — Profile comparison + regression detection
├── ffi/
│   ├── python.zig      — Python frame detection
│   ├── boundary.zig    — Language boundary tracking
│   └── gil.zig         — GIL state tracking
└── build.zig
```

## Agent-First Design

Every command supports `--json` with structured, machine-parseable output. This means:

1. **Claude Code can call it**: `zigprofiler run --json ./program` → parse JSON → suggest optimizations
2. **CI integration**: `zigprofiler bench --ci --threshold 5%` → fail if regression
3. **Composable**: pipe output to other tools, feed into dashboards
4. **Deterministic**: same input → same output (for reproducible bug reports)

### Agent workflow example

```
Agent: "The user's RESP parser is slow. Let me profile it."

1. zigprofiler run --json ./faster-redis/zig-out/bin/test
   → Finds findCRLF takes 40% of time

2. zigprofiler bench --json --function findCRLF
   → 58ns per call, SIMD path only taken for buffers >16 bytes

3. Agent suggests: "Most RESP lines are <16 bytes. The SIMD path is skipped.
   Add a fast scalar path for short strings before the SIMD loop."

4. User applies fix → zigprofiler bench --compare old new
   → 58ns → 31ns, 1.87x improvement
```

## Implementation Plan

### Phase 1: Core (week 1)
- [ ] CLI skeleton with `run`, `bench`, `mem` subcommands
- [ ] Basic sampling profiler (SIGPROF on macOS/Linux)
- [ ] Zig symbolizer (parse DWARF from debug binary)
- [ ] JSON output for all commands
- [ ] `bench` with warmup detection + outlier trimming

### Phase 2: Memory + Segfault (week 2)
- [ ] Wrapping allocator that logs alloc/free with source location
- [ ] Peak heap tracking + allocation flamegraph
- [ ] SIGSEGV handler with register dump + stack trace
- [ ] Root cause hinting (null deref, OOB, use-after-free)

### Phase 3: FFI + Polish (week 3)
- [ ] Python↔Zig boundary detection in stack traces
- [ ] GIL state tracking via `_Py_IsFinalizing` / `PyGILState_Check`
- [ ] Unified flamegraph (Python + Zig frames)
- [ ] Terminal UI (live dashboard for `mem` mode)
- [ ] `diff` command for profile comparison

### Phase 4: Distribution
- [ ] Single static binary (like nanobrew — small, no deps)
- [ ] `brew install zigprofiler` / `cargo binstall zigprofiler`
- [ ] GitHub Action for CI profiling
- [ ] Claude Code skill integration

## Why Zig for a profiler?

- **No runtime overhead**: profiler itself shouldn't distort measurements
- **Direct DWARF parsing**: Zig can read ELF/Mach-O debug info natively
- **Signal handling**: Zig's `std.os` gives direct access to signal handlers
- **Cross-platform**: same code for macOS (Instruments) and Linux (perf_events)
- **Single binary**: 2MB profiler, no Python/Node/Java runtime needed
- **Dog-fooding**: profile Zig code with a Zig profiler

## Comparison with existing tools

| Tool | Language | Zig-aware | Agent-friendly | Memory | Segfault | FFI |
|---|---|---|---|---|---|---|
| `perf` | C | No | No | No | No | No |
| Instruments | ObjC | No | No | Yes | No | No |
| Valgrind | C | No | No | Yes | Yes | No |
| Tracy | C++ | No | No | Yes | No | No |
| **zigprofiler** | **Zig** | **Yes** | **Yes (JSON)** | **Yes** | **Yes** | **Yes** |

## Open Questions

- Should we use `dtrace` on macOS or implement our own sampler?
- DWARF parsing: use Zig's `std.dwarf` or write custom?
- How to handle optimized builds where debug info is stripped?
- Should `zigprofiler ffi` support other languages (Ruby, Node)?
- MCP server mode? (`zigprofiler serve --mcp` for direct Claude Code integration)
