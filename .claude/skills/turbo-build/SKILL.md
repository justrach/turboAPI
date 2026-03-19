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

## Common issues

- **"Native core not available"**: The turbonet `.so` isn't built or is built for a different Python version. Rebuild with the command above.
- **dhi hash mismatch**: Run `cd zig && zig fetch --save "https://github.com/justrach/dhi/archive/refs/heads/main.tar.gz"` to update the hash.
- **Missing Python headers**: Ensure Python 3.14t is installed: `uv python install 3.14t`
- **Missing Zig**: Install Zig 0.15+: `brew install zig` or download from ziglang.org

## Build modes

- `--install`: Copy the built `.so` into `python/turboapi/` (required for dev)
- `--release`: Build with ReleaseFast optimizations (for benchmarks/production)
- No flags: Build only, don't install (for compile checking)

## What gets built

`zig/build_turbonet.py` auto-detects:
- Python version and include path
- Free-threaded status (3.14t vs 3.14)
- dhi dependency (fetched via `build.zig.zon`)
- pg.zig dependency (fetched via `build.zig.zon`)

Output: `python/turboapi/turbonet.{suffix}.so`
