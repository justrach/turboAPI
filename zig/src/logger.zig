// logger.zig — Convenience wrappers over telemetry event stream
// debug/info/warn/err push Log events immediately to the active exporter.

const std = @import("std");
const telemetry = @import("telemetry.zig");
const Level = telemetry.Level;

pub fn log(comptime level: Level, comptime fmt: []const u8, args: anytype) void {
    if (!telemetry.isEnabled()) return;
    if (@intFromEnum(level) < @intFromEnum(telemetry.getLevel())) return;
    var buf: [1024]u8 = undefined;
    const msg = std.fmt.bufPrint(&buf, fmt, args) catch buf[0..];
    telemetry.pushEvent(.{ .log = .{ .level = level, .msg = msg } });
}

pub fn debug(comptime fmt: []const u8, args: anytype) void {
    log(.debug, fmt, args);
}

pub fn info(comptime fmt: []const u8, args: anytype) void {
    log(.info, fmt, args);
}

pub fn warn(comptime fmt: []const u8, args: anytype) void {
    log(.warn, fmt, args);
}

pub fn err(comptime fmt: []const u8, args: anytype) void {
    log(.err, fmt, args);
}
