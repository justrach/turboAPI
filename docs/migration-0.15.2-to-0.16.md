# Zig 0.15.2 -> 0.16 Migration Reference

This is the compact reference version of the project migration plan.

The important correction from earlier drafts is simple:

> For TurboAPI-owned code, do not solve Zig 0.16 by introducing pthread shims.
> Move runtime code onto native `std.Io` once, then keep the backend swappable.

The local Zig 0.16 stdlib already gives us the abstraction we want:

- `std.Io.Threaded` for the blocking runtime we want today
- `std.Io.Evented` for later `Uring` / `Dispatch` / `Kqueue` backends
- `std.Io.Mutex`, `Condition`, and `RwLock` that already follow the chosen `Io`
- `std.Io.net` server and stream types that are already the new networking surface

---

## Rule Of Thumb

### Use native `std.Io` directly when the code is part of the server runtime

That includes:

- sockets and accept loops
- lock types
- condition variables
- rwlocks
- randomness
- crypto call sites that now require `std.Io`

### Use compat helpers only for narrow, mechanical rewrites

That includes:

- `cwd` filesystem helpers
- timestamp helpers
- an isolated blocking sleep helper for legacy code that does not already accept `io`

### Do not add a pthread compatibility layer to TurboAPI core code

That would preserve the wrong abstraction and force another migration later.

---

## Build System

Many `Build.Step.Compile` helpers moved to `root_module`:

```zig
// 0.15
lib.addIncludePath(.{ .cwd_relative = path });
lib.linkSystemLibrary("foo");
lib.addCSourceFile(.{ .file = b.path("shim.c"), .flags = &.{} });

// 0.16
lib.root_module.addIncludePath(.{ .cwd_relative = path });
lib.root_module.linkSystemLibrary("foo", .{});
lib.root_module.addCSourceFile(.{ .file = b.path("shim.c"), .flags = &.{} });
```

If the compiler mentions `Build.Step.Compile` and `addIncludePath`, move the call to
`root_module` rather than trying to outsmart the pointer-deref note.

---

## Runtime Bootstrap

Pick one application `Io` at startup and keep it in a runtime module:

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

`std.Io.Threaded.global_single_threaded` exists, but it is not the right default for a long-lived
server runtime. Own the `Io` explicitly.

---

## Networking

### `std.net` -> `std.Io.net`

```zig
// 0.15
const addr = try std.net.Address.parseIp4(host, port);
var server = try addr.listen(.{ .reuse_address = true });
const conn = try server.accept();
defer conn.stream.close();

// 0.16
const addr = try std.Io.net.IpAddress.parse(host, port);
var server = try addr.listen(runtime.io, .{ .reuse_address = true });
const stream = try server.accept(runtime.io);
defer stream.close(runtime.io);
```

### Raw handle field changed

```zig
// 0.15
stream.handle

// 0.16
stream.socket.handle
```

### Prefer native stream readers and writers

```zig
var read_buf: [4096]u8 = undefined;
var write_buf: [4096]u8 = undefined;

var reader = stream.reader(runtime.io, &read_buf);
var writer = stream.writer(runtime.io, &write_buf);
```

Use raw fd operations only when the code genuinely needs them, such as `setsockopt` or a
dependency boundary that still speaks raw sockets.

### Other network renames

```zig
std.net.has_unix_sockets
// becomes
std.Io.net.has_unix_sockets
```

`std.posix.close` is gone. Use `std.c.close(fd)`. `std.posix.read` still exists.

---

## Threading

### Replace `std.Thread.*` primitives with native `std.Io.*`

