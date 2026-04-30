const std = @import("std");
const Allocator = std.mem.Allocator;

const m = @import("metric.zig");
const Metric = m.Metric;
const MetricVec = m.MetricVec;

const RegistryOpts = @import("registry.zig").Opts;

const Opts = struct {
    help: ?[]const u8 = null,
};

pub fn Gauge(comptime V: type) type {
    assertGaugeType(V);
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

        pub fn set(self: *Self, value: V) void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| impl.set(value),
            }
        }

        pub fn incrBy(self: *Self, value: V) void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| impl.incrBy(value),
            }
        }

        pub fn write(self: *Self, writer: *std.io.Writer) !void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| return impl.write(writer),
            }
        }

        pub const Impl = struct {
            value: V,
            preamble: []const u8,

            pub fn init(comptime name: []const u8, comptime opts: Opts) Impl {
                return .{
                    .value = 0,
                    .preamble = comptime m.preamble(name, .gauge, true, opts.help),
                };
            }

            pub fn incr(self: *Impl) void {
                self.incrBy(1);
            }

            pub fn incrBy(self: *Impl, value: V) void {
                _ = @atomicRmw(V, &self.value, .Add, value, .monotonic);
            }

            pub fn set(self: *Impl, value: V) void {
                @atomicStore(V, &self.value, value, .monotonic);
            }

            pub fn write(self: *const Impl, writer: *std.io.Writer) !void {
                try writer.writeAll(self.preamble);
                try m.write(@atomicLoad(V, &self.value, .monotonic), writer);
                return writer.writeByte('\n');
            }
        };
    };
}

// Gauge with labels
pub fn GaugeVec(comptime V: type, comptime L: type) type {
    assertGaugeType(V);
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

        pub fn incrBy(self: *Self, labels: L, value: V) !void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| return impl.incrBy(labels, value),
            }
        }

        pub fn set(self: *Self, labels: L, value: V) !void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| return impl.set(labels, value),
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

            const Value = struct {
                value: V,
                attributes: []const u8,
            };

            pub fn init(allocator: Allocator, comptime name: []const u8, comptime opts: Opts) !Impl {
                return .{
                    .lock = .{},
                    .allocator = allocator,
                    .vec = try MetricVec(L).init(name),
                    .values = MetricVec(L).HashMap(Value){},
                    .preamble = comptime m.preamble(name, .gauge, false, opts.help),
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

            pub fn incrBy(self: *Impl, labels: L, value: V) !void {
                return self.withValue(labels, value, atomicIncrCallback, incrCallback);
            }

            fn atomicIncrCallback(value: V, entry: *Value) void {
                entry.value += value;
            }

            fn incrCallback(value: V, entry: *Value) void {
                entry.value += value;
            }

            pub fn set(self: *Impl, labels: L, value: V) !void {
                return self.withValue(labels, value, atomicSetCallback, setCallback);
            }

            fn setCallback(value: V, entry: *Value) void {
                entry.value = value;
            }

            fn atomicSetCallback(value: V, entry: *Value) void {
                entry.value = value;
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
                    try m.write(value.value, writer);
                    try writer.writeByte('\n');
                }
            }

            // value is only used if this is the first time we've seen this label.
            // if we've already seen this label, and thus have an existing entry in
            // our map, then fa() or f() is executed. fa() is called when an atomic
            // update is necessary, and f() is called when an atomic update isn't (
            // because a mutex is being held).
            fn withValue(self: *Impl, labels: L, value: V, comptime fa: fn (V, *Value) void, comptime f: fn (V, *Value) void) !void {
                const allocator = self.allocator;

                {
                    self.lock.lockShared();
                    defer self.lock.unlockShared();
                    if (self.values.getPtr(labels)) |existing| {
                        fa(value, existing);
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

                const gauge = Value{
                    .value = value,
                    .attributes = attributes,
                };

                self.lock.lock();
                defer self.lock.unlock();

                const gop = try self.values.getOrPut(allocator, owned_labels);
                if (gop.found_existing) {
                    MetricVec(L).free(allocator, owned_labels);
                    allocator.free(attributes);
                    f(value, gop.value_ptr);
                    return;
                }
                gop.value_ptr.* = gauge;
            }
        };
    };
}

fn assertGaugeType(comptime T: type) void {
    switch (@typeInfo(T)) {
        .float, .int => return,
        else => {},
    }
    @compileError("Gauge metric must be an integer or float, got: " ++ @typeName(T));
}

const t = @import("t.zig");
test "Gauge: noop incr/incrBy/set" {
    // these should just not crash
    var c = Gauge(u32){ .noop = {} };
    c.incr();
    c.incrBy(10);
    c.set(100);

    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();
    try c.write(&writer.writer);
    const buf = writer.writer.buffered();
    try t.expectEqual(0, buf.len);
}

test "Gauge: incr/incrBy/set" {
    var g = Gauge(i32).init("t1", .{}, .{});

    g.incr();
    try t.expectEqual(1, g.impl.value);

    g.incrBy(10);
    try t.expectEqual(11, g.impl.value);

    g.incrBy(-2);
    try t.expectEqual(9, g.impl.value);

    g.set(-10);
    try t.expectEqual(-10, g.impl.value);
}

