# Zig 0.16 Migration Guide

**From:** Zig 0.15.x  
**To:** Zig 0.16.0  
**Status:** 0.16.0 milestone complete (333/333 issues resolved); stable release imminent as of April 2026.

---

## Summary

The biggest change in 0.16 is the **networking API**. `std.net` is removed and replaced by
`std.Io.net`, which pairs with a new `std.Io` runtime abstraction. For TurboAPI this means:

- Every `std.net.Stream` type annotation → `std.Io.net.Stream`
- The listen/accept loop in `server_run` needs an `std.Io` instance
- `stream.close()` → `stream.deinit()`
- The custom `ConnectionPool` **stays as-is** — `std.Thread.spawn` is not removed, and the
  Python GIL integration (per-worker `PyThreadState`) requires manual thread lifecycle control
  that `std.Io.Threaded`'s automatic pool doesn't expose

Everything else — JSON parsing, request parsing, the radix router, dhi validation, `std.posix.*`,
`std.Thread.Mutex/Condition`, `std.mem.*`, `std.fmt.*`, `std.ArrayListUnmanaged` — is unaffected.

---

## Breaking Changes at a Glance

| Old (0.15) | New (0.16) | Where it hits |
|---|---|---|
| `std.net.Address.parseIp4(host, port)` | `std.Io.net.IpAddress.parse(host, port)` | `server.zig:802` |
| `addr.listen(.{})` | `ip_addr.listen(io, .{})` | `server.zig:807` |
| `tcp_server.accept()` → `Connection` | `tcp_server.accept()` → `Stream` directly | `server.zig:834` |
| `conn.stream` | `conn` (stream is the accepted value) | `server.zig:835` |
| `std.net.Stream` | `std.Io.net.Stream` | `server.zig` — dozens of annotations |
| `stream.close()` | `stream.deinit()` | `server.zig:867` and every `handleConnection` |
| `stream.handle` (raw fd) | `stream.handle` (likely unchanged, verify) | `server.zig:872` |
| `std.heap.GeneralPurposeAllocator` | `std.heap.DebugAllocator` | not used in this repo currently |
| `build.zig.zon` version `"0.15.2"` | `"0.16.0"` | `zig/build.zig.zon:3` |

---

## File-by-File Changes

### `zig/build.zig.zon`

**Line 3** — bump version:

```zig
// Before
.version = "0.15.2",

// After
.version = "0.16.0",
```

Dependency URLs and hashes (`dhi`, `pg.zig`, `turboapi_core`) will need re-verification once
those libraries publish 0.16-compatible releases. Run `zig build` and update the `.hash` values
if the fetch fails.

> **Note:** `.name = .zig` (identifier syntax, not a quoted string) is already correct for
> 0.14+ style and stays unchanged.

---

### `zig/build.zig`

The `build.zig` already uses the 0.14+ API (`b.addLibrary`, `b.createModule`,
`.root_module` pattern). No changes required for the build itself.

If any dependency's own `build.zig` is written for 0.15 you'll see compile errors fetching it —
fix by pinning to a 0.16-compatible tag of that dependency.

---

### `zig/src/server.zig`

This is the file with the most changes. All are mechanical type renames except the
`server_run` function which needs a new `std.Io` instance.

#### 1. Add `std.Io` instance to `server_run` (lines 801–840)

The whole listen/accept loop needs an `io` handle:

```zig
// Before (0.15)
pub fn server_run(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    const addr = std.net.Address.parseIp4(server_host, server_port) catch {
        py.setError("Invalid address: {s}:{d}", .{ server_host, server_port });
        return null;
    };

    var tcp_server = addr.listen(.{ .reuse_address = true }) catch {
        py.setError("Failed to bind to {s}:{d}", .{ server_host, server_port });
        return null;
    };
    defer tcp_server.deinit();

    // ...

    while (true) {
        const conn = tcp_server.accept() catch continue;
        pool.queue.push(conn.stream);         // <── conn.stream unpacking
    }
}
```

