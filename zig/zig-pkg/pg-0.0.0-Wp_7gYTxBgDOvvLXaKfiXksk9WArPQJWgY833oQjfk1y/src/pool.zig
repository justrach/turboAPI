const std = @import("std");
const lib = @import("lib.zig");

const log = lib.log;
const Conn = lib.Conn;
const Result = lib.Result;
const SSLCtx = lib.SSLCtx;
const QueryRow = lib.QueryRow;
const QueryRowUnsafe = lib.QueryRowUnsafe;
const DynamicValue = lib.types.DynamicValue;
const Listener = @import("listener.zig").Listener;

const Thread = std.Thread;
const Allocator = std.mem.Allocator;

// Zig 0.16: Thread.Mutex/Condition moved to Io.Mutex/Condition which requires an Io instance.
// pg has no Io context, so fall back to POSIX pthreads directly.
const PthreadMutex = struct {
    inner: std.c.pthread_mutex_t = std.c.PTHREAD_MUTEX_INITIALIZER,

    pub fn lock(m: *PthreadMutex) void {
        _ = std.c.pthread_mutex_lock(&m.inner);
    }
    pub fn unlock(m: *PthreadMutex) void {
        _ = std.c.pthread_mutex_unlock(&m.inner);
    }
    pub fn tryLock(m: *PthreadMutex) bool {
        return @intFromEnum(std.c.pthread_mutex_trylock(&m.inner)) == 0;
    }
};

const PthreadCondition = struct {
    inner: std.c.pthread_cond_t = std.c.PTHREAD_COND_INITIALIZER,

    pub fn timedWait(cond: *PthreadCondition, mutex: *PthreadMutex, timeout_ns: u64) !void {
        var ts: std.c.timespec = undefined;
        _ = std.c.clock_gettime(.REALTIME, &ts);
        const now_ns: u128 = @as(u128, @intCast(ts.sec)) * 1_000_000_000 + @as(u128, @intCast(ts.nsec));
        const deadline_ns: u128 = now_ns + timeout_ns;
        const abs_time = std.c.timespec{
            .sec = @intCast(deadline_ns / 1_000_000_000),
            .nsec = @intCast(deadline_ns % 1_000_000_000),
        };
        const rc = std.c.pthread_cond_timedwait(&cond.inner, &mutex.inner, &abs_time);
        if (@intFromEnum(rc) == @intFromEnum(std.c.E.TIMEDOUT)) return error.Timeout;
    }

    pub fn signal(cond: *PthreadCondition) void {
        _ = std.c.pthread_cond_signal(&cond.inner);
    }
    pub fn broadcast(cond: *PthreadCondition) void {
        _ = std.c.pthread_cond_broadcast(&cond.inner);
    }
};

fn nanoTimestamp() i128 {
    var ts: std.c.timespec = undefined;
    _ = std.c.clock_gettime(.REALTIME, &ts);
    return @as(i128, ts.sec) * 1_000_000_000 + @as(i128, ts.nsec);
}

fn threadSleep(ns: u64) void {
    const ts = std.c.timespec{
        .sec = @intCast(ns / std.time.ns_per_s),
        .nsec = @intCast(ns % std.time.ns_per_s),
    };
    _ = std.c.nanosleep(&ts, null);
}