test "Gauge: write" {
    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();

    var g = Gauge(i32).init("metric_grp_1_x", .{}, .{});

    {
        g.incr();
        try g.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString("# TYPE metric_grp_1_x gauge\nmetric_grp_1_x 1\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        g.incrBy(399929123);
        try g.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString("# TYPE metric_grp_1_x gauge\nmetric_grp_1_x 399929124\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        g.set(-329);
        try g.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString("# TYPE metric_grp_1_x gauge\nmetric_grp_1_x -329\n", buf);
    }
}

test "Gauge: float incr/incrBy/set" {
    var c = Gauge(f32).init("t1", .{}, .{});
    c.incr();
    try t.expectEqual(1, c.impl.value);
    c.incrBy(-3.9);
    try t.expectEqual(-2.9, c.impl.value);
    c.set(99.9);
    try t.expectEqual(99.9, c.impl.value);
}

test "Gauge: float write" {
    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();

    var c = Gauge(f64).init("metric_g_2_x", .{}, .{});

    {
        c.incr();
        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString("# TYPE metric_g_2_x gauge\nmetric_g_2_x 1\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        c.incrBy(-9.2);
        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString("# TYPE metric_g_2_x gauge\nmetric_g_2_x -8.2\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        c.set(8.888);
        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString("# TYPE metric_g_2_x gauge\nmetric_g_2_x 8.888\n", buf);
    }
}

test "GaugeVec: noop incr/incrBy/set" {
    // these should just not crash
    var g = GaugeVec(u32, struct { id: u32 }){ .noop = {} };
    defer g.deinit();
    try g.incr(.{ .id = 3 });
    try g.incrBy(.{ .id = 10 }, 20);
    try g.set(.{ .id = 3 }, 11);

    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();
    try g.write(&writer.writer);
    const buf = writer.writer.buffered();
    try t.expectEqual(0, buf.len);
}

test "GaugeVec: incr/incrBy/set + write" {
    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();

    const preamble = "# HELP gauge_vec_1 h1\n# TYPE gauge_vec_1 gauge\n";

    // these should just not crash
    var g = try GaugeVec(i64, struct { id: []const u8 }).init(t.allocator, "gauge_vec_1", .{ .help = "h1" }, .{});
    defer g.deinit();

    {
        try g.incr(.{ .id = "a" });
        try g.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "gauge_vec_1{id=\"a\"} 1\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        try g.incr(.{ .id = "b" });
        try g.incr(.{ .id = "a" });
        try g.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "gauge_vec_1{id=\"b\"} 1\ngauge_vec_1{id=\"a\"} 2\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        try g.incrBy(.{ .id = "a" }, 20);
        try g.set(.{ .id = "c" }, 5);
        try g.set(.{ .id = "b" }, -33);
        try g.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "gauge_vec_1{id=\"b\"} -33\ngauge_vec_1{id=\"a\"} 22\ngauge_vec_1{id=\"c\"} 5\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        g.remove(.{ .id = "not_found" });
        g.remove(.{ .id = "a" });
        try g.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "gauge_vec_1{id=\"b\"} -33\ngauge_vec_1{id=\"c\"} 5\n", buf);
    }
}

test "GaugeVec: float incr/incrBy/set + write" {
    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();

    const preamble = "# HELP gauge_vec_xx_2 h1\n# TYPE gauge_vec_xx_2 gauge\n";

    // these should just not crash
    var g = try GaugeVec(f64, struct { id: []const u8 }).init(t.allocator, "gauge_vec_xx_2", .{ .help = "h1" }, .{});
    defer g.deinit();

    {
        try g.incr(.{ .id = "a" });
        try g.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "gauge_vec_xx_2{id=\"a\"} 1\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        try g.incr(.{ .id = "b" });
        try g.incr(.{ .id = "a" });
        try g.set(.{ .id = "c\nc" }, 0.011);
        try g.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "gauge_vec_xx_2{id=\"b\"} 1\ngauge_vec_xx_2{id=\"a\"} 2\ngauge_vec_xx_2{id=\"c\\nc\"} 0.011\n", buf);
    }

    {
        writer.clearRetainingCapacity();
        try g.incrBy(.{ .id = "a" }, 0.25);
        g.remove(.{ .id = "c\nc" });
        try g.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "gauge_vec_xx_2{id=\"b\"} 1\ngauge_vec_xx_2{id=\"a\"} 2.25\n", buf);
    }
}

test "Gauge: concurrent create" {
    const EquitiesGauge = GaugeVec(u64, struct {
        symbol: []const u8,
        type: []const u8,
    });

    const preamble = "# TYPE gauge_vec_concurrent gauge\n";

    const run = struct {
        fn run(c: *EquitiesGauge) void {
            c.set(.{ .symbol = "AAPL", .type = "trade" }, 1) catch {};
        }
    }.run;

    for (0..100) |_| {
        var writer: std.io.Writer.Allocating = .init(t.allocator);
        defer writer.deinit();

        var c = try EquitiesGauge.init(t.allocator, "gauge_vec_concurrent", .{}, .{});
        defer c.deinit();

        var th1 = try std.Thread.spawn(.{}, run, .{&c});
        var th2 = try std.Thread.spawn(.{}, run, .{&c});
        th2.join();
        th1.join();

        try c.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(preamble ++ "gauge_vec_concurrent{symbol=\"AAPL\",type=\"trade\"} 1\n", buf);
    }
}