```zig
// After (0.16)
pub fn server_run(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    // One Io instance for the accept loop only. Worker threads use raw
    // PyThreadState / std.Thread — std.Io.Threaded's pool cannot hook into
    // the per-worker PyThreadState lifecycle, so the ConnectionPool stays.
    var threaded_io = std.Io.Threaded.create(.{ .thread_count = 1 }) catch {
        py.setError("Failed to create Io runtime", .{});
        return null;
    };
    defer threaded_io.deinit();
    const io = threaded_io.io();

    const ip_addr = std.Io.net.IpAddress.parse(server_host, server_port) catch {
        py.setError("Invalid address: {s}:{d}", .{ server_host, server_port });
        return null;
    };

    var tcp_server = ip_addr.listen(io, .{ .reuse_address = true }) catch {
        py.setError("Failed to bind to {s}:{d}", .{ server_host, server_port });
        return null;
    };
    defer tcp_server.deinit();

    // ...

    while (true) {
        const stream = tcp_server.accept() catch continue;  // stream directly, no .stream field
        pool.queue.push(stream);
    }
}
```

#### 2. `ConnectionPool.Queue` item type (lines 739–770)

```zig
// Before
items: [4096]std.net.Stream = undefined,

fn push(self: *Queue, stream: std.net.Stream) void { ... }
fn pop(self: *Queue) std.net.Stream { ... }

// After
items: [4096]std.Io.net.Stream = undefined,

fn push(self: *Queue, stream: std.Io.net.Stream) void { ... }
fn pop(self: *Queue) std.Io.net.Stream { ... }
```

#### 3. `stream.close()` → `stream.deinit()` (lines 867, 751)

`std.Io.net.Stream` uses `deinit()` as the RAII destructor:

```zig
// Before
fn handleConnection(stream: std.net.Stream, tstate: ?*anyopaque) void {
    defer stream.close();
    // ...
}

// Also in Queue.push when the queue is full (line 751):
stream.close();

// After
fn handleConnection(stream: std.Io.net.Stream, tstate: ?*anyopaque) void {
    defer stream.deinit();
    // ...
}

stream.deinit();  // reject when queue full
```

#### 4. All function signatures taking `std.net.Stream`

Mechanical rename throughout the file:

| Function | Line | Change |
|---|---|---|
| `handleConnection` | 866 | `std.net.Stream` → `std.Io.net.Stream` |
| `handleOneRequest` | 879 | `std.net.Stream` → `std.Io.net.Stream` |
| `sendResponse` | 2058 | `std.net.Stream` → `std.Io.net.Stream` |
| `sendTupleResponse` | 1255 | `std.net.Stream` → `std.Io.net.Stream` |
| `callPythonNoArgs` | 1291 | `std.net.Stream` → `std.Io.net.Stream` |
| `callPythonNoArgsCaching` | 1305 | `std.net.Stream` → `std.Io.net.Stream` |
| `callPythonHandlerDirect` | 1530 | `std.net.Stream` → `std.Io.net.Stream` |
| `callPythonModelHandlerDirect` | 1641 | `std.net.Stream` → `std.Io.net.Stream` |
| `callPythonModelHandlerParsed` | 1702 | `std.net.Stream` → `std.Io.net.Stream` |
| Anonymous params at lines ~1362, ~1442 | various | rename |

#### 5. Raw socket access for `setsockopt` (line 872)

The Slowloris timeout sets `SO_RCVTIMEO` via raw fd:

```zig
// Current (unchanged for now — verify it still compiles)
const timeout = std.posix.timeval{ .sec = 30, .usec = 0 };
std.posix.setsockopt(stream.handle, std.posix.SOL.SOCKET, std.posix.SO.RCVTIMEO,
    std.mem.asBytes(&timeout)) catch {};
```

`std.Io.net.Stream` still exposes `.handle` in 0.16. **Verify this after renaming** — if
the compiler rejects it, check whether the field is now `.socket`, `.fd`, or accessed via
a method. The `std.posix.*` constants themselves (`SOL.SOCKET`, `SO.RCVTIMEO`, `timeval`)
are unchanged.

#### 6. `stream.read` and `stream.writeAll` — no changes needed

`std.Io.net.Stream.read` and `writeAll` keep the same blocking signature in the `Threaded`
backend. The calls in `handleOneRequest` (reads into `header_buf`) and in `sendResponse`
(the `writeAll(resp_buf[0..pos])` single-copy fast path) compile unchanged.

---

### `zig/src/db.zig`

No `std.net` usage. No changes required.

`std.posix.getenv` (lines 69, 81) and `std.Thread.Mutex` (line 56) both remain in 0.16.

---

### `zig/src/dhi_validator.zig`, `multipart.zig`, `telemetry.zig`, `logger.zig`, `py.zig`, `response.zig`

No `std.net` usage in any of these files. No changes required.

---

### `CLAUDE.md`

Update the requirements section:

