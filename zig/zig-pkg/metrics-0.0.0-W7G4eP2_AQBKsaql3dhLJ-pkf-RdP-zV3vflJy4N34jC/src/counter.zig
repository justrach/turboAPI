const std = @import("std");
const Allocator = std.mem.Allocator;

const m = @import("metric.zig");
const MetricVec = m.MetricVec;

const RegistryOpts = @import("registry.zig").Opts;

const Opts = struct {
    help: ?[]const u8 = null,
};

pub fn Counter(comptime V: type) type {
    assertCounterType(V);
    return union(enum) {
        noop: void,
        impl: Impl,

        const Self = @This();

        pub fn init(comptime name: []const u8, comptime opts: Opts, comptime ropts: RegistryOpts) Self {
            switch (ropts.shouldExclude(name)) {
                true => return .{ .noop = {} },
                false => return .{ .impl = Impl.init(ropts.prefix ++ name, opts) },
            }
        }

        pub fn incr(self: *Self) void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| impl.incr(),
            }
        }

        pub fn incrBy(self: *Self, count: V) void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| impl.incrBy(count),
            }
        }

        pub fn write(self: *Self, writer: *std.io.Writer) !void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| return impl.write(writer),
            }
        }

        pub const Impl = struct {
            count: V,
            preamble: []const u8,

            pub fn init(comptime name: []const u8, comptime opts: Opts) Impl {
                return .{
                    .count = 0,
                    .preamble = comptime m.preamble(name, .counter, true, opts.help),
                };
            }

            pub fn incr(self: *Impl) void {
                self.incrBy(1);
            }

            pub fn incrBy(self: *Impl, count: V) void {
                _ = @atomicRmw(V, &self.count, .Add, count, .monotonic);
            }

            pub fn write(self: *const Impl, writer: *std.io.Writer) !void {
                try writer.writeAll(self.preamble);
                const count = @atomicLoad(V, &self.count, .monotonic);
                try m.write(count, writer);
                return writer.writeByte('\n');
            }
        };
    };
}

