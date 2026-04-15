const std = @import("std");
const Allocator = std.mem.Allocator;

const m = @import("metric.zig");
const Metric = m.Metric;
const MetricVec = m.MetricVec;

const RegistryOpts = @import("registry.zig").Opts;

const Opts = struct {
    help: ?[]const u8 = null,
};

pub fn Histogram(comptime V: type, comptime upper_bounds: []const V) type {
    assertHistogramType(V);
    assertUpperBounds(upper_bounds);

    return union(enum) {
        noop: void,
        impl: Impl,

        const Self = @This();

        pub fn init(comptime name: []const u8, comptime opts: Opts, comptime ropts: RegistryOpts) Self {
            switch (ropts.shouldExclude(name)) {
                true => return .{ .noop = {} },
                false => return .{ .impl = comptime Impl.init(ropts.prefix ++ name, opts) },
            }
        }

        pub fn observe(self: *Self, value: V) void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| impl.observe(value),
            }
        }

        pub fn write(self: *Self, writer: *std.io.Writer) !void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| return impl.write(writer),
            }
        }

        pub const Impl = struct {
            sum: V,
            count: usize,
            preamble: []const u8,
            buckets: [upper_bounds.len]V,
            output_sum_prefix: []const u8,
            output_count_prefix: []const u8,
            output_bucket_prefixes: [upper_bounds.len][]const u8,
            output_bucket_inf_prefix: []const u8,

            pub fn init(comptime name: []const u8, comptime opts: Opts) Impl {
                comptime {
                    const output_sum_prefix = std.fmt.comptimePrint("\n{s}_sum ", .{name});
                    const output_count_prefix = std.fmt.comptimePrint("\n{s}_count ", .{name});

                    const output_bucket_inf_prefix = std.fmt.comptimePrint("{s}_bucket{{le=\"+Inf\"}} ", .{name});
                    var output_bucket_prefixes: [upper_bounds.len][]const u8 = undefined;

                    for (upper_bounds, 0..) |upper, i| {
                        output_bucket_prefixes[i] = std.fmt.comptimePrint("{s}_bucket{{le=\"{d}\"}} ", .{ name, upper });
                    }

                    return .{
                        .sum = 0,
                        .count = 0,
                        .preamble = m.preamble(name, .histogram, false, opts.help),
                        .output_sum_prefix = output_sum_prefix,
                        .output_count_prefix = output_count_prefix,
                        .output_bucket_prefixes = output_bucket_prefixes,
                        .output_bucket_inf_prefix = output_bucket_inf_prefix,
                        .buckets = std.mem.zeroes([upper_bounds.len]V),
                    };
                }
            }

            pub fn observe(self: *Impl, value: V) void {
                _ = @atomicRmw(usize, &self.count, .Add, 1, .monotonic);
                _ = @atomicRmw(V, &self.sum, .Add, value, .monotonic);

                const idx = blk: {
                    for (upper_bounds, 0..) |upper, i| {
                        if (value < upper) {
                            break :blk i;
                        }
                    }
                    // this is our implicit bucket to +Inf. Implicit because the count
                    // and sum, updated above, will contain this entry
                    return;
                };

                _ = @atomicRmw(V, &self.buckets[idx], .Add, 1, .monotonic);
            }

            pub fn write(self: *Impl, writer: *std.io.Writer) !void {
                try writer.writeAll(self.preamble);

                var sum: V = 0;
                for (self.output_bucket_prefixes, 0..) |prefix, i| {
                    sum += @atomicRmw(V, &self.buckets[i], .Xchg, 0, .monotonic);
                    try writer.writeAll(prefix);
                    try m.write(sum, writer);
                    try writer.writeByte('\n');
                }

                const total_count = @atomicRmw(usize, &self.count, .Xchg, 0, .monotonic);
                {
                    // write +Inf
                    try writer.writeAll(self.output_bucket_inf_prefix);
                    try writer.printInt(total_count, 10, .lower, .{});
                }

                {
                    //write sum
                    // this includes a leading newline, hence we didn't need to write
                    // it after our output_bucket_inf_prefix
                    try writer.writeAll(self.output_sum_prefix);
                    try m.write(@atomicRmw(V, &self.sum, .Xchg, 0, .monotonic), writer);
                }

                {
                    //write count
                    // this includes a leading newline, hence we didn't need to write
                    // it after our output_sum_prefix
                    try writer.writeAll(self.output_count_prefix);
                    try writer.printInt(total_count, 10, .lower, .{});
                    try writer.writeByte('\n');
                }
            }
        };
    };
}

