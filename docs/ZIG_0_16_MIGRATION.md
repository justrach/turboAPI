# Zig 0.16 Migration Guide

**From:** Zig 0.15.x  
**To:** Zig 0.16.0  
**Status:** Complete — build clean, 341 tests passing as of 2026-04-15.

This guide documents every breaking change encountered migrating TurboAPI (a Python/Zig hybrid
HTTP framework) from 0.15.x to 0.16.0, with the verified fixes that produced a clean build.
Intended as a reference for future agents or developers working in this codebase.

---

## Summary of Breaking Changes

0.16 has three major categories of breakage, each wider than the 0.15 changelog implies:

1. **`std.net` completely removed** — replaced by `std.Io.net`, which needs an `Io` instance.
   `Io.net.Stream` has a different API: different close signature, no `.read()`/`.writeAll()`.
2. **`std.io` (lowercase) completely removed** — `std.Io` (capital) is the new async IO module
   but has totally different semantics. `std.fmt.bufPrint` replaces `fixedBufferStream`.
3. **Time, threading, and POSIX API pruning** — `std.time.timestamp/milliTimestamp/nanoTimestamp`,
   `std.Thread.Mutex/Condition/sleep`, `std.debug.lockStderrWriter`, `std.posix.write/connect/socket`,
   and `std.crypto.random` all removed.

---

## 1. Networking: `std.net` → `std.Io.net`

### 1a. Type rename: `std.net.Stream` → `std.Io.net.Stream`

Pure rename everywhere a stream type is annotated:

```zig
// Before
fn sendResponse(stream: std.net.Stream, ...) void { ... }
stream: std.net.Stream,          // struct field

// After
fn sendResponse(stream: std.Io.net.Stream, ...) void { ... }
stream: std.Io.net.Stream,       // struct field
```

### 1b. Accept loop: `std.net.Address` → `std.Io.net.IpAddress` + `io` argument

The listen/accept loop must have an `Io` instance. Create a `std.Io.Threaded` runtime
and store it in a module-global `runtime.zig` so worker threads can also access `io`.

```zig
// Before (0.15)
const addr = std.net.Address.parseIp4(host, port) catch { ... };
var tcp_server = addr.listen(.{ .reuse_address = true }) catch { ... };
while (true) {
    const conn = tcp_server.accept() catch continue;
    pool.queue.push(conn.stream);   // had .stream field
}

// After (0.16)
const ip_addr = std.Io.net.IpAddress.parse(host, port) catch { ... };
var tcp_server = ip_addr.listen(io, .{ .reuse_address = true }) catch { ... };
while (true) {
    const stream = tcp_server.accept() catch continue;  // returns Stream directly, no .stream
    pool.queue.push(stream);
}
```

New shared `runtime.zig`:

```zig
// zig/src/runtime.zig (new file)
const std = @import("std");
pub var threaded: std.Io.Threaded = undefined;
pub var io: std.Io = undefined;
```

### 1c. `stream.close()` → `stream.close(io)` — takes Io argument

```zig
// Before
stream.close();

// After
stream.close(runtime.io);   // must pass the Io instance
```

### 1d. Raw fd: `stream.handle` → `stream.socket.handle`

```zig
// Before
std.posix.setsockopt(stream.handle, ...);

// After
std.posix.setsockopt(stream.socket.handle, ...);
```

### 1e. `Io.net.Stream` has NO `.read()` or `.writeAll()` methods

Use raw C wrappers for blocking I/O in worker threads:

```zig
extern "c" fn write(fd: c_int, buf: [*]const u8, nbytes: usize) isize;

fn streamWriteAll(stream: std.Io.net.Stream, data: []const u8) !void {
    var remaining = data;
    while (remaining.len > 0) {
        const n = write(stream.socket.handle, remaining.ptr, remaining.len);
        if (n <= 0) return error.BrokenPipe;
        remaining = remaining[@intCast(n)..];
    }
}

// std.posix.read() still works (posix.read was NOT removed):
const posix = std.posix;
const n = posix.read(stream.socket.handle, buf) catch return error.ReadError;
```

### 1f. `std.net.has_unix_sockets` → `std.Io.net.has_unix_sockets`

```zig
if (comptime std.Io.net.has_unix_sockets == false ...) { ... }
```

### 1g. `std.net.connectUnixSocket/tcpConnectToHost` removed — use raw C externs

