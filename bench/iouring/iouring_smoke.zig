//! End-to-end smoke test for the iouring AcceptLoop on Linux.
//!
//! Pipeline:
//!   1. Open a non-blocking TCP listen socket on 127.0.0.1:<port>.
//!   2. Spawn a worker thread running `iouring.Linux.AcceptLoop.run`.
//!      Each accepted fd is counted then closed immediately.
//!   3. From the main thread, open N TCP connections to the listener.
//!   4. Wait until the AcceptLoop has counted N accepts, then stop it and
//!      assert that we saw exactly N.
//!
//! Exits 0 on success, non-zero on any failure. Designed to be a one-shot
//! sanity check inside an Apple `container` Linux VM (kernel 6.x), not a
//! benchmark.

const std = @import("std");
const builtin = @import("builtin");
const iouring = @import("iouring");

const linux = std.os.linux;
const posix = std.posix;

const N_CONNECTIONS: usize = 16;
const PORT: u16 = 18080;

const Counter = struct {
    accepts: std.atomic.Value(usize) = std.atomic.Value(usize).init(0),
    loop: ?*iouring.Linux.AcceptLoop = null,
};

pub fn main() !void {
    if (builtin.os.tag != .linux) {
        std.debug.print("skip: not Linux\n", .{});
        return;
    }
    if (!iouring.Available) {
        std.debug.print("skip: iouring.Available == false\n", .{});
        return;
    }

    // ── 1. listen socket ──
    const listen_fd = try createListenSocket(PORT);
    defer _ = linux.close(listen_fd);
    std.debug.print("listening on 127.0.0.1:{d} (fd={d})\n", .{ PORT, listen_fd });

    // ── 2. accept loop on its own thread ──
    var counter = Counter{};
    var loop = try iouring.Linux.AcceptLoop.init(
        listen_fd,
        onAccept,
        @ptrCast(&counter),
        iouring.DEFAULT_SQ_ENTRIES,
    );
    defer loop.deinit();
    counter.loop = &loop;

    const t = try std.Thread.spawn(.{}, runLoop, .{&loop});
    defer t.join();

    // ── 3. connect N times ──
    for (0..N_CONNECTIONS) |i| {
        try dialOnce(PORT);
        std.debug.print("  client {d}/{d} connected\n", .{ i + 1, N_CONNECTIONS });
    }

    // ── 4. wait + assert ──
    var waited_ms: usize = 0;
    while (counter.accepts.load(.acquire) < N_CONNECTIONS and waited_ms < 5_000) {
        var ts: linux.timespec = .{ .sec = 0, .nsec = 10 * std.time.ns_per_ms };
        _ = linux.nanosleep(&ts, null);
        waited_ms += 10;
    }

    loop.stop();

    // Touch the loop one more time so copy_cqes wakes up. A no-op connect is
    // the cheapest way to force a CQE.
    dialOnce(PORT) catch {};

    const got = counter.accepts.load(.acquire);
    std.debug.print("io_uring AcceptLoop saw {d} accepts (wanted >= {d})\n", .{ got, N_CONNECTIONS });
    if (got < N_CONNECTIONS) {
        std.debug.print("FAIL\n", .{});
        std.process.exit(1);
    }
    std.debug.print("OK\n", .{});
}

fn runLoop(loop: *iouring.Linux.AcceptLoop) void {
    loop.run() catch |err| {
        std.debug.print("loop.run errored: {s}\n", .{@errorName(err)});
    };
}

fn onAccept(ctx: *anyopaque, fd: posix.fd_t) void {
    const counter: *Counter = @ptrCast(@alignCast(ctx));
    _ = counter.accepts.fetchAdd(1, .acq_rel);
    _ = linux.close(fd);
}

fn createListenSocket(port: u16) !posix.fd_t {
    const fd_signed = linux.socket(linux.AF.INET, linux.SOCK.STREAM | linux.SOCK.CLOEXEC, 0);
    if (fd_signed < 0) return error.SocketFailed;
    const fd: posix.fd_t = @intCast(fd_signed);

    const yes: c_int = 1;
    _ = linux.setsockopt(fd, linux.SOL.SOCKET, linux.SO.REUSEADDR, std.mem.asBytes(&yes), @sizeOf(c_int));

    var addr: linux.sockaddr.in = .{
        .family = linux.AF.INET,
        .port = std.mem.nativeToBig(u16, port),
        .addr = std.mem.nativeToBig(u32, 0x7F000001), // 127.0.0.1
        .zero = .{0} ** 8,
    };
    if (linux.bind(fd, @ptrCast(&addr), @sizeOf(linux.sockaddr.in)) != 0) return error.BindFailed;
    if (linux.listen(fd, 128) != 0) return error.ListenFailed;
    return fd;
}

fn dialOnce(port: u16) !void {
    const fd_signed = linux.socket(linux.AF.INET, linux.SOCK.STREAM | linux.SOCK.CLOEXEC, 0);
    if (fd_signed < 0) return error.SocketFailed;
    const fd: posix.fd_t = @intCast(fd_signed);
    defer _ = linux.close(fd);

    var addr: linux.sockaddr.in = .{
        .family = linux.AF.INET,
        .port = std.mem.nativeToBig(u16, port),
        .addr = std.mem.nativeToBig(u32, 0x7F000001),
        .zero = .{0} ** 8,
    };
    if (linux.connect(fd, @ptrCast(&addr), @sizeOf(linux.sockaddr.in)) != 0) {
        return error.ConnectFailed;
    }
}
