---
name: turbo-build
description: Build the TurboAPI Zig native backend. Use when the turbonet extension needs to be recompiled, after changing Zig source files, or when seeing "Native core not available".
disable-model-invocation: true
argument-hint: [--release]
---

# Build TurboAPI Zig Backend

## Steps

1. **Build turbonet**:

```bash
uv run --python 3.14t python zig/build_turbonet.py --install $ARGUMENTS
```

2. **Verify the build**:

```bash
uv run --python 3.14t python -c "from turboapi import turbonet; print(turbonet.hello())"
```

## Dependencies (auto-fetched via build.zig.zon)

- **dhi** (justrach/dhi) — Zig-native JSON validation
- **pg.zig** (justrach/pg.zig) — Zig-native Postgres client with SIMD + pgvector

## Common issues

- **"Native core not available"**: Rebuild with the command above
- **dhi hash mismatch**: `cd zig && zig fetch --save "https://github.com/justrach/dhi/archive/refs/heads/main.tar.gz"`
- **pg.zig hash mismatch**: `cd zig && zig fetch --save "git+https://github.com/justrach/pg.zig#master"`
- **Missing Python 3.14t**: `uv python install 3.14t`
- **Missing Zig 0.15+**: `brew install zig` or download from ziglang.org

## Build modes

- `--install`: Copy .so into `python/turboapi/` (required for dev)
- `--release`: ReleaseFast optimizations (for benchmarks/production)
- No flags: Compile check only

## What gets built

Output: `python/turboapi/turbonet.{suffix}.so` containing:
- HTTP server (server.zig) — 24-thread pool, keep-alive, CORS
- Router (router.zig) — radix trie with path params + wildcards
- dhi validator (dhi_validator.zig) — pre-GIL JSON validation
- DB layer (db.zig) — pg.zig pool, cache, prepared statements
- pg.zig fork — SIMD JSON escaping, pgvector, writeJsonRow
