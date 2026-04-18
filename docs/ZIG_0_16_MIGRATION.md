# Zig 0.16 Migration Direction

**From:** Zig 0.15.x  
**To:** Zig 0.16.0  
**Status:** Corrected plan for `v1.0.28`  
**Compiler checked locally:** `zig version` -> `0.16.0`

> The stdlib reading changed my mind. The TurboAPI-style pthread shims would actively hurt us.

This document replaces the earlier recommendation to port removed thread primitives with
POSIX pthread shims. After reading the local Zig 0.16 stdlib, that advice is withdrawn.
For TurboAPI-owned code, the point of the migration is to route through `std.Io`, not to
work around it.

Files checked locally while rewriting this document:

- `lib/std/Io.zig`
- `lib/std/Io/Threaded.zig`
- `lib/std/Io/net.zig`
- `lib/std/Io/RwLock.zig`
- `lib/std/crypto/25519/ed25519.zig`

---

## What Changed

The previous version of this guide got two important things wrong:

1. It treated `std.Io` as a compatibility obstacle instead of the new abstraction boundary.
2. It recommended pthread-style shims for `Mutex` and `Condition`, which would lock TurboAPI
   into the wrong API just before the runtime wants to move to evented I/O.

That would create a double migration:

- first from `std.Thread.*` to `Pthread*`
- then later from `Pthread*` to `std.Io.*` when we want `io_uring` / `Dispatch` / `Kqueue`

That is unnecessary churn. TurboAPI should do the `std.Io` migration once.

---

## Key Findings From The Local Stdlib

### 1. `std.Io` is the abstraction boundary, not the obstacle

The top of `lib/std/Io.zig` describes `std.Io` as the interface that abstracts both I/O
operations and concurrency. This is the whole design:

- `std.Io.Threaded` is the blocking, OS-threaded backend we want today
- `std.Io.Evented` resolves by platform to `Uring` on Linux, `Dispatch` on Apple platforms,
  and `Kqueue` on BSD
- `std.Io.Threaded.global_single_threaded` exists as a prebuilt singleton for cases where a
  library or debug path needs a statically initialized threaded `Io`

The important consequence is that backend selection lives behind the `Io` vtable. If TurboAPI
keeps its own code on native `std.Io` call sites, backend swaps happen at startup, not across
the whole codebase.

### 2. `std.Io.Mutex` is the path forward, not a stopgap

`lib/std/Io.zig` implements `Mutex.lock`, `lockUncancelable`, and `unlock` in terms of a CAS
fast path plus `io.futexWait*` / `io.futexWake`:

```zig
pub fn lock(m: *Mutex, io: Io) Cancelable!void {
    // CAS fast path...
    try io.futexWait(State, &m.state.raw, .contended);
}

pub fn unlock(m: *Mutex, io: Io) void {
    // ...
    io.futexWake(State, &m.state.raw, 1);
}
```

What matters is not just the implementation detail, but where the dependency lands:

- under `Threaded`, those waits route to the runtime's native blocking wait path
- on Linux, that path is futex-backed
- under `Evented`, the same call sites become scheduler-managed waits instead of "rewrite all
  locks again later"

The same logic applies to `std.Io.Condition` and `std.Io.RwLock`. Once TurboAPI adopts the
native APIs, the concurrency backend is selectable without another lock-API migration.

### 3. Native `std.Io.net` is already the server-facing API we want

The local `lib/std/Io/net.zig` exposes the real shape of the 0.16 networking layer:

- `std.Io.net.IpAddress.parse(host, port)`
- `addr.listen(io, options)`
- `server.accept(io)`
- `stream.reader(io, buf)`
- `stream.writer(io, buf)`

That means the correct migration is not "wrap raw file descriptors until the compiler stops
complaining". The correct migration is to move server code onto native `std.Io.net` and only
drop to raw socket handles for truly low-level operations such as `setsockopt`.

### 4. Compat is still useful, but only for mechanical rewrites

There is still room for a small compatibility layer. It just needs to be used in the right
places:

- good: `cwd` file-system helpers that inject `runtime.io`
- good: timestamp helpers based on `clock_gettime`
- good: a narrow `threadSleep` helper for isolated legacy sites that do not already accept `io`
- bad: `PthreadMutex`, `PthreadCondition`, or a fake `std.net` facade in core runtime code

Compat should reduce migration noise, not hide the new runtime model.

---

## Corrected Project Policy

### Use native `std.Io` directly for runtime-owned subsystems

This includes:

- networking
- mutexes
- conditions
- rwlocks
- randomness and crypto call sites that now take `std.Io`
- any code that is part of the long-lived server runtime

### Use thin shims only where the adoption cost is purely mechanical

This includes:

- `std.fs.cwd()` replacements that can become one-line wrappers around `std.Io.Dir.cwd()`
- `milliTimestamp` / `nanoTimestamp`
- a narrow `threadSleep(ns)` helper for the few sites that genuinely want blocking sleep and do
  not already have `io` in scope

### Do not introduce a pthread compatibility layer into TurboAPI core code

That would:

- make the eventual evented-runtime migration harder
- split the codebase across two concurrency abstractions
- force another call-site rewrite later

---

## Revised Runtime Shape

### `zig/src/runtime.zig`

One module should own the chosen `Io` implementation:

```zig
const std = @import("std");

pub var threaded: std.Io.Threaded = undefined;
pub var io: std.Io = undefined;

pub fn init(gpa: std.mem.Allocator) void {
    threaded = std.Io.Threaded.init(gpa, .{});
    io = threaded.io();
}

pub fn deinit() void {
    threaded.deinit();
}
```

Each entry-point `main()` should call `runtime.init(gpa)` once and `defer runtime.deinit()`.
From there on, runtime-owned code should take or import `runtime.io`.

### `zig/src/compat.zig`

Use a small shim module for repetitive rewrites, not for backend selection:

```zig
const std = @import("std");
const runtime = @import("runtime.zig");

pub const fs = struct {
    pub fn cwdDeleteTree(path: []const u8) !void {
        return std.Io.Dir.cwd().deleteTree(runtime.io, path);
    }

    pub fn cwdCreateDirPath(path: []const u8) !void {
        return std.Io.Dir.cwd().createDirPath(runtime.io, path);
    }

    pub fn cwdOpenDir(path: []const u8, options: std.Io.Dir.OpenOptions) !std.Io.Dir {
        return std.Io.Dir.cwd().openDir(runtime.io, path, options);
    }
};
```

Time helpers remain fine here as well:

```zig
pub fn milliTimestamp() i64 { /* clock_gettime */ }
pub fn nanoTimestamp() i128 { /* clock_gettime */ }
pub fn threadSleep(ns: u64) void { /* nanosleep */ }
```

The key rule is that compat forwards into `std.Io`. It does not replace it.

---

## Thread Primitives: Native Adoption, No Shims

The correct replacements are:

- `std.Thread.Mutex` -> `std.Io.Mutex`
- `std.Thread.Condition` -> `std.Io.Condition`
- `std.Thread.RwLock` -> `std.Io.RwLock`

Field shape:

```zig
mu: std.Io.Mutex = .init,
cond: std.Io.Condition = .init,
rw: std.Io.RwLock = .init,
```

Call-site shape:

```zig
self.mu.lockUncancelable(runtime.io);
defer self.mu.unlock(runtime.io);

self.cond.waitUncancelable(runtime.io, &self.mu);

self.rw.lockSharedUncancelable(runtime.io);
defer self.rw.unlockShared(runtime.io);
```

This is slightly more explicit because an `Io` parameter is now visible at the call site.
That is a feature, not noise. It keeps the runtime choice alive.

---

## Networking: Native `std.Io.net` Adoption

The server-side migration should target the real 0.16 API:

```zig
const ip = try std.Io.net.IpAddress.parse(host, port);
var server = try ip.listen(runtime.io, .{ .reuse_address = true });

while (true) {
    const stream = try server.accept(runtime.io);
    // hand off stream
}
```

And for I/O:

```zig
var read_buf: [4096]u8 = undefined;
var write_buf: [4096]u8 = undefined;

var reader = stream.reader(runtime.io, &read_buf);
var writer = stream.writer(runtime.io, &write_buf);
```

Use `stream.socket.handle` only when the code truly needs the raw descriptor, such as:

- socket options
- integration with a low-level dependency that still takes a raw fd

Defaulting to raw C `read`/`write` wrappers in TurboAPI-owned code would be another way of
fighting the new API instead of adopting it.

---

## Still-Valid Mechanical Fixes

The previous doc was wrong about thread primitives, but several other 0.16 changes remain valid:

- `build.zig`: many `Compile.*` helpers moved to `root_module.*`
- `std.io.fixedBufferStream` -> `std.fmt.bufPrint`
- `*std.io.Writer` -> `*std.Io.Writer`
- `std.time.timestamp/milliTimestamp/nanoTimestamp` -> `clock_gettime` helpers
- `std.debug.lockStderrWriter` -> `std.debug.lockStderr(&buf)`
- `std.crypto.random.bytes(buf)` -> `runtime.io.random(buf)`
- `Ed25519.KeyPair.generate()` -> `Ed25519.KeyPair.generate(runtime.io)`
- empty `ArrayListUnmanaged` initializers now need explicit fields
- local variables may not shadow module-level `extern fn` declarations

Those are still worth fixing mechanically. They just do not justify introducing the wrong
concurrency abstraction.

---

## Order Of Operations

1. Add `runtime.zig` and `compat.zig`.
2. Update each entry point to initialize and deinitialize the shared `Io`.
3. Do the purely mechanical rewrites first:
   - `build.zig`
   - `fixedBufferStream`
   - timestamp helpers
   - stderr locking
   - random / crypto call sites
   - `ArrayListUnmanaged`
4. Replace `std.Thread.Mutex`, `Condition`, and `RwLock` with native `std.Io` primitives.
5. Rewrite networking to `std.Io.net` and prefer `reader` / `writer` over raw fd wrappers.
6. Keep compat helpers narrow and delete any temptation to add pthread shims.
7. Run `zig build` until clean.
8. Run `zig build test`.
9. Only then treat evented I/O as a backend-selection task, not another API migration.

---

## Payoff

If TurboAPI routes its runtime, locks, and networking through `runtime.io`, the later move to an
evented backend becomes dramatically simpler. The win is not just "builds on 0.16". The win is
that the codebase stops baking in the threaded-only assumptions that the stdlib is explicitly
trying to abstract away.

That is the actual path to the `io_uring` / `Dispatch` / `Kqueue` upside in Zig 0.16:

- choose `std.Io.Threaded` today
- keep call sites on native `std.Io`
- swap the backend later without rewriting every mutex and socket call again