pub fn HistogramVec(comptime V: type, comptime L: type, comptime upper_bounds: []const V) type {
    assertHistogramType(V);
    assertUpperBounds(upper_bounds);

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

        pub fn observe(self: *Self, labels: L, value: V) !void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| return impl.observe(labels, value),
            }
        }

        pub fn write(self: *Self, writer: *std.io.Writer) !void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| return impl.write(writer),
            }
        }

        // could get the allocator from impl.allocator, but taking it as a parameter
        // makes the API the same between Histogram and HistogramVec
        pub fn deinit(self: *Self) void {
            switch (self.*) {
                .noop => {},
                .impl => |*impl| impl.deinit(),
            }
        }

        pub const Impl = struct {
            vec: MetricVec(L),
            preamble: []const u8,
            allocator: Allocator,
            lock: std.Thread.RwLock,
            values: MetricVec(L).HashMap(Value),
            output_sum_prefix: []const u8,
            output_count_prefix: []const u8,
            output_bucket_prefixes: [upper_bounds.len][]const u8,
            output_bucket_inf_prefix: []const u8,

            const Value = struct {
                sum: V,
                count: usize,
                mutex: std.Thread.Mutex,
                buckets: [upper_bounds.len]V,
                // this gets glued to our output_bucket_prefixes
                attributes: []const u8,

                fn observe(self: *Value, value: V, idx: ?usize) void {
                    self.mutex.lock();
                    defer self.mutex.unlock();
                    self.observeLocked(value, idx);
                }

                fn observeLocked(self: *Value, value: V, idx: ?usize) void {
                    self.sum += value;
                    self.count += 1;
                    if (idx) |idx_| {
                        self.buckets[idx_] += 1;
                    }
                }

                fn getIndex(value: V) ?usize {
                    for (upper_bounds, 0..) |upper, i| {
                        if (value < upper) {
                            return i;
                        }
                    }
                    return null;
                }
            };

            pub fn init(allocator: Allocator, comptime name: []const u8, comptime opts: Opts) !Impl {
                const vec = try MetricVec(L).init(name);

                const output_sum_prefix = try std.fmt.allocPrint(allocator, "\n{s}_sum", .{name});
                errdefer allocator.free(output_sum_prefix);

                const output_count_prefix = try std.fmt.allocPrint(allocator, "\n{s}_count", .{name});
                errdefer allocator.free(output_count_prefix);

                const output_bucket_inf_prefix = try std.fmt.allocPrint(allocator, "{s}_bucket{{le=\"+Inf\",", .{name});
                errdefer allocator.free(output_bucket_inf_prefix);

                var output_bucket_prefixes: [upper_bounds.len][]const u8 = undefined;
                var initialized: usize = 0;
                errdefer {
                    for (0..initialized) |i| {
                        allocator.free(output_bucket_prefixes[i]);
                    }
                }

                for (upper_bounds, 0..) |upper, i| {
                    output_bucket_prefixes[i] = try std.fmt.allocPrint(allocator, "{s}_bucket{{le=\"{d}\",", .{ name, upper });
                    initialized += 1;
                }

                return .{
                    .vec = vec,
                    .lock = .{},
                    .allocator = allocator,
                    .values = MetricVec(L).HashMap(Value){},
                    .output_sum_prefix = output_sum_prefix,
                    .output_count_prefix = output_count_prefix,
                    .output_bucket_prefixes = output_bucket_prefixes,
                    .output_bucket_inf_prefix = output_bucket_inf_prefix,
                    .preamble = comptime m.preamble(name, .histogram, false, opts.help),
                };
            }

            pub fn deinit(self: *Impl) void {
                const allocator = self.allocator;
                allocator.free(self.output_sum_prefix);
                allocator.free(self.output_count_prefix);
                allocator.free(self.output_bucket_inf_prefix);
                for (self.output_bucket_prefixes) |obf| {
                    allocator.free(obf);
                }

                var it = self.values.iterator();
                while (it.next()) |kv| {
                    MetricVec(L).free(allocator, kv.key_ptr.*);
                    allocator.free(kv.value_ptr.attributes);
                }
                self.values.deinit(allocator);
            }

            pub fn observe(self: *Impl, labels: L, value: V) !void {
                const allocator = self.allocator;

                // do this outside any lock
                const idx: ?usize = blk: {
                    for (upper_bounds, 0..) |upper, i| {
                        if (value < upper) {
                            break :blk i;
                        }
                    }
                    // this is our implicit bucket to +Inf. Implicit because the count
                    // and sum, updated above, will contain this entry
                    break :blk null;
                };

                {
                    self.lock.lockShared();
                    defer self.lock.unlockShared();
                    if (self.values.getPtr(labels)) |existing| {
                        existing.observe(value, idx);
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

                const histogram = Value{
                    .sum = 0,
                    .count = 0,
                    .mutex = .{},
                    .attributes = attributes,
                    .buckets = std.mem.zeroes([upper_bounds.len]V),
                };

                self.lock.lock();
                defer self.lock.unlock();

                const gop = try self.values.getOrPut(allocator, owned_labels);
                if (gop.found_existing) {
                    MetricVec(L).free(allocator, owned_labels);
                    allocator.free(attributes);
                } else {
                    gop.value_ptr.* = histogram;
                }

                // since we've taking out a write lock out the entire histogram
                // we can observe this value without taking an inner value lock.
                gop.value_ptr.observeLocked(value, idx);
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

                const output_sum_prefix = self.output_sum_prefix;
                const output_count_prefix = self.output_count_prefix;
                const output_bucket_inf_prefix = self.output_bucket_inf_prefix;

                self.lock.lockShared();
                defer self.lock.unlockShared();

                var it = self.values.iterator();
                while (it.next()) |kv| {
                    var value = kv.value_ptr;
                    var bucket_counts: [upper_bounds.len]V = undefined;

                    // copy our sum/count/bucket_counts out of Value into local variables
                    // to minimize our lock duration
                    value.mutex.lock();
                    var buckets = &value.buckets;
                    const value_sum = value.sum;
                    const value_count = value.count;
                    for (buckets, 0..) |bucket_count, i| {
                        bucket_counts[i] = bucket_count;
                        buckets[i] = 0;
                    }
                    value.sum = 0;
                    value.count = 0;
                    value.mutex.unlock();

                    const attributes = value.attributes;
                    // attributes contains the opening and closing braces: {k="v"}
                    // but for the bucket values, we're appending the attribute to the
                    // pre-generated prefix, which already contains "{le="$bucket".
                    // So we strip out the leading "{" from our attribute so that we can
                    // glue is to our pre-generated prefix.
                    const append_attributes = attributes[1..];

                    var sum: V = 0;
                    for (self.output_bucket_prefixes, bucket_counts) |prefix, bucket_count| {
                        sum += bucket_count;
                        try writer.writeAll(prefix);
                        try writer.writeAll(append_attributes);
                        try m.write(sum, writer);
                        try writer.writeByte('\n');
                    }

                    {
                        // write +Inf
                        try writer.writeAll(output_bucket_inf_prefix);
                        try writer.writeAll(append_attributes);
                        try writer.printInt(value_count, 10, .lower, .{});
                    }

                    {
                        //write sum
                        // this includes a leading newline, hence we didn't need to write
                        // it after our output_bucket_inf_prefix
                        try writer.writeAll(output_sum_prefix);
                        try writer.writeAll(attributes);
                        try m.write(value_sum, writer);
                    }

                    {
                        //write count
                        // this includes a leading newline, hence we didn't need to write
                        // it after our output_sum_prefix
                        try writer.writeAll(output_count_prefix);
                        try writer.writeAll(attributes);
                        try writer.printInt(value_count, 10, .lower, .{});
                        try writer.writeByte('\n');
                    }
                }
            }
        };
    };
}

