# Zig 0.15.2 → 0.16 Migration Reference

A condensed, code-first reference for porting a Zig 0.15.x project to 0.16.
Every entry here was verified against a real build failure and its working fix.

---

## Build system (`build.zig`)

### `Compile.*` methods moved to `Module.*`

In 0.15 these were called directly on the artifact:

```zig
// 0.15
lib.addIncludePath(.{ .cwd_relative = path });
lib.addLibraryPath(.{ .cwd_relative = path });
lib.linkSystemLibrary("foo");
lib.addCSourceFile(.{ .file = b.path("shim.c"), .flags = &.{} });
```

In 0.16 they live on the module:

```zig
// 0.16
lib.root_module.addIncludePath(.{ .cwd_relative = path });
lib.root_module.addLibraryPath(.{ .cwd_relative = path });
lib.root_module.linkSystemLibrary("foo", .{});  // note: now takes options struct
lib.root_module.addCSourceFile(.{ .file = b.path("shim.c"), .flags = &.{} });
```

The compiler error looks like:

```
error: no field or member function named 'addIncludePath' in 'Build.Step.Compile'
note: method invocation only supports up to one level of implicit pointer dereferencing
note: use '.*' to dereference pointer
```

The note is misleading — the fix is not `lib.*.addIncludePath` but moving to `lib.root_module`.

Fields that remain on `Compile` directly: `linker_allow_shlib_undefined`, `linkage`, `name`, etc.

---

## Networking

### `std.net` removed → `std.Io.net` (requires `Io` instance)

```zig
// 0.15
const addr = try std.net.Address.parseIp4(host, port);
var server = try addr.listen(.{ .reuse_address = true });
const conn = try server.accept();   // returns .stream field
defer conn.stream.close();

// 0.16
const addr = try std.Io.net.IpAddress.parse(host, port);
var server = try addr.listen(io, .{ .reuse_address = true });
const stream = try server.accept(); // returns Stream directly — no .stream wrapper
defer stream.close(io);             // close() now takes io
```

You need a `std.Io` instance. Create one at startup and thread it through:

```zig
// Minimal runtime setup
var threaded = std.Io.Threaded.init(std.heap.c_allocator);
var io: std.Io = threaded.io();
```

### `stream.handle` → `stream.socket.handle`

```zig
// 0.15
std.posix.setsockopt(stream.handle, ...);

// 0.16
std.posix.setsockopt(stream.socket.handle, ...);
```

### `Io.net.Stream` has no `.read()` / `.writeAll()`

Use raw C calls for blocking I/O on worker threads:

```zig
extern "c" fn write(fd: c_int, buf: [*]const u8, n: usize) isize;

fn writeAll(stream: std.Io.net.Stream, data: []const u8) !void {
    var rem = data;
    while (rem.len > 0) {
        const n = write(stream.socket.handle, rem.ptr, rem.len);
        if (n <= 0) return error.BrokenPipe;
        rem = rem[@intCast(n)..];
    }
}

// posix.read() is still present:
const n = try std.posix.read(stream.socket.handle, buf);
```

### `std.net.connectUnixSocket` / `tcpConnectToHost` removed

Replace with C externs. **Important:** do not name local variables `socket` or `connect` —
0.16 errors if a local constant shadows a module-level `extern fn`:

```zig
extern "c" fn socket(domain: c_int, typ: c_int, proto: c_int) c_int;
extern "c" fn connect(fd: c_int, addr: *const anyopaque, len: u32) c_int;

fn connectTcp(host: []const u8, port: u16) !std.posix.socket_t {
    // Use sock_fd, not socket — "local constant shadows declaration of socket"
    const sock_fd = socket(std.c.AF.INET, std.c.SOCK.STREAM, 0);
    if (sock_fd < 0) return error.SystemResources;
    // ... getaddrinfo, connect, etc.
    return sock_fd;
}
```

### `std.net.has_unix_sockets` → `std.Io.net.has_unix_sockets`

```zig
if (comptime std.Io.net.has_unix_sockets) { ... }
```

### `std.posix.close` removed — use `std.c.close`

```zig
// 0.15
std.posix.close(fd);

// 0.16
_ = std.c.close(fd);
```

`std.posix.read` is still present. Only `close`, `write`, `connect`, and `socket` were removed.

---

## IO (`std.io` → `std.Io`)

### `std.io.fixedBufferStream` → `std.fmt.bufPrint`

```zig
// 0.15
var buf: [512]u8 = undefined;
var stream = std.io.fixedBufferStream(&buf);
try std.fmt.format(stream.writer(), "{d}", .{value});
useSlice(stream.getWritten());

// 0.16
var buf: [512]u8 = undefined;
const slice = try std.fmt.bufPrint(&buf, "{d}", .{value});
useSlice(slice);
```

### Vtable writer parameter: `*std.io.Writer` → `*std.Io.Writer`

```zig
// 0.15
fn drain(w: *std.io.Writer, data: []const u8) error{WriteFailed}!usize { ... }

// 0.16
fn drain(w: *std.Io.Writer, data: []const u8) error{WriteFailed}!usize { ... }
```

---

## Time

`std.time.timestamp()`, `milliTimestamp()`, and `nanoTimestamp()` are removed.
Use `clock_gettime` directly:

```zig
fn timestampSec() i64 {
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

`ts.nsec` is a signed integer — use `@divTrunc`, not `/`:

```zig
// compile error in 0.16: signed integer division without @divTrunc
const ms = @as(i64, ts.nsec) / 1_000_000;  // WRONG

const ms = @divTrunc(@as(i64, ts.nsec), 1_000_000);  // OK
```

`std.time.ns_per_s` is still present.

---

## Threading

`std.Thread.Mutex`, `std.Thread.Condition`, and `std.Thread.sleep` are removed.
The 0.16 replacements (`std.Io.Mutex` / `std.Io.Condition`) require an `Io` instance, which
is not always available (e.g. in libraries). POSIX shims are the portable fallback:

```zig
const PthreadMutex = struct {
    inner: std.c.pthread_mutex_t = std.c.PTHREAD_MUTEX_INITIALIZER,

    pub fn lock(m: *@This()) void   { _ = std.c.pthread_mutex_lock(&m.inner); }
    pub fn unlock(m: *@This()) void { _ = std.c.pthread_mutex_unlock(&m.inner); }
    pub fn tryLock(m: *@This()) bool {
        return @intFromEnum(std.c.pthread_mutex_trylock(&m.inner)) == 0;
    }
};

const PthreadCondition = struct {
    inner: std.c.pthread_cond_t = std.c.PTHREAD_COND_INITIALIZER,

    pub fn signal(c: *@This()) void    { _ = std.c.pthread_cond_signal(&c.inner); }
    pub fn broadcast(c: *@This()) void { _ = std.c.pthread_cond_broadcast(&c.inner); }

    pub fn timedWait(cond: *@This(), mutex: *PthreadMutex, timeout_ns: u64) !void {
        var ts: std.c.timespec = undefined;
        _ = std.c.clock_gettime(.REALTIME, &ts);
        const now_ns: u128 = @as(u128, @intCast(ts.sec)) * 1_000_000_000 +
                              @as(u128, @intCast(ts.nsec));
        const deadline = std.c.timespec{
            .sec  = @intCast((now_ns + timeout_ns) / 1_000_000_000),
            .nsec = @intCast((now_ns + timeout_ns) % 1_000_000_000),
        };
        const rc = std.c.pthread_cond_timedwait(&cond.inner, &mutex.inner, &deadline);
        if (@intFromEnum(rc) == @intFromEnum(std.c.E.TIMEDOUT)) return error.Timeout;
    }
};

fn threadSleep(ns: u64) void {
    const ts = std.c.timespec{
        .sec  = @intCast(ns / std.time.ns_per_s),
        .nsec = @intCast(ns % std.time.ns_per_s),
    };
    _ = std.c.nanosleep(&ts, null);
}
```

`std.Thread.spawn` is unchanged.

---

## Debug / stderr

```zig
// 0.15
const stderr = std.debug.lockStderrWriter();
defer std.debug.unlockStderr();
try stderr.print("msg: {s}\n", .{text});

// 0.16
var buf: [4096]u8 = undefined;
const held = std.debug.lockStderr(&buf);
defer std.debug.unlockStderr();
// held.file_writer is a File.Writer; .interface is the Io.Writer
try held.file_writer.print("msg: {s}\n", .{text});
```

---

## Random

`std.crypto.random` is removed. `std.posix.getrandom` does **not** exist in 0.16 despite the name.

```zig
// 0.15
std.crypto.random.bytes(&nonce);

// 0.16 — macOS + Linux glibc 2.36+
extern "c" fn arc4random_buf(buf: *anyopaque, nbytes: usize) void;
// ...
arc4random_buf(&nonce, nonce.len);

// 0.16 — Linux only (no glibc dependency)
_ = std.os.linux.getrandom(buf.ptr, buf.len, 0);
```

---

## `ArrayListUnmanaged` empty initialiser

```zig
// 0.15 — .{} zero-initialised to empty
var list: std.ArrayListUnmanaged(u8) = .{};

// 0.16 — explicit fields required
var list: std.ArrayListUnmanaged(u8) = .{ .items = &.{}, .capacity = 0 };
```

---

## Local constant cannot shadow module-level `extern`

0.16 treats it as a compile error even if the extern appears later in the file:

```zig
extern "c" fn socket(...) c_int;  // module level

fn myConnect(...) !void {
    const socket = blk: { ... };  // ERROR: "local constant shadows declaration of socket"
    const sock_fd = blk: { ... }; // OK — use a different name
}
```

---

## What did NOT change

| Thing | Still works |
|---|---|
| `std.posix.read` | yes |
| `std.posix.setsockopt`, `timeval`, `SOL`, `SO` | yes |
| `std.posix.socket_t` | yes |
| `std.mem.*`, `std.fmt.*`, `std.json.*` | yes |
| `std.c.getaddrinfo` / `freeaddrinfo` | yes |
| `std.c.AF.*`, `std.c.SOCK.*`, `std.c.close` | yes |
| `std.time.ns_per_s` | yes |
| `std.Thread.spawn` | yes |
| `callconv(.c)` FFI exports | yes |
| `b.addLibrary`, `b.createModule`, `b.dependency` | yes |
| `std.heap.c_allocator` | yes |