```zig
extern "c" fn socket(domain: c_int, socket_type: c_int, protocol: c_int) c_int;
extern "c" fn connect(sockfd: c_int, addr: *const anyopaque, addrlen: u32) c_int;

// WARNING: if you name a local const socket or connect, the compiler errors:
// "local constant shadows declaration of socket"
// Use a different name (e.g. sock_fd) for local variables.

fn connectUnixSocket(path: []const u8) !std.posix.socket_t {
    const fd = socket(std.c.AF.UNIX, std.c.SOCK.STREAM, 0);
    if (fd < 0) return error.SystemResources;
    errdefer _ = std.c.close(fd);
    // ... build SockaddrUn, call connect() ...
    return fd;
}

fn tcpConnectToHost(host: []const u8, port: u16) !std.posix.socket_t {
    // use std.c.getaddrinfo / freeaddrinfo
    // iterate results, call socket() + connect()
    return fd;
}
```

`posix.close(fd)` → `_ = std.c.close(fd)` (`std.posix.close` was removed):

```zig
// Before
posix.close(self.socket);

// After
_ = std.c.close(self.socket);
```

---

## 2. `std.io` (lowercase) completely removed

### 2a. `std.io.fixedBufferStream` → `std.fmt.bufPrint`

```zig
// Before (0.15)
var str_buf: [512]u8 = undefined;
var stream = std.io.fixedBufferStream(&str_buf);
try std.fmt.format(stream.writer(), "{d}", .{value});
return useSlice(stream.getWritten(), buf);

// After (0.16)
var str_buf: [512]u8 = undefined;
const slice = try std.fmt.bufPrint(&str_buf, "{d}", .{value});
return useSlice(slice, buf);
```

### 2b. `*std.io.Writer` vtable parameter → `*std.Io.Writer`

```zig
// Before
pub fn drain(io_w: *std.io.Writer, ...) error{WriteFailed}!usize { ... }

// After
pub fn drain(io_w: *std.Io.Writer, ...) error{WriteFailed}!usize { ... }
```

---

## 3. Time APIs removed: use `clock_gettime`

`std.time.timestamp()`, `milliTimestamp()`, and `nanoTimestamp()` are all removed.

```zig
fn timestampSeconds() i64 {
    var ts: std.c.timespec = undefined;
    _ = std.c.clock_gettime(.REALTIME, &ts);
    return ts.sec;
}

fn milliTimestamp() i64 {
    var ts: std.c.timespec = undefined;
    _ = std.c.clock_gettime(.REALTIME, &ts);
    return @as(i64, ts.sec) * 1000 + @divTrunc(@as(i64, ts.nsec), 1_000_000);
}

fn nanoTimestamp() i128 {
    var ts: std.c.timespec = undefined;
    _ = std.c.clock_gettime(.REALTIME, &ts);
    return @as(i128, ts.sec) * 1_000_000_000 + @as(i128, ts.nsec);
}
```

`ts.nsec` is signed — use `@divTrunc` not `/` for division (0.16 enforces this):

```zig
// WRONG — compile error: "signed integer division"
@as(i64, ts.nsec) / 1_000_000

// RIGHT
@divTrunc(@as(i64, ts.nsec), 1_000_000)
```

---

## 4. Thread primitives removed: use POSIX pthreads

`std.Thread.Mutex`, `std.Thread.Condition`, and `std.Thread.sleep` are removed.
The replacement (`std.Io.Mutex/Condition`) requires an `Io` instance — unavailable in
vendored dependencies. Use POSIX pthread shims:

```zig
const PthreadMutex = struct {
    inner: std.c.pthread_mutex_t = std.c.PTHREAD_MUTEX_INITIALIZER,
    pub fn lock(m: *PthreadMutex) void { _ = std.c.pthread_mutex_lock(&m.inner); }
    pub fn unlock(m: *PthreadMutex) void { _ = std.c.pthread_mutex_unlock(&m.inner); }
    pub fn tryLock(m: *PthreadMutex) bool {
        return @intFromEnum(std.c.pthread_mutex_trylock(&m.inner)) == 0;
    }
};

const PthreadCondition = struct {
    inner: std.c.pthread_cond_t = std.c.PTHREAD_COND_INITIALIZER,
    pub fn timedWait(cond: *PthreadCondition, mutex: *PthreadMutex, timeout_ns: u64) !void {
        var ts: std.c.timespec = undefined;
        _ = std.c.clock_gettime(.REALTIME, &ts);
        const now_ns: u128 = @as(u128, @intCast(ts.sec)) * 1_000_000_000 +
                              @as(u128, @intCast(ts.nsec));
        const deadline_ns: u128 = now_ns + timeout_ns;
        const abs_time = std.c.timespec{
            .sec = @intCast(deadline_ns / 1_000_000_000),
            .nsec = @intCast(deadline_ns % 1_000_000_000),
        };
        const rc = std.c.pthread_cond_timedwait(&cond.inner, &mutex.inner, &abs_time);
        if (@intFromEnum(rc) == @intFromEnum(std.c.E.TIMEDOUT)) return error.Timeout;
    }
    pub fn signal(cond: *PthreadCondition) void { _ = std.c.pthread_cond_signal(&cond.inner); }
    pub fn broadcast(cond: *PthreadCondition) void { _ = std.c.pthread_cond_broadcast(&cond.inner); }
};
```