pub const Pool = struct {
    _opts: Opts,
    _timeout: u64,
    _conns: []*Conn,
    _available: usize,
    _missing: usize,
    _allocator: Allocator,
    _mutex: PthreadMutex,
    _cond: PthreadCondition,
    _ssl_ctx: ?*lib.SSLCtx,
    _reconnector: Reconnector,
    _arena: std.heap.ArenaAllocator,

    pub const Opts = struct {
        size: u16 = 10,
        auth: Conn.AuthOpts = .{},
        connect: Conn.Opts = .{},
        timeout: u32 = 10 * std.time.ms_per_s,
        connect_on_init_count: ?u16 = null,
        max_queries_per_conn: u64 = 0, // 0 = unlimited
        max_conn_lifetime: i64 = 0, // 0 = unlimited (seconds)
    };

    pub const Stats = struct {
        size: usize,
        available: usize,
        missing: usize,
        in_use: usize,
    };

    pub fn initUri(allocator: Allocator, uri: std.Uri, opts: Opts) !*Pool {
        var po = try lib.parseOpts(uri, allocator);
        defer po.deinit();
        po.opts.size = opts.size;
        po.opts.timeout = opts.timeout;
        return Pool.init(allocator, po.opts);
    }

    pub fn init(allocator: Allocator, opts: Opts) !*Pool {
        var arena = std.heap.ArenaAllocator.init(allocator);
        const aa = arena.allocator();
        errdefer arena.deinit();

        const pool = try aa.create(Pool);
        const size = opts.size;
        const conns = try aa.alloc(*Conn, size);

        var opts_copy = opts;
        var ssl_ctx: ?*SSLCtx = null;
        if (comptime lib.has_openssl) {
            switch (opts.connect.tls) {
                .off => {},
                else => |tls_config| {
                    if (opts.connect.host) |h| {
                        opts_copy.connect._hostz = try aa.dupeZ(u8, h);
                    }
                    ssl_ctx = try lib.initializeSSLContext(tls_config);
                },
            }
        }
        errdefer lib.freeSSLContext(ssl_ctx);
        const connect_on_init_count = opts.connect_on_init_count orelse size;

        pool.* = .{
            ._cond = .{},
            ._mutex = .{},
            ._conns = conns,
            ._arena = arena,
            ._opts = opts_copy,
            ._ssl_ctx = ssl_ctx,
            ._missing = 0,
            ._allocator = allocator,
            ._available = connect_on_init_count,
            ._reconnector = Reconnector.init(pool),
            ._timeout = @as(u64, @intCast(opts.timeout)) * std.time.ns_per_ms,
        };

        var opened_connections: usize = 0;
        errdefer {
            for (0..opened_connections) |i| {
                conns[i].deinit();
            }
        }

        for (0..connect_on_init_count) |i| {
            conns[i] = try newConnection(pool, true);
            opened_connections += 1;
        }

        const lazy_start_count = size - connect_on_init_count;
        pool._missing = lazy_start_count;
        for (0..lazy_start_count) |_| {
            try pool._reconnector.reconnect();
        }

        return pool;
    }

    pub fn deinit(self: *Pool) void {
        self._reconnector.stop();
        const allocator = self._allocator;
        for (self._conns) |conn| {
            conn.deinit();
            allocator.destroy(conn);
        }
        lib.freeSSLContext(self._ssl_ctx);
        self._arena.deinit();
    }

    pub fn acquire(self: *Pool) !*Conn {
        const conns = self._conns;
        const deadline = nanoTimestamp() + @as(i128, @intCast(self._timeout));

        self._mutex.lock();
        errdefer self._mutex.unlock();

        while (true) {
            const available = self._available;
            const missing = self._missing;

            if (available == 0) {
                // Check if pool is completely exhausted
                const total_alive = self._conns.len - missing;
                if (total_alive == 0) {
                    return error.PoolExhausted;
                }

                lib.metrics.poolEmpty();

                // Calculate remaining timeout
                const now = nanoTimestamp();
                if (now >= deadline) {
                    return error.Timeout;
                }
                const remaining_ns: u64 = @intCast(deadline - now);

                try self._cond.timedWait(&self._mutex, remaining_ns);
                continue;
            }

            const index = available - 1;
            const conn = conns[index];
            self._available = index;
            self._mutex.unlock();
            return conn;
        }
    }

    pub fn release(self: *Pool, conn: *Conn) void {
        var conn_to_add = conn;
        var needs_replace = conn._state != .idle;

        if (!needs_replace) {
            // Check if connection should be rotated (query count or age)
            const opts = self._opts;
            if (opts.max_queries_per_conn > 0 and conn.queryCount() >= opts.max_queries_per_conn) {
                needs_replace = true;
            } else if (opts.max_conn_lifetime > 0 and conn.age() >= opts.max_conn_lifetime) {
                needs_replace = true;
            }
        }

        if (needs_replace) {
            if (conn._state != .idle) {
                lib.metrics.poolDirty();
            }
            conn.deinit();
            self._allocator.destroy(conn);

            conn_to_add = newConnection(self, true) catch |err1| {
                self._mutex.lock();
                self._missing += 1;
                self._mutex.unlock();

                self._reconnector.reconnect() catch |err2| {
                    log.err("Re-opening connection failed ({}) and background reconnector failed to start ({})", .{ err1, err2 });
                };
                return;
            };
        }

        var conns = self._conns;
        self._mutex.lock();
        const available = self._available;
        conns[available] = conn_to_add;
        self._available = available + 1;
        self._mutex.unlock();
        self._cond.signal();
    }

    pub fn newListener(self: *Pool) !Listener {
        var listener = try Listener.open(self._allocator, self._opts.connect);
        try listener.auth(self._opts.auth);
        return listener;
    }

    pub fn stats(self: *Pool) Stats {
        self._mutex.lock();
        defer self._mutex.unlock();

        const available = self._available;
        const missing = self._missing;
        const size = self._conns.len;

        return .{
            .size = size,
            .available = available,
            .missing = missing,
            .in_use = size - available - missing,
        };
    }

    pub fn exec(self: *Pool, sql: []const u8, values: anytype) !?i64 {
        return self.execOpts(sql, values, .{});
    }

    pub fn execOpts(self: *Pool, sql: []const u8, values: anytype, opts: Conn.QueryOpts) !?i64 {
        var conn = try self.acquire();
        defer self.release(conn);
        return conn.execOpts(sql, values, opts);
    }

    pub fn execManyDynamic(self: *Pool, sql: []const u8, rows: []const []const DynamicValue, opts: Conn.QueryOpts) !i64 {
        var conn = try self.acquire();
        defer self.release(conn);
        return conn.execManyDynamic(sql, rows, opts);
    }

    pub fn query(self: *Pool, sql: []const u8, values: anytype) !*Result {
        return self.queryOpts(sql, values, .{});
    }

    pub fn queryOpts(self: *Pool, sql: []const u8, values: anytype, opts_: Conn.QueryOpts) !*Result {
        var opts = opts_;
        opts.release_conn = true;
        var conn = try self.acquire();
        errdefer self.release(conn);
        return conn.queryOpts(sql, values, opts);
    }

    pub fn row(self: *Pool, sql: []const u8, values: anytype) !?QueryRow {
        return self.rowOpts(sql, values, .{});
    }

    pub fn rowUnsafe(self: *Pool, sql: []const u8, values: anytype) !?QueryRowUnsafe {
        return self.rowUnsafeOpts(sql, values, .{});
    }

    pub fn rowOpts(self: *Pool, sql: []const u8, values: anytype, opts_: Conn.QueryOpts) !?QueryRow {
        var opts = opts_;
        opts.release_conn = true;
        var conn = try self.acquire();
        return conn.rowOpts(sql, values, opts);
    }

    pub fn rowUnsafeOpts(self: *Pool, sql: []const u8, values: anytype, opts_: Conn.QueryOpts) !?QueryRowUnsafe {
        var opts = opts_;
        opts.release_conn = true;
        var conn = try self.acquire();
        return conn.rowUnsafeOpts(sql, values, opts);
    }
};

