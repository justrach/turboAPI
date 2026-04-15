const std = @import("std");

const counter = @import("counter.zig");
pub const Counter = counter.Counter;
pub const CounterVec = counter.CounterVec;

const gauge = @import("gauge.zig");
pub const Gauge = gauge.Gauge;
pub const GaugeVec = gauge.GaugeVec;

const histogram = @import("histogram.zig");
pub const Histogram = histogram.Histogram;
pub const HistogramVec = histogram.HistogramVec;

pub const RegistryOpts = @import("registry.zig").Opts;

// This allows a library developer to safely use a library-wide metrics
// instance by defaulting all metrics to "noop" variants. Library developers
// can then expose a function to the main application, say:
//   try thelib.initializeMetrics(allocator)
// which then initializes the metrics instance to real implementations.
// Whether or not the application calls in initializeMetrics, the library
// can safely use the metrics instance, sine this function initialized it to
// noop.
pub fn initializeNoop(comptime T: type) T {
    switch (@typeInfo(T)) {
        .@"struct" => |struct_info| {
            var m: T = undefined;
            inline for (struct_info.fields) |field| {
                switch (@typeInfo(field.type)) {
                    .@"union" => @field(m, field.name) = .{ .noop = {} },
                    else => {
                        if (field.default_value_ptr) |default_value_ptr| {
                            const default_value = @as(*align(1) const field.type, @ptrCast(default_value_ptr)).*;
                            @field(m, field.name) = default_value;
                        }
                    },
                }
            }
            return m;
        },
        else => @compileError("initializeNoop expects a struct"),
    }
}

pub fn write(metrics: anytype, writer: *std.io.Writer) !void {
    const S = @typeInfo(@TypeOf(metrics)).pointer.child;
    const fields = @typeInfo(S).@"struct".fields;

    inline for (fields) |f| {
        switch (@typeInfo(f.type)) {
            .@"union" => try @constCast(&@field(metrics, f.name)).write(writer),
            else => {},
        }
    }
}

test {
    std.testing.refAllDecls(@This());
}

const t = @import("t.zig");
test "initializeNoop + write" {
    const x = initializeNoop(struct {
        status: u16 = 33,
        hits: CounterVec(u32, struct { status: u16 }),
        active: Gauge(u64),
        latency: Histogram(u32, &.{ 0, 2 }),
    });

    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();
    try write(&x, &writer.writer);
    const buf = writer.writer.buffered();
    try t.expectEqual(0, buf.len);
}

test "metrics: write" {
    const M = struct {
        hits: Hits,
        active: Gauge(u64),
        timing: Timing,

        const Hits = CounterVec(u32, struct { status: u16 });
        const Timing = HistogramVec(u32, struct { path: []const u8 }, &.{ 5, 10, 25, 50, 100, 250, 500, 1000 });
    };

    var m = M{ .active = Gauge(u64).init("active", .{}, .{}), .hits = try M.Hits.init(t.allocator, "hits", .{}, .{}), .timing = try M.Timing.init(t.allocator, "timing", .{ .help = "the timing" }, .{ .prefix = "x_" }) };
    defer m.hits.deinit();
    defer m.timing.deinit();

    var writer: std.io.Writer.Allocating = .init(t.allocator);
    defer writer.deinit();

    m.active.set(919);
    try m.hits.incr(.{ .status = 199 });

    {
        try write(&m, &writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(
            \\# TYPE hits counter
            \\hits{status="199"} 1
            \\# TYPE active gauge
            \\active 919
            \\# HELP x_timing the timing
            \\# TYPE x_timing histogram
            \\
        , buf);
    }

    m.active.set(32);
    try m.hits.incr(.{ .status = 199 });
    try m.hits.incr(.{ .status = 3 });
    try m.timing.observe(.{ .path = "/a" }, 2);
    try m.timing.observe(.{ .path = "/a" }, 8);
    try m.timing.observe(.{ .path = "/b" }, 7);

    {
        writer.clearRetainingCapacity();
        try write(&m, &writer.writer);
        const buf = writer.writer.buffered();
        try t.expectString(
            \\# TYPE hits counter
            \\hits{status="3"} 1
            \\hits{status="199"} 2
            \\# TYPE active gauge
            \\active 32
            \\# HELP x_timing the timing
            \\# TYPE x_timing histogram
            \\x_timing_bucket{le="5",path="/b"} 0
            \\x_timing_bucket{le="10",path="/b"} 1
            \\x_timing_bucket{le="25",path="/b"} 1
            \\x_timing_bucket{le="50",path="/b"} 1
            \\x_timing_bucket{le="100",path="/b"} 1
            \\x_timing_bucket{le="250",path="/b"} 1
            \\x_timing_bucket{le="500",path="/b"} 1
            \\x_timing_bucket{le="1000",path="/b"} 1
            \\x_timing_bucket{le="+Inf",path="/b"} 1
            \\x_timing_sum{path="/b"} 7
            \\x_timing_count{path="/b"} 1
            \\x_timing_bucket{le="5",path="/a"} 1
            \\x_timing_bucket{le="10",path="/a"} 2
            \\x_timing_bucket{le="25",path="/a"} 2
            \\x_timing_bucket{le="50",path="/a"} 2
            \\x_timing_bucket{le="100",path="/a"} 2
            \\x_timing_bucket{le="250",path="/a"} 2
            \\x_timing_bucket{le="500",path="/a"} 2
            \\x_timing_bucket{le="1000",path="/a"} 2
            \\x_timing_bucket{le="+Inf",path="/a"} 2
            \\x_timing_sum{path="/a"} 10
            \\x_timing_count{path="/a"} 2
            \\
        , buf);
    }
}