`std.Thread.sleep(ns)` → nanosleep:

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

## 5. `std.debug.lockStderrWriter` → `std.debug.lockStderr`

```zig
// Before (0.15)
const stderr = std.debug.lockStderrWriter();
defer std.debug.unlockStderr();
try stderr.print("...", .{});

// After (0.16)
var buffer: [4096]u8 = undefined;
const stderr = std.debug.lockStderr(&buffer);
defer std.debug.unlockStderr();
// stderr.file_writer is a File.Writer; its .interface is an Io.Writer
writeEvent(&stderr.file_writer.interface, event) catch {};
```

---

## 6. `std.crypto.random` removed

```zig
// Before
std.crypto.random.bytes(&nonce);

// After — arc4random_buf is available on macOS and Linux glibc 2.36+
extern "c" fn arc4random_buf(buf: *anyopaque, nbytes: usize) void;
// ...
arc4random_buf(&nonce, nonce.len);
```

Note: `std.posix.getrandom` does NOT exist in 0.16 (despite its name). For Linux-only
targets, use `std.os.linux.getrandom(buf.ptr, buf.len, 0)`.

---

## 7. `ArrayListUnmanaged` empty init changed

```zig
// Before (0.15) — .{} worked as zero-init
._list = .{},

// After (0.16) — explicit fields required
._list = .{ .items = &.{}, .capacity = 0 },
```

---

## 8. Local constants cannot shadow module-level `extern` declarations

If a function declares a local `const` with the same name as a module-level `extern fn`,
it is a compile error in 0.16 (even if the extern is declared later in the file):

```zig
extern "c" fn socket(...) c_int;   // module level

fn connect(...) !void {
    // WRONG: "local constant shadows declaration of socket"
    const socket = blk: { ... };

    // RIGHT: rename local variable
    const sock_fd = blk: { ... };
}
```

---

## File-by-File Summary

| File | Changes |
|---|---|
| `zig/src/server.zig` | `std.net.Stream`→`std.Io.net.Stream`; `stream.close()`→`stream.close(runtime.io)`; `stream.handle`→`stream.socket.handle`; add `streamWriteAll` + `posix.read`; `std.time.timestamp()`→`timestampSeconds()`; add `const posix = std.posix;` |
| `zig/src/runtime.zig` | **New**: shared `std.Io.Threaded` + `std.Io` globals |
| `zig/src/telemetry.zig` | `lockStderrWriter`→`lockStderr(&buf)` + `.file_writer.interface`; `milliTimestamp()` helper; `@divTrunc` for signed division |
| `zig/src/db.zig` | `std.net.Stream`→`std.Io.net.Stream`; `std.time.milliTimestamp()`→clock_gettime helper |
| `zig/zig-pkg/pg-*/src/stream.zig` | Replace `std.net.connectUnixSocket/tcpConnectToHost` with raw C externs; `posix.close`→`std.c.close`; rename local `socket`→`sock_fd`; `std.net.has_unix_sockets`→`std.Io.net.has_unix_sockets` |
| `zig/zig-pkg/pg-*/src/conn.zig` | `std.time.timestamp()`→`posixTimestamp()` helper; `ArrayListUnmanaged` empty init fix |
| `zig/zig-pkg/pg-*/src/pool.zig` | `Thread.Mutex/Condition`→`PthreadMutex/PthreadCondition` shims; helpers for nanoTimestamp/threadSleep |
| `zig/zig-pkg/pg-*/src/auth.zig` | `std.crypto.random.bytes`→`arc4random_buf` |
| `zig/zig-pkg/pg-*/src/types/numeric.zig` | `std.io.fixedBufferStream`→`std.fmt.bufPrint` |
| `zig/zig-pkg/N-V-.../src/buffer.zig` | `*std.io.Writer`→`*std.Io.Writer` in drain vtable |

---

## What Did NOT Change

- `std.posix.read` — still present (only `posix.write/connect/socket/close` removed)
- `std.posix.setsockopt`, `std.posix.timeval`, `std.posix.SOL/SO` — unchanged
- `std.posix.socket_t` (`= fd_t = c_int`) — unchanged
- `std.mem.*`, `std.fmt.*`, `std.json.*` — unchanged
- `std.c.getaddrinfo/freeaddrinfo`, `std.c.AF.*`, `std.c.SOCK.*`, `std.c.close` — all present
- `std.time.ns_per_s` constant — still present
- `std.Thread.spawn` — unchanged
- `callconv(.c)` FFI exports — unchanged
- Build system (`b.addLibrary`, `b.createModule`, etc.) — unchanged
- `std.heap.c_allocator` — unchanged