const Reconnector = struct {
    // number of connections that the pool is missing, i.e. how many need to be
    // reconnected
    count: usize,

    // when stop is called, this is set to true
    stopped: bool,

    pool: *Pool,
    mutex: PthreadMutex,

    // the thread, if any, that the monitor is running in
    thread: ?Thread,

    fn init(pool: *Pool) Reconnector {
        return .{
            .pool = pool,
            .count = 0,
            .mutex = .{},
            .stopped = false,
            .thread = null,
        };
    }

    fn run(self: *Reconnector) void {
        const pool = self.pool;
        const retry_delay = 2 * std.time.ns_per_s;

        self.mutex.lock();
        defer self.mutex.unlock();
        loop: while (self.count > 0) {
            const stopped = self.stopped;
            self.mutex.unlock();
            if (stopped == true) {
                return;
            }

            const conn = newConnection(pool, false) catch {
                threadSleep(retry_delay);
                self.mutex.lock();
                continue :loop;
            };

            // Decrement missing count when successfully recreated
            pool._mutex.lock();
            std.debug.assert(pool._missing > 0);
            pool._missing -= 1;
            pool._mutex.unlock();

            conn.release(); // inserts it into the pool
            self.mutex.lock();
            self.count -= 1;
        }

        self.thread.?.detach();
        self.thread = null;
    }

    fn stop(self: *Reconnector) void {
        self.mutex.lock();
        self.stopped = true;
        self.mutex.unlock();
        if (self.thread) |thrd| {
            thrd.join();
        }
    }

    fn reconnect(self: *Reconnector) !void {
        self.mutex.lock();
        defer self.mutex.unlock();
        self.count += 1;
        if (self.thread == null) {
            self.thread = try Thread.spawn(.{ .stack_size = 1024 * 1024 }, Reconnector.run, .{self});
        }
    }
};