```diff
-**Zig 0.15+** (for building the native backend)
+**Zig 0.16+** (for building the native backend)
```

---

## What Stays the Same

- `std.Thread.spawn`, `std.Thread.Mutex`, `std.Thread.Condition` — all unchanged
- `std.posix.getenv`, `std.posix.setsockopt`, `std.posix.timeval` — POSIX module unchanged
- `std.mem.*`, `std.fmt.*`, `std.json.*`, `std.time.*` — unchanged
- `std.ArrayListUnmanaged` with `.empty` initializer — already the correct 0.14+ style
- `std.heap.c_allocator` — unchanged (the rename only affects `GeneralPurposeAllocator`)
- `callconv(.c)` FFI exports to Python — unchanged
- Build system: `b.addLibrary`, `b.createModule`, `b.dependency`, `b.installArtifact` — unchanged
- Fuzz test setup (`zig build test --fuzz`) — unchanged

---

## New Capabilities Worth Considering Post-Migration

### `std.Io.Evented` — io_uring on Linux, GCD on macOS

Once 0.16 is working, the accept loop can optionally move to the event-driven backend:

```zig
// Linux (io_uring) or macOS (GCD) — same source code, different backend
var evented_io = try std.Io.Evented.create(.{});
const io = evented_io.io();
```

This eliminates `epoll`/`kqueue` overhead in the accept loop. With io_uring the kernel
batches accept calls, reducing syscalls per connection. Could push ~140k req/s toward
~200k+ on Linux hardware. **Benchmark before enabling** — the `Threaded` backend is simpler
and already fast.

### Replacing `ConnectionPool` with `std.Io.Group` — future option

If Python's free-threaded mode (3.14t) eventually allows sub-interpreter isolation per
connection, the manual pool could be replaced:

```zig
var group = try io.group.create(allocator);
try group.async(io, handleClient, .{ stream, sub_interp });
try group.wait();
```

**Not yet feasible** because `std.Io.Group` doesn't expose thread lifecycle hooks needed
for `PyThreadState_New` and `PyThreadState_DeleteCurrent`. Keep the manual pool.

### Faster incremental builds

0.16 ships incremental compilation by default (Zig compiler self-build: 75s → 20s).
`python zig/build_turbonet.py --install` on a second run will be measurably faster.

---

## Migration Checklist

- [ ] Install Zig 0.16: `brew upgrade zig` or download from ziglang.org/download
- [ ] Bump `zig/build.zig.zon` version to `"0.16.0"`
- [ ] Run `zig build` — note all compile errors (most will be `std.net.*` type mismatches)
- [ ] In `server.zig`: rename all `std.net.Stream` → `std.Io.net.Stream`
- [ ] In `server.zig:server_run`: add `std.Io.Threaded.create` + pass `io` to `ip_addr.listen`
- [ ] In `server.zig:server_run`: `parseIp4(host, port)` → `IpAddress.parse(host, port)`
- [ ] In `server.zig:server_run`: `conn.stream` → `conn` (accept returns stream directly)
- [ ] In `server.zig`: `stream.close()` → `stream.deinit()` everywhere
- [ ] Verify `stream.handle` still compiles for the `setsockopt` call (line 872)
- [ ] Update dependency hashes in `build.zig.zon` if dhi/pg.zig need 0.16 bumps
- [ ] Run `zig build test` — all unit tests and fuzz seed corpus should pass
- [ ] Run `uv run --python 3.14t python -m pytest tests/ -p no:anchorpy --deselect tests/test_fastapi_parity.py::TestWebSocket`
- [ ] Benchmark: `uv run --python 3.14t python benchmarks/run_benchmarks.py`
  — ~140k req/s baseline should hold; any regression means the Io integration needs tuning
- [ ] Update `CLAUDE.md`: `Zig 0.15+` → `Zig 0.16+`

---

## Dependency Compatibility

| Dependency | Current pin | Action |
|---|---|---|
| `dhi` (JSON validator) | `justrach/dhi` main | Check for a `zig-0.16` branch/tag; update hash if it fails to fetch |
| `pg.zig` (Postgres) | specific commit hash | Re-verify; pg.zig uses `std.net` internally — may need its own migration |
| `turboapi-core` (local) | `../turboapi-core` path | Also Zig source; apply the same `std.net` renames if it uses networking |

The local `turboapi-core` dependency is the most likely to need parallel work since it
contains the radix router, which may or may not use `std.net` depending on how it's structured.