fn assertHistogramType(comptime T: type) void {
    switch (@typeInfo(T)) {
        .float => return,
        .int => |int| {
            if (int.signedness == .unsigned) return;
        },
        else => {},
    }
    @compileError("Histogram metric must be an unsigned integer or a float, got: " ++ @typeName(T));
}

fn assertUpperBounds(upper_bounds: anytype) void {
    if (upper_bounds.len == 0) {
        @compileError("Histogram upper bound cannot be empty");
    }
    var last = upper_bounds[0];
    for (upper_bounds[1..]) |value| {
        if (value < last) {
            @compileError("Histogram upper bounds must be in ascending order");
        }
        last = value;
    }
}

const t = @import("t.zig");
test "Histogram: noop " {
    // these should just not crash
    var h = Histogram(u32, &.{0}){ .noop = {} };
    h.observe(2);

    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();
    try h.write(&writer.writer);
    const buf = writer.writer.buffered();
    try t.expectEqual(0, buf.len);
}

test "Histogram: simple" {
    var h = Histogram(f64, &.{ 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10 }).init("hst_1", .{}, .{});

    var i: f64 = 0.001;
    for (0..1000) |_| {
        i = i + i / 100;
        h.observe(i);
    }

    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();

    {
        try h.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(
            \\# TYPE hst_1 histogram
            \\hst_1_bucket{le="0.005"} 161
            \\hst_1_bucket{le="0.01"} 231
            \\hst_1_bucket{le="0.025"} 323
            \\hst_1_bucket{le="0.05"} 393
            \\hst_1_bucket{le="0.1"} 462
            \\hst_1_bucket{le="0.25"} 554
            \\hst_1_bucket{le="0.5"} 624
            \\hst_1_bucket{le="1"} 694
            \\hst_1_bucket{le="2.5"} 786
            \\hst_1_bucket{le="5"} 855
            \\hst_1_bucket{le="10"} 925
            \\hst_1_bucket{le="+Inf"} 1000
            \\hst_1_sum 2116.7737194191777
            \\hst_1_count 1000
            \\
        , buf);
    }

    {
        writer.clearRetainingCapacity();
        h.observe(2.8);
        try h.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(
            \\# TYPE hst_1 histogram
            \\hst_1_bucket{le="0.005"} 0
            \\hst_1_bucket{le="0.01"} 0
            \\hst_1_bucket{le="0.025"} 0
            \\hst_1_bucket{le="0.05"} 0
            \\hst_1_bucket{le="0.1"} 0
            \\hst_1_bucket{le="0.25"} 0
            \\hst_1_bucket{le="0.5"} 0
            \\hst_1_bucket{le="1"} 0
            \\hst_1_bucket{le="2.5"} 0
            \\hst_1_bucket{le="5"} 1
            \\hst_1_bucket{le="10"} 1
            \\hst_1_bucket{le="+Inf"} 1
            \\hst_1_sum 2.8
            \\hst_1_count 1
            \\
        , buf);
    }
}