fn newConnection(pool: *Pool, log_failure: bool) !*Conn {
    const opts = &pool._opts;
    const allocator = pool._allocator;

    const conn = allocator.create(Conn) catch |err| {
        if (log_failure) log.err("connect error: {}", .{err});
        return err;
    };
    errdefer allocator.destroy(conn);

    conn.* = Conn.open(allocator, opts.connect) catch |err| {
        if (log_failure) log.err("connect error: {}", .{err});
        return err;
    };
    errdefer conn.deinit();

    conn.auth(opts.auth) catch |err| {
        if (log_failure) {
            if (conn.err) |pg_err| {
                log.err("connect error: {s}", .{pg_err.message});
            } else {
                log.err("connect error: {}", .{err});
            }
        }
        return err;
    };
    conn._pool = pool;
    return conn;
}

const t = lib.testing;
test "Pool" {
    var pool = try Pool.init(t.allocator, .{
        .size = 2,
        .auth = t.authOpts(.{}),
        .connect_on_init_count = 1,
    });
    defer pool.deinit();

    {
        const c1 = try pool.acquire();
        defer pool.release(c1);
        _ = try c1.exec(
            \\ drop table if exists pool_test;
            \\ create table pool_test (id int not null)
        , .{});
    }

    const t1 = try std.Thread.spawn(.{}, testPool, .{pool});
    const t2 = try std.Thread.spawn(.{}, testPool, .{pool});
    const t3 = try std.Thread.spawn(.{}, testPool, .{pool});

    t1.join();
    t2.join();
    t3.join();

    {
        const c1 = try pool.acquire();
        defer c1.release();

        const affected = try c1.exec("delete from pool_test", .{});
        try t.expectEqual(1500, affected.?);
    }
}

test "Pool: Release" {
    var pool = try Pool.init(t.allocator, .{
        .size = 2,
        .auth = .{
            .database = "postgres",
            .username = "postgres",
            .password = "postgres",
        },
    });
    defer pool.deinit();

    const c1 = try pool.acquire();
    c1._state = .query;
    pool.release(c1);
}