```zig
// 0.15
mu: std.Thread.Mutex = .{},
cond: std.Thread.Condition = .{},

// 0.16
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

If a lock site belongs to TurboAPI's runtime, pass `runtime.io` and move on. Do not paper over
this with `PthreadMutex` unless the code is truly outside the runtime boundary and cannot be
changed without disproportionate churn.

### Sleep

If the code already has access to `io`, prefer staying on `std.Io`.

If the code is an isolated legacy blocking path, a tiny compat helper is acceptable:

```zig
fn threadSleep(ns: u64) void {
    const ts = std.c.timespec{
        .sec = @intCast(ns / std.time.ns_per_s),
        .nsec = @intCast(ns % std.time.ns_per_s),
    };
    _ = std.c.nanosleep(&ts, null);
}
```

---

## Filesystem Compat

`std.fs.cwd()` call sites can usually become thin wrappers around `std.Io.Dir.cwd()`:

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

    pub fn cwdOpenFile(path: []const u8, options: std.Io.Dir.OpenFileOptions) !std.Io.File {
        return std.Io.Dir.cwd().openFile(runtime.io, path, options);
    }
};
```

This is a good compat layer because it forwards into `std.Io` instead of hiding it.

---

## Time, Random, And Crypto

### Timestamps

`std.time.timestamp()`, `milliTimestamp()`, and `nanoTimestamp()` are removed.

```zig
fn milliTimestamp() i64 {
    var ts: std.c.timespec = undefined;
    _ = std.c.clock_gettime(.REALTIME, &ts);
    return @as(i64, ts.sec) * 1000 + @divTrunc(@as(i64, ts.nsec), 1_000_000);
}
```

`ts.nsec` is signed. Use `@divTrunc`, not `/`.

### Random bytes

```zig
// 0.15
std.crypto.random.bytes(&buf);

// 0.16
runtime.io.random(&buf);
```

### Ed25519

```zig
// 0.15-style assumption
const kp = std.crypto.sign.Ed25519.KeyPair.generate();

// 0.16
const kp = std.crypto.sign.Ed25519.KeyPair.generate(runtime.io);
```

---

## Other 0.16 Mechanical Fixes

### `std.io.fixedBufferStream` -> `std.fmt.bufPrint`

```zig
// 0.15
var buf: [512]u8 = undefined;
var stream = std.io.fixedBufferStream(&buf);
try std.fmt.format(stream.writer(), "{d}", .{value});
const slice = stream.getWritten();

// 0.16
var buf: [512]u8 = undefined;
const slice = try std.fmt.bufPrint(&buf, "{d}", .{value});
```

### `*std.io.Writer` -> `*std.Io.Writer`

```zig
fn drain(w: *std.Io.Writer, data: []const u8) error{WriteFailed}!usize { ... }
```

### `std.debug.lockStderrWriter` -> `std.debug.lockStderr(&buf)`

```zig
var buf: [4096]u8 = undefined;
const held = std.debug.lockStderr(&buf);
defer std.debug.unlockStderr();
try held.file_writer.print("msg: {s}\n", .{text});
```

### Empty `ArrayListUnmanaged` initializer

```zig
var list: std.ArrayListUnmanaged(u8) = .{ .items = &.{}, .capacity = 0 };
```

### Local variables cannot shadow module-level `extern fn`

If you define `extern "c" fn socket(...)`, you can no longer declare `const socket = ...`
inside a local function. Rename the local.

---

## Anti-Patterns To Avoid

- Do not create `PthreadMutex` / `PthreadCondition` as the new house style.
- Do not keep a fake `std.net` facade just to avoid threading `io`.
- Do not default to raw `read` / `write` wrappers in code that can use native `std.Io.net`.
- Do not hide the application runtime behind multiple singleton `Io` instances.

---

## Recommended Migration Order

1. Add `runtime.zig`.
2. Add narrow compat helpers for filesystem and timestamps.
3. Fix build-system API moves.
4. Fix `std.io` removals and stderr changes.
5. Fix timestamps, random, and crypto.
6. Replace thread primitives with `std.Io.Mutex`, `Condition`, and `RwLock`.
7. Move networking to `std.Io.net`.
8. Run `zig build` until clean.
9. Run `zig build test`.

If that order is respected, the codebase ends the migration on the abstraction Zig 0.16 is
actually designed around.
