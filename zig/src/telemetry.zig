// telemetry.zig — Event-sourced telemetry core for TurboAPI
// Hybrid A+B: event stream internally, layered API surface (logger/telemetry) externally.
// Phase 1: structured logging (log events + stderr exporter)
// Phase 2: spans, metrics, OTLP/TurboData exporters, batching

const std = @import("std");

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
        const writer = std.debug.lockStderrWriter(&buffer);
        defer std.debug.unlockStderrWriter();
        for (events) |event| {
            writeEvent(writer, event) catch {};
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
            const ts = std.time.milliTimestamp();
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
    for (s) |c| {
        switch (c) {
            '"' => try writer.writeAll("\\\""),
            '\\' => try writer.writeAll("\\\\"),
            '\n' => try writer.writeAll("\\n"),
            '\r' => try writer.writeAll("\\r"),
            '\t' => try writer.writeAll("\\t"),
            else => {
                if (c < 0x20) {
                    try writer.print("\\u{d:0>4}", .{c});
                } else {
                    try writer.writeByte(c);
                }
            },
        }
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

var enabled: bool = false;
var log_level: Level = .info;
var log_format: enum { text, json } = .text;
var active_exporter: Exporter = undefined;

// ── Public API ───────────────────────────────────────────────────────────────

pub fn init() void {
    if (std.posix.getenv("TURBO_LOG_LEVEL")) |val| {
        if (std.mem.eql(u8, val, "debug")) log_level = .debug else if (std.mem.eql(u8, val, "info")) log_level = .info else if (std.mem.eql(u8, val, "warn")) log_level = .warn else if (std.mem.eql(u8, val, "error")) log_level = .err;
    }
    if (std.posix.getenv("TURBO_LOG_FORMAT")) |val| {
        if (std.mem.eql(u8, val, "json")) log_format = .json;
    }
    enabled = true;
    active_exporter = stderr_exporter;
}

pub fn pushEvent(event: Event) void {
    if (!enabled) return;
    active_exporter.exportEvents(&.{event});
}

pub fn isEnabled() bool {
    return enabled;
}

pub fn getLevel() Level {
    return log_level;
}

pub fn getFormat() @TypeOf(log_format) {
    return log_format;
}
