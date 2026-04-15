// telemetry.zig — Event-sourced telemetry core for TurboAPI
// Hybrid A+B: event stream internally, layered API surface (logger/telemetry) externally.
// Phase 1: structured logging (log events + stderr exporter)
// Phase 2: spans, metrics, OTLP/TurboData exporters, batching

const std = @import("std");

fn milliTimestamp() i64 {
    var ts: std.c.timespec = undefined;
    _ = std.c.clock_gettime(.REALTIME, &ts);
    return @as(i64, ts.sec) * 1000 + @divTrunc(@as(i64, ts.nsec), 1_000_000);
}

pub const Level = enum(u8) {
    debug = 0,
    info = 1,
    warn = 2,
    err = 3,
};

pub const SpanKind = enum { internal, server, client, producer, consumer };
pub const SpanStatus = enum { unset, ok, failed };

pub const LogEvent = struct {
    level: Level,
    msg: []const u8,
};

pub const SpanStartEvent = struct {
    trace_id: [16]u8 = undefined,
    span_id: [8]u8 = undefined,
    parent_span_id: ?[8]u8 = null,
    operation_name: []const u8 = "",
    kind: SpanKind = .server,
};

pub const SpanEndEvent = struct {
    trace_id: [16]u8 = undefined,
    span_id: [8]u8 = undefined,
    status: SpanStatus = .unset,
    duration_ns: i128 = 0,
    status_code: u16 = 0,
    operation_name: []const u8 = "",
};

pub const CounterEvent = struct {
    name: []const u8 = "",
    delta: u64 = 1,
};

pub const HistogramEvent = struct {
    name: []const u8 = "",
    value: f64 = 0,
};

pub const GaugeEvent = struct {
    name: []const u8 = "",
    value: f64 = 0,
};

pub const Event = union(enum) {
    log: LogEvent,
    span_start: SpanStartEvent,
    span_end: SpanEndEvent,
    counter: CounterEvent,
    histogram: HistogramEvent,
    gauge: GaugeEvent,
};

// ── Exporter interface (vtable) ─────────────────────────────────────────────

pub const Exporter = struct {
    ptr: *anyopaque,
    vtable: *const VTable,

    pub const VTable = struct {
        exportEvents: *const fn (*anyopaque, []const Event) void,
        flush: *const fn (*anyopaque) void,
        shutdown: *const fn (*anyopaque) void,
    };

    pub fn exportEvents(self: Exporter, events: []const Event) void {
        self.vtable.exportEvents(self.ptr, events);
    }

    pub fn doFlush(self: Exporter) void {
        self.vtable.flush(self.ptr);
    }

    pub fn doShutdown(self: Exporter) void {
        self.vtable.shutdown(self.ptr);
    }
};

// ── Stderr exporter ─────────────────────────────────────────────────────────

const StderrExporter = struct {
    fn exportEventsFn(ptr: *anyopaque, events: []const Event) void {
        _ = ptr;
        var buffer: [4096]u8 = undefined;
        const stderr = std.debug.lockStderr(&buffer);
        defer std.debug.unlockStderr();
        for (events) |event| {
            writeEvent(&stderr.file_writer.interface, event) catch {};
        }
    }

    fn flushFn(ptr: *anyopaque) void {
        _ = ptr;
    }

    fn shutdownFn(ptr: *anyopaque) void {
        _ = ptr;
    }
};

fn writeEvent(writer: anytype, event: Event) !void {
    switch (event) {
        .log => |l| try writeLogEvent(writer, l),
        else => {}, // Phase 2: span/metric event output
    }
}

fn writeLogEvent(writer: anytype, l: LogEvent) !void {
    const level_text = switch (l.level) {
        .debug => "DEBUG",
        .info => "INFO",
        .warn => "WARN",
        .err => "ERROR",
    };
    const level_json = switch (l.level) {
        .debug => "debug",
        .info => "info",
        .warn => "warn",
        .err => "error",
    };
    switch (log_format) {
        .text => {
            try writer.print("{s} {s}\n", .{ level_text, l.msg });
        },
        .json => {
            const ts = milliTimestamp();
            try writer.writeAll("{\"ts\":");
            try writer.print("{d}", .{ts});
            try writer.writeAll(",\"level\":\"");
            try writer.writeAll(level_json);
            try writer.writeAll("\",\"msg\":");
            try writeJsonString(writer, l.msg);
            try writer.writeAll("}\n");
        },
    }
}

fn writeJsonString(writer: anytype, s: []const u8) !void {
    try writer.writeByte('"');
    var pos: usize = 0;
    while (pos < s.len) {
        // Find the next character that needs escaping
        const start = pos;
        while (pos < s.len) : (pos += 1) {
            const c = s[pos];
            if (c == '"' or c == '\\' or c < 0x20) break;
        }
        // Bulk-copy the clean run
        if (pos > start) try writer.writeAll(s[start..pos]);
        if (pos >= s.len) break;
        // Emit the escape sequence
        const c = s[pos];
        switch (c) {
            '"' => try writer.writeAll("\\\""),
            '\\' => try writer.writeAll("\\\\"),
            '\n' => try writer.writeAll("\\n"),
            '\r' => try writer.writeAll("\\r"),
            '\t' => try writer.writeAll("\\t"),
            else => try writer.print("\\u{x:0>4}", .{c}),
        }
        pos += 1;
    }
    try writer.writeByte('"');
}

var stderr_vtable = Exporter.VTable{
    .exportEvents = StderrExporter.exportEventsFn,
    .flush = StderrExporter.flushFn,
    .shutdown = StderrExporter.shutdownFn,
};

var stderr_state: usize = 0;
var stderr_exporter = Exporter{
    .ptr = @ptrCast(&stderr_state),
    .vtable = &stderr_vtable,
};

// ── Global state ─────────────────────────────────────────────────────────────

var enabled: std.atomic.Value(bool) = .init(false);
var log_level: std.atomic.Value(Level) = .init(.info);
var log_format: enum { text, json } = .text;
var active_exporter: Exporter = undefined;

// ── Public API ───────────────────────────────────────────────────────────────

pub fn init() void {
    if (std.c.getenv("TURBO_LOG_LEVEL")) |_p| { const val = std.mem.span(_p);
        if (std.mem.eql(u8, val, "debug")) log_level.store(.debug, .release) else if (std.mem.eql(u8, val, "info")) log_level.store(.info, .release) else if (std.mem.eql(u8, val, "warn")) log_level.store(.warn, .release) else if (std.mem.eql(u8, val, "error")) log_level.store(.err, .release);
    }
    if (std.c.getenv("TURBO_LOG_FORMAT")) |_p| { const val = std.mem.span(_p);
        if (std.mem.eql(u8, val, "json")) log_format = .json;
    }
    enabled.store(true, .release);
    active_exporter = stderr_exporter;
}

pub fn pushEvent(event: Event) void {
    if (!enabled.load(.acquire)) return;
    active_exporter.exportEvents(&.{event});
}

pub fn isEnabled() bool {
    return enabled.load(.acquire);
}

pub fn getLevel() Level {
    return log_level.load(.acquire);
}

pub fn getFormat() @TypeOf(log_format) {
    return log_format;
}