test "HistogramVec: noop " {
    // these should just not crash
    var h = HistogramVec(u32, struct { status: u16 }, &.{0}){ .noop = {} };
    defer h.deinit();
    try h.observe(.{ .status = 200 }, 2);

    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();
    try h.write(&writer.writer);
    const buf = writer.writer.buffered();
    try t.expectEqual(0, buf.len);
}

test "HistogramVec" {
    var h = try HistogramVec(f64, struct { status: u16 }, &.{ 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10 }).init(t.allocator, "hst_1", .{}, .{});
    defer h.deinit();

    var i: f64 = 0.001;
    for (0..1000) |_| {
        i = i + i / 100;
        try h.observe(.{ .status = 200 }, i);
    }

    i = 0.02;
    for (0..100) |_| {
        i = i + i / 50;
        try h.observe(.{ .status = 400 }, i);
    }

    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();

    {
        try h.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(
            \\# TYPE hst_1 histogram
            \\hst_1_bucket{le="0.005",status="200"} 161
            \\hst_1_bucket{le="0.01",status="200"} 231
            \\hst_1_bucket{le="0.025",status="200"} 323
            \\hst_1_bucket{le="0.05",status="200"} 393
            \\hst_1_bucket{le="0.1",status="200"} 462
            \\hst_1_bucket{le="0.25",status="200"} 554
            \\hst_1_bucket{le="0.5",status="200"} 624
            \\hst_1_bucket{le="1",status="200"} 694
            \\hst_1_bucket{le="2.5",status="200"} 786
            \\hst_1_bucket{le="5",status="200"} 855
            \\hst_1_bucket{le="10",status="200"} 925
            \\hst_1_bucket{le="+Inf",status="200"} 1000
            \\hst_1_sum{status="200"} 2116.7737194191777
            \\hst_1_count{status="200"} 1000
            \\hst_1_bucket{le="0.005",status="400"} 0
            \\hst_1_bucket{le="0.01",status="400"} 0
            \\hst_1_bucket{le="0.025",status="400"} 11
            \\hst_1_bucket{le="0.05",status="400"} 46
            \\hst_1_bucket{le="0.1",status="400"} 81
            \\hst_1_bucket{le="0.25",status="400"} 100
            \\hst_1_bucket{le="0.5",status="400"} 100
            \\hst_1_bucket{le="1",status="400"} 100
            \\hst_1_bucket{le="2.5",status="400"} 100
            \\hst_1_bucket{le="5",status="400"} 100
            \\hst_1_bucket{le="10",status="400"} 100
            \\hst_1_bucket{le="+Inf",status="400"} 100
            \\hst_1_sum{status="400"} 6.369539040617386
            \\hst_1_count{status="400"} 100
            \\
        , buf);
    }

    {
        try h.observe(.{ .status = 200 }, 9);
        writer.clearRetainingCapacity();
        try h.write(&writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(
            \\# TYPE hst_1 histogram
            \\hst_1_bucket{le="0.005",status="200"} 0
            \\hst_1_bucket{le="0.01",status="200"} 0
            \\hst_1_bucket{le="0.025",status="200"} 0
            \\hst_1_bucket{le="0.05",status="200"} 0
            \\hst_1_bucket{le="0.1",status="200"} 0
            \\hst_1_bucket{le="0.25",status="200"} 0
            \\hst_1_bucket{le="0.5",status="200"} 0
            \\hst_1_bucket{le="1",status="200"} 0
            \\hst_1_bucket{le="2.5",status="200"} 0
            \\hst_1_bucket{le="5",status="200"} 0
            \\hst_1_bucket{le="10",status="200"} 1
            \\hst_1_bucket{le="+Inf",status="200"} 1
            \\hst_1_sum{status="200"} 9
            \\hst_1_count{status="200"} 1
            \\hst_1_bucket{le="0.005",status="400"} 0
            \\hst_1_bucket{le="0.01",status="400"} 0
            \\hst_1_bucket{le="0.025",status="400"} 0
            \\hst_1_bucket{le="0.05",status="400"} 0
            \\hst_1_bucket{le="0.1",status="400"} 0
            \\hst_1_bucket{le="0.25",status="400"} 0
            \\hst_1_bucket{le="0.5",status="400"} 0
            \\hst_1_bucket{le="1",status="400"} 0
            \\hst_1_bucket{le="2.5",status="400"} 0
            \\hst_1_bucket{le="5",status="400"} 0
            \\hst_1_bucket{le="10",status="400"} 0
            \\hst_1_bucket{le="+Inf",status="400"} 0
            \\hst_1_sum{status="400"} 0
            \\hst_1_count{status="400"} 0
            \\
        , buf);
    }
}
