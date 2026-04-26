const std = @import("std");

/// Shared Io.Threaded runtime owned by the active process.
/// Initialized once before any requests; outlives all worker threads.
pub var threaded: std.Io.Threaded = undefined;

/// Io interface derived from `threaded` and passed through runtime-owned code.
pub var io: std.Io = undefined;

pub fn init(gpa: std.mem.Allocator) void {
    initWithOptions(gpa, .{});
}

pub fn initWithOptions(gpa: std.mem.Allocator, options: std.Io.Threaded.InitOptions) void {
    threaded = std.Io.Threaded.init(gpa, options);
    io = threaded.io();
}

pub fn deinit() void {
    threaded.deinit();
}