// Counter with labels
pub fn CounterVec(comptime V: type, comptime L: type) type {
    assertCounterType(V);
    return union(enum) {
        noop: void,
        impl: Impl,

        const Self = @This();

        pub fn init(allocator: Allocator, comptime name: []const u8, comptime opts: Opts, comptime ropts: RegistryOpts) !Self {
            switch (ropts.shouldExclude(name)) {
                true => return .{ .noop = {} },
                false => return .{ .impl = try Impl.init(allocator, ropts.prefix ++ name, opts) },
            }
        }

        pub fn deinit(self: *Self) void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| impl.deinit(),
            }
        }

        pub fn incr(self: *Self, labels: L) !void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| return impl.incr(labels),
            }
        }

        pub fn incrBy(self: *Self, labels: L, count: V) !void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| return impl.incrBy(labels, count),
            }
        }

        pub fn remove(self: *Self, labels: L) void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| impl.remove(labels),
            }
        }

        pub fn write(self: *Self, writer: *std.io.Writer) !void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| return impl.write(writer),
            }
        }

        pub const Impl = struct {
            vec: MetricVec(L),
            preamble: []const u8,
            allocator: Allocator,
            lock: std.Thread.RwLock,
            values: MetricVec(L).HashMap(Value),

            pub const Value = struct {
                count: V,
                attributes: []const u8,
            };

            pub fn init(allocator: Allocator, comptime name: []const u8, comptime opts: Opts) !Impl {
                return .{
                    .lock = .{},
                    .allocator = allocator,
                    .vec = try MetricVec(L).init(name),
                    .values = MetricVec(L).HashMap(Value){},
                    .preamble = comptime m.preamble(name, .counter, false, opts.help),
                };
            }

            pub fn deinit(self: *Impl) void {
                const allocator = self.allocator;

                var it = self.values.iterator();
                while (it.next()) |kv| {
                    MetricVec(L).free(allocator, kv.key_ptr.*);
                    allocator.free(kv.value_ptr.attributes);
                }
                self.values.deinit(allocator);
            }

            pub fn incr(self: *Impl, labels: L) !void {
                return self.incrBy(labels, 1);
            }

            pub fn incrBy(self: *Impl, labels: L, count: V) !void {
                const allocator = self.allocator;

                {
                    self.lock.lockShared();
                    defer self.lock.unlockShared();
                    if (self.values.getPtr(labels)) |existing| {
                        _ = @atomicRmw(V, &existing.count, .Add, count, .monotonic);
                        return;
                    }
                }

                // It's possible that another thread will come in and create this
                // missing label, and we'll check for that, but we'll assume not and
                // do our allocations here, outside of any locks.
                const attributes = try MetricVec(L).buildAttributes(allocator, labels);
                errdefer allocator.free(attributes);

                const owned_labels = try MetricVec(L).dupe(allocator, labels);
                errdefer MetricVec(L).free(allocator, owned_labels);

                const counter = Value{
                    .count = count,
                    .attributes = attributes,
                };

                self.lock.lock();
                defer self.lock.unlock();

                const gop = try self.values.getOrPut(allocator, owned_labels);
                if (gop.found_existing) {
                    MetricVec(L).free(allocator, owned_labels);
                    allocator.free(attributes);
                    gop.value_ptr.count += count;
                    return;
                }

                gop.value_ptr.* = counter;
            }

            pub fn remove(self: *Impl, labels: L) void {
                const kv = blk: {
                    self.lock.lock();
                    defer self.lock.unlock();
                    break :blk self.values.fetchRemove(labels) orelse return;
                };

                const allocator = self.allocator;
                MetricVec(L).free(allocator, kv.key);
                allocator.free(kv.value.attributes);
            }

            pub fn write(self: *Impl, writer: *std.io.Writer) !void {
                try writer.writeAll(self.preamble);

                const name = self.vec.name;

                self.lock.lockShared();
                defer self.lock.unlockShared();

                var it = self.values.iterator();
                while (it.next()) |kv| {
                    try writer.writeAll(name);

                    const value = kv.value_ptr.*;
                    try writer.writeAll(value.attributes);
                    try m.write(value.count, writer);
                    try writer.writeByte('\n');
                }
            }
        };
    };
}

fn assertCounterType(comptime T: type) void {
    switch (@typeInfo(T)) {
        .float => return,
        .int => |int| {
            if (int.signedness == .unsigned) return;
        },
        else => {},
    }
    @compileError("Counter metric must be an unsigned integer or a float, got: " ++ @typeName(T));
}

const t = @import("t.zig");
test "Counter: noop incr/incrBy" {
    // these should just not crash
    var c = Counter(u32){ .noop = {} };
    c.incr();
    c.incrBy(10);

    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();
    try c.write(&writer.writer);
    try t.expectEqual(0, writer.writer.end);
}

test "Counter: incr/incrBy" {
    var c = Counter(u32).init("t1", .{}, .{});
    c.incr();
    try t.expectEqual(1, c.impl.count);
    c.incrBy(10);
    try t.expectEqual(11, c.impl.count);
}

