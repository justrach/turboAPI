const std = @import("std");

/// Shared Io.Threaded runtime owned by server_run().
/// Initialized once before any requests; outlives all worker threads.
pub var threaded: std.Io.Threaded = undefined;

/// Io interface derived from threaded — passed to Io.Mutex and Io.Condition
/// operations throughout server.zig and db.zig.
pub var io: std.Io = undefined;
