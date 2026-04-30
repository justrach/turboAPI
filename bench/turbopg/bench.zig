//! Throughput bench for the vendored pg.zig driver.
//!
//! Spawns N worker threads, each running a hot loop of either:
//!   * `SELECT 1`
//!   * `SELECT generate_series(1,50) AS id`
//!
//! against a single Postgres instance. Each thread owns its own
//! `pg.Conn` (no pool contention, no scheduler), so the only thing
//! varying between the blocking-build and the iouring-build is the
//! stream transport in `zig/pg/src/stream.zig`.
//!
//! Output is plain text:
//!
//!   transport=<blocking|iouring> threads=N duration=Ds query=<id>
//!     queries=Q rows=R rps=X.YZ
//!
//! Per AGENTS.md, do NOT cite these numbers in release notes.

const std = @import("std");
const pg = @import("pg");

const Args = struct {
    host: []const u8 = "127.0.0.1",
    port: u16 = 5432,
    user: []const u8 = "postgres",
    database: []const u8 = "postgres",
    threads: usize = 4,
    duration_s: u64 = 10,
    query_id: u8 = 1,
    label: []const u8 = "blocking",

    fn fromEnv(_: std.mem.Allocator) !Args {
        var a: Args = .{};
        if (getenv("PGHOST")) |v| a.host = v;
        if (getenv("PGPORT")) |v| a.port = try std.fmt.parseInt(u16, v, 10);
        if (getenv("PGUSER")) |v| a.user = v;
        if (getenv("PGDATABASE")) |v| a.database = v;
        if (getenv("BENCH_THREADS")) |v| a.threads = try std.fmt.parseInt(usize, v, 10);
        if (getenv("BENCH_DURATION")) |v| a.duration_s = try std.fmt.parseInt(u64, v, 10);
        if (getenv("BENCH_QUERY")) |v| a.query_id = try std.fmt.parseInt(u8, v, 10);
        if (getenv("BENCH_LABEL")) |v| a.label = v;
        return a;
    }
};

fn nowNs() i128 {
    var ts: std.posix.timespec = undefined;
    _ = std.posix.system.clock_gettime(.MONOTONIC, &ts);
    return @as(i128, ts.sec) * 1_000_000_000 + @as(i128, ts.nsec);
}

fn sleepSeconds(secs: u64) void {
    var ts: std.posix.timespec = .{ .sec = @intCast(secs), .nsec = 0 };
    _ = std.posix.system.nanosleep(&ts, null);
}

fn getenv(key: []const u8) ?[]const u8 {
    // libc getenv; each worker thread only reads it, never mutates.
    var buf: [128]u8 = undefined;
    const key_z = std.fmt.bufPrintZ(&buf, "{s}", .{key}) catch return null;
    const raw = std.c.getenv(key_z.ptr) orelse return null;
    return std.mem.span(raw);
}

const ThreadStats = struct {
    queries: u64 = 0,
    rows: u64 = 0,
    err_count: u64 = 0,
};

fn workerLoop(
    args: *const Args,
    stop_flag: *std.atomic.Value(bool),
    stats: *ThreadStats,
) !void {
    const allocator = std.heap.smp_allocator;

    var conn = try pg.Conn.open(allocator, .{
        .host = args.host,
        .port = args.port,
    });
    defer conn.deinit();

    try conn.auth(.{
        .username = args.user,
        .database = args.database,
        .timeout = 10_000,
    });

    const sql = switch (args.query_id) {
        1 => "SELECT 1",
        2 => "SELECT id FROM generate_series(1, 50) AS id",
        else => "SELECT 1",
    };

    while (!stop_flag.load(.acquire)) {
        var result = conn.query(sql, .{}) catch |err| {
            stats.err_count += 1;
            if (stats.err_count > 10) return err;
            continue;
        };
        defer result.deinit();

        while (result.next() catch null) |_| {
            stats.rows += 1;
        }
        stats.queries += 1;
    }
}

fn workerEntry(
    args: *const Args,
    stop_flag: *std.atomic.Value(bool),
    stats: *ThreadStats,
) void {
    workerLoop(args, stop_flag, stats) catch |err| {
        std.debug.print("worker error: {s}\n", .{@errorName(err)});
    };
}

pub fn main() !void {
    const allocator = std.heap.smp_allocator;

    const args = try Args.fromEnv(allocator);

    std.debug.print(
        "[bench] transport={s} threads={d} duration={d}s query={d} host={s}:{d}\n",
        .{ args.label, args.threads, args.duration_s, args.query_id, args.host, args.port },
    );

    var stop_flag = std.atomic.Value(bool).init(false);

    const stats = try allocator.alloc(ThreadStats, args.threads);
    @memset(stats, .{});
    defer allocator.free(stats);

    const threads = try allocator.alloc(std.Thread, args.threads);
    defer allocator.free(threads);

    const t_start = nowNs();
    for (threads, 0..) |*t, i| {
        t.* = try std.Thread.spawn(.{}, workerEntry, .{ &args, &stop_flag, &stats[i] });
    }

    sleepSeconds(args.duration_s);

    stop_flag.store(true, .release);
    for (threads) |t| t.join();
    const t_end = nowNs();

    var total_q: u64 = 0;
    var total_r: u64 = 0;
    var total_e: u64 = 0;
    for (stats) |s| {
        total_q += s.queries;
        total_r += s.rows;
        total_e += s.err_count;
    }
    const elapsed_s: f64 = @as(f64, @floatFromInt(t_end - t_start)) / 1e9;
    const rps: f64 = @as(f64, @floatFromInt(total_q)) / elapsed_s;
    const rows_ps: f64 = @as(f64, @floatFromInt(total_r)) / elapsed_s;

    std.debug.print(
        "[bench] result transport={s} queries={d} rows={d} errors={d} elapsed={d:.2}s rps={d:.2} rows_ps={d:.2}\n",
        .{ args.label, total_q, total_r, total_e, elapsed_s, rps, rows_ps },
    );
}
