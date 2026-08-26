const std = @import("std");

/// Shared Io.Threaded runtime owned by the active process.
/// Initialized once before any requests; outlives all worker threads.
pub var threaded: std.Io.Threaded = undefined;

/// Io interface derived from `threaded` and passed through runtime-owned code.
pub var io: std.Io = undefined;
var process_initialized: std.atomic.Value(bool) = .init(false);
var process_init_lock: std.atomic.Mutex = .unlocked;

fn initWithOptions(gpa: std.mem.Allocator, options: std.Io.Threaded.InitOptions) void {
    threaded = std.Io.Threaded.init(gpa, options);
    io = threaded.io();
}

/// Initialize the process runtime exactly once. Long-lived HTTP and WebSocket
/// workers keep mutex/condition waiters tied to this `io`, so replacing or
/// deinitializing it after a listener starts is unsafe.
pub fn ensureInitialized(gpa: std.mem.Allocator, options: std.Io.Threaded.InitOptions) void {
    if (process_initialized.load(.acquire)) return;
    while (!process_init_lock.tryLock()) std.atomic.spinLoopHint();
    defer process_init_lock.unlock();
    if (process_initialized.load(.monotonic)) return;
    initWithOptions(gpa, options);
    process_initialized.store(true, .release);
}

fn deinit() void {
    threaded.deinit();
}

/// Tests that do not start process workers may own a short-lived runtime.
pub fn initForTest(gpa: std.mem.Allocator, options: std.Io.Threaded.InitOptions) void {
    std.debug.assert(!process_initialized.load(.acquire));
    initWithOptions(gpa, options);
}

pub fn deinitForTest() void {
    std.debug.assert(!process_initialized.load(.acquire));
    deinit();
}