test "Pool: stats" {
    var pool = try Pool.init(t.allocator, .{
        .size = 3,
        .auth = t.authOpts(.{}),
    });
    defer pool.deinit();

    // Initial state: all connections available
    {
        const s = pool.stats();
        try t.expectEqual(3, s.size);
        try t.expectEqual(3, s.available);
        try t.expectEqual(0, s.missing);
        try t.expectEqual(0, s.in_use);
    }

    // Acquire one connection
    const c1 = try pool.acquire();
    {
        const s = pool.stats();
        try t.expectEqual(3, s.size);
        try t.expectEqual(2, s.available);
        try t.expectEqual(0, s.missing);
        try t.expectEqual(1, s.in_use);
    }

    // Acquire another
    const c2 = try pool.acquire();
    {
        const s = pool.stats();
        try t.expectEqual(3, s.size);
        try t.expectEqual(1, s.available);
        try t.expectEqual(0, s.missing);
        try t.expectEqual(2, s.in_use);
    }

    // Release one
    pool.release(c1);
    {
        const s = pool.stats();
        try t.expectEqual(3, s.size);
        try t.expectEqual(2, s.available);
        try t.expectEqual(0, s.missing);
        try t.expectEqual(1, s.in_use);
    }

    // Release the other
    pool.release(c2);
    {
        const s = pool.stats();
        try t.expectEqual(3, s.size);
        try t.expectEqual(3, s.available);
        try t.expectEqual(0, s.missing);
        try t.expectEqual(0, s.in_use);
    }
}

test "Pool: exec" {
    var pool = try Pool.init(t.allocator, .{ .size = 1, .auth = t.authOpts(.{}) });
    defer pool.deinit();

    {
        const n = try pool.exec("insert into simple_table values ($1), ($2), ($3)", .{ "pool_insert_args_a", "pool_insert_args_b", "pool_insert_args_c" });
        try t.expectEqual(3, n.?);
    }

    {
        // this makes sure the connection was returned to the pool
        const n = try pool.exec("insert into simple_table values ($1)", .{"pool_insert_args_a"});
        try t.expectEqual(1, n.?);
    }
}

test "Pool: Query/Row" {
    var pool = try Pool.init(t.allocator, .{ .size = 1, .auth = t.authOpts(.{}) });
    defer pool.deinit();

    {
        _ = try pool.exec("insert into all_types (id, col_int8, col_text) values ($1, $2, $3)", .{ 100, 1, "val-1" });
        _ = try pool.exec("insert into all_types (id, col_int8, col_text) values ($1, $2, $3)", .{ 101, 2, "val-2" });
    }

    for (0..3) |_| {
        var result = try pool.query("select col_int8, col_text from all_types where id = any($1)", .{[2]i32{ 100, 101 }});
        defer result.deinit();

        const row1 = (try result.nextUnsafe()) orelse unreachable;
        try t.expectEqual(1, row1.get(i64, 0));
        try t.expectString("val-1", row1.get([]u8, 1));

        const row2 = (try result.nextUnsafe()) orelse unreachable;
        try t.expectEqual(2, row2.get(i64, 0));
        try t.expectString("val-2", row2.get([]u8, 1));

        try t.expectEqual(null, result.nextUnsafe());
    }

    for (0..3) |_| {
        var row = try pool.rowUnsafe("select col_int8, col_text from all_types where id = $1", .{101}) orelse unreachable;
        defer row.deinit() catch {};

        try t.expectEqual(2, row.get(i64, 0));
        try t.expectString("val-2", row.get([]u8, 1));
    }
}

test "Pool: Row error" {
    var pool = try Pool.init(t.allocator, .{ .size = 1, .auth = t.authOpts(.{}) });
    defer pool.deinit();

    _ = try pool.rowUnsafe("insert into all_types (id) values ($1)", .{200});

    // This would segfault:
    // https://github.com/karlseguin/pg.zig/issues/34
    try t.expectError(error.PG, pool.rowUnsafe("insert into all_types (id) values ($1)", .{200}));

    try t.expectEqual(1, pool._available);
}

fn testPool(p: *Pool) void {
    for (0..500) |i| {
        const conn = p.acquire() catch unreachable;
        _ = conn.exec("insert into pool_test (id) values ($1)", .{i}) catch unreachable;
        conn.release();
    }
}
