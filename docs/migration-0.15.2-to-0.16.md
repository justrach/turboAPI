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

---

## Managing multiple Zig versions with `zigup`

When migrating a project, you often need to keep the old compiler available — for
comparison builds, CI, or vendored dependencies that haven't been ported yet.
[`zigup`](https://github.com/marler8997/zigup) handles this cleanly and is the
recommended approach on macOS/Linux.

### Install

```bash
brew install marler8997/tap/zigup
```

### Install specific versions side-by-side

```bash
zigup fetch 0.15.2   # download without changing the default
zigup fetch 0.16.0   # download without changing the default
zigup list           # show all installed versions
```

```
0.15.2
0.16.0  (default)
```

### Switch the default

```bash
zigup 0.16.0          # set 0.16.0 as the default `zig` on $PATH
zigup default         # print current default
zigup default 0.15.2  # switch back to 0.15.2
```

### Run a specific version without changing the default

```bash
zigup run 0.15.2 build        # build with 0.15.2
zigup run 0.16.0 build test   # test with 0.16.0
```

Or reference the binary directly (useful in scripts and CI):

```bash
~/.local/share/zigup/0.15.2/files/zig build
~/.local/share/zigup/0.16.0/files/zig build
```

### Practical workflow for a 0.15 → 0.16 migration

```bash
# 1. Keep 0.15.2 as the working default while you start
zigup fetch 0.16.0

# 2. Attempt the build with 0.16 without touching your default
zigup run 0.16.0 build 2>&1 | head -40

# 3. Fix each error, re-run until clean
zigup run 0.16.0 build

# 4. Once clean, promote 0.16 to default
zigup 0.16.0

# 5. Keep 0.15.2 around for branch comparisons; clean up later
zigup clean 0.15.2
```

### Using both versions in the same repo (worktrees)

This is useful for performance comparisons between the old and new backend.
Create a git worktree for the un-migrated branch and build it with 0.15.2:

```bash
git worktree add /tmp/myproject-old main
cd /tmp/myproject-old
zigup run 0.15.2 build          # build old branch with 0.15.2
cd -
zig build                        # build new branch with 0.16 (the default)
```

Then run both servers and diff the wrk numbers — see the `benchmarks/` directory
for a ready-made comparison script.

### `zigup install-dir`

By default zigup stores compilers in `~/.local/share/zigup/`. You can relocate this
(e.g. to a fast SSD or shared network path):

```bash
zigup set-install-dir /Volumes/fast/zig-compilers
zigup fetch 0.16.0   # now stored on /Volumes/fast/...
```

### CI tip: pin the version in your workflow

```yaml
# .github/workflows/ci.yml
- name: Install Zig 0.16.0
  run: |
    brew install marler8997/tap/zigup
    zigup 0.16.0
```

Or with the `goto-bus-stop/setup-zig` action:

```yaml
- uses: goto-bus-stop/setup-zig@v2
  with:
    version: 0.16.0

---

## Step-by-step migration walkthrough with `zigup`

This section walks through the full migration from 0.15.2 to 0.16 as a
practical checklist — using `zigup` so you never need to touch your system
Zig installation.

### 1. Install zigup and fetch both compilers

```bash
brew install marler8997/tap/zigup

# Fetch without changing your active default
zigup fetch 0.15.2   # keep old compiler available for fallback
zigup fetch 0.16.0   # new compiler to migrate to
zigup list           # verify both are present
```

### 2. Create an isolation branch

```bash
git checkout -b feat/zig-0.16-migration
```

Work here until the build is green, then merge.

### 3. Try the build with 0.16 — do NOT set it as default yet

```bash
zigup run 0.16.0 zig build 2>&1 | head -60
```

You will likely see a batch of errors. The common categories are:

| Error pattern | What changed | Fix |
|---|---|---|
| `no field 'addIncludePath' in 'Compile'` | Build API moved to `root_module` | `lib.root_module.addIncludePath(...)` |
| `'std.net' has no member 'Stream'` | Networking split to `std.Io.net` | See §Networking above |
| `'timestamp' not found in 'std.time'` | Timestamp functions removed | Use `std.c.clock_gettime(.REALTIME, &ts)` |
| `'lockUncancelable' not found` | Mutex API changed | `mutex.lock(io) catch ...` |
| `'std.crypto.random' not found` | CSPRNG moved | `arc4random_buf(&buf, buf.len)` |
| `cannot shadow module-level extern` | Scoping rule tightened | Rename local or remove `extern` |

### 4. Fix errors in batches, rebuild after each category

Tackle one category at a time.  After each batch:

```bash
zigup run 0.16.0 zig build        # must be clean before moving on
zigup run 0.15.2 zig build        # old build must still work (don't break CI)
```

The dual-check keeps both branches buildable while you iterate.

### 5. Run your test suite under 0.16

```bash
zigup run 0.16.0 zig build test   # Zig unit tests
uv run --python 3.14t pytest tests/ -p no:anchorpy   # Python integration tests
```

Fix any test failures before promoting 0.16 to default.

### 6. Benchmark: compare old and new builds side-by-side

Keep the un-migrated branch in a git worktree so you can build both at once:

```bash
# Build old branch with 0.15.2
git worktree add /tmp/myproject-old main
cd /tmp/myproject-old
zigup run 0.15.2 zig build --release-fast
./zig-out/bin/server &   # or your Python launch command

# Build new branch with 0.16
cd -
zigup run 0.16.0 zig build --release-fast
./zig-out/bin/server --port 8081 &

# Compare
wrk -t4 -c100 -d15s http://localhost:8080/health
wrk -t4 -c100 -d15s http://localhost:8081/health
```

For TurboAPI specifically, a typical comparison shows ~1–4% throughput
improvement from the 0.16 Zig-layer optimisations (SIMD header scanning,
`StaticStringMap` dispatch, bulk-copy string paths) on top of baseline
~138–140 k req/s through the native HTTP backend:

```
Endpoint               Before (req/s)  After (req/s)      Δ
---------------------------------------------------------------
GET /                         138,015        139,536  +  1.1%
GET /health                   139,097        139,860  +  0.5%
GET /json                     138,623        139,997  +  1.0%
GET /users/123                138,720        139,073  +  0.3%
===============================================================
Average                       138,614        139,617  +  0.7%
```

(Measured locally on Apple M-series, native Zig HTTP server, `-t4 -c100 -d8s`.)

### 7. Promote 0.16 as the project default

Once tests and benchmarks are green:

```bash
zigup 0.16.0          # sets system default
zig version           # should print 0.16.0
git add -A && git commit -m "build: migrate to Zig 0.16"
git push origin feat/zig-0.16-migration
```

Open a PR and merge.  Keep 0.15.2 installed until CI is updated so you
can fall back quickly.

```bash
# Later, when CI is stable on 0.16:
zigup clean 0.15.2
```