test "Counter: write" {
    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();

    var c = Counter(u32).init("metric_cnt_1_x", .{}, .{ .exclude = &.{"t_ex"} });

    {
        c.incr();
        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString("# TYPE metric_cnt_1_x counter\nmetric_cnt_1_x 1\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        c.incrBy(399929123);
        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString("# TYPE metric_cnt_1_x counter\nmetric_cnt_1_x 399929124\n", buf);
    }
}

test "Counter: exclude" {
    var c = Counter(u32).init("t_ex", .{}, .{ .exclude = &.{"t_ex"} });
    c.incr();

    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();
    try c.write(&writer.writer);
    const buf = writer.writer.buffered();
    try t.expectEqual(0, buf.len);
}

test "Counter: prefix" {
    var c = Counter(u32).init("t1_p", .{}, .{ .prefix = "hello_" });
    c.incr();

    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();
    try c.write(&writer.writer);
    const buf = writer.writer.buffered();
    try t.expectString("# TYPE hello_t1_p counter\nhello_t1_p 1\n", buf);
}

test "Counter: float incr/incrBy" {
    var c = Counter(f32).init("t1", .{}, .{});
    c.incr();
    try t.expectEqual(1, c.impl.count);
    c.incrBy(12.1);
    try t.expectEqual(13.1, c.impl.count);
}

test "Counter: float write" {
    var writer: std.io.Writer.Allocating = .init(
        t.allocator,
    );
    defer writer.deinit();

    var c = Counter(f64).init("metric_cnt_2_x", .{}, .{});

    {
        c.incr();
        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString("# TYPE metric_cnt_2_x counter\nmetric_cnt_2_x 1\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        c.incrBy(123.991);
        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString("# TYPE metric_cnt_2_x counter\nmetric_cnt_2_x 124.991\n", buf);
    }
}

test "CounterVec: noop incr/incrBy" {
    // these should just not crash
    var c = CounterVec(u32, struct { id: u32 }){ .noop = {} };
    defer c.deinit();
    try c.incr(.{ .id = 3 });
    try c.incrBy(.{ .id = 10 }, 20);

    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();
    try c.write(&writer.writer);
    const buf = writer.writer.buffered();
    try t.expectEqual(0, buf.len);
}

test "CounterVec: incr/incrBy + write" {
    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();

    const preamble = "# HELP counter_vec_1 h1\n# TYPE counter_vec_1 counter\n";

    // these should just not crash
    var c = try CounterVec(u64, struct { id: []const u8 }).init(t.allocator, "counter_vec_1", .{ .help = "h1" }, .{});
    defer c.deinit();

    {
        try c.incr(.{ .id = "a" });
        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "counter_vec_1{id=\"a\"} 1\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        try c.incr(.{ .id = "b" });
        try c.incr(.{ .id = "a" });
        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "counter_vec_1{id=\"b\"} 1\ncounter_vec_1{id=\"a\"} 2\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        try c.incrBy(.{ .id = "a" }, 20);
        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "counter_vec_1{id=\"b\"} 1\ncounter_vec_1{id=\"a\"} 22\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        c.remove(.{ .id = "not_found" });
        c.remove(.{ .id = "a" });
        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "counter_vec_1{id=\"b\"} 1\n", buf);
    }
}

test "CounterVec: float incr/incrBy + write" {
    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();

    const preamble = "# HELP counter_vec_xx_2 h1\n# TYPE counter_vec_xx_2 counter\n";

    // these should just not crash
    var c = try CounterVec(f32, struct { id: []const u8 }).init(t.allocator, "counter_vec_xx_2", .{ .help = "h1" }, .{});
    defer c.deinit();

    {
        try c.incr(.{ .id = "a" });
        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "counter_vec_xx_2{id=\"a\"} 1\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        try c.incr(.{ .id = "b" });
        try c.incr(.{ .id = "a" });
        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "counter_vec_xx_2{id=\"b\"} 1\ncounter_vec_xx_2{id=\"a\"} 2\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        try c.incrBy(.{ .id = "a" }, 0.25);
        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "counter_vec_xx_2{id=\"b\"} 1\ncounter_vec_xx_2{id=\"a\"} 2.25\n", buf);
    }
}

test "Counter: concurrent create" {
    const EquitiesCounter = CounterVec(u64, struct {
        symbol: []const u8,
        type: []const u8,
    });

    const preamble = "# TYPE counter_vec_concurrent counter\n";

    const run = struct {
        fn run(c: *EquitiesCounter) void {
            c.incrBy(.{ .symbol = "AAPL", .type = "trade" }, 1) catch {};
        }
    }.run;

    for (1..100) |_| {
        var writer: std.io.Writer.Allocating = .init(t.allocator);
        defer writer.deinit();

        var c = try EquitiesCounter.init(t.allocator, "counter_vec_concurrent", .{}, .{});
        defer c.deinit();

        var th1 = try std.Thread.spawn(.{}, run, .{&c});
        var th2 = try std.Thread.spawn(.{}, run, .{&c});
        th2.join();
        th1.join();

        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "counter_vec_concurrent{symbol=\"AAPL\",type=\"trade\"} 2\n", buf);
    }
}
