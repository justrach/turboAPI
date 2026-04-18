const std = @import("std");
const builtin = @import("builtin");

const Buffer = @import("buffer.zig").Buffer;

const Mutex = std.Thread.Mutex;
const Allocator = std.mem.Allocator;

pub const Pool = struct {
    mutex: Mutex,
    available: usize,
    allocator: Allocator,
    buffer_size: usize,
    buffers: []*Buffer,

    pub fn init(allocator: Allocator, pool_size: u16, buffer_size: usize) !Pool {
        const buffers = try allocator.alloc(*Buffer, pool_size);

        for (0..pool_size) |i| {
            const sb = try allocator.create(Buffer);
            sb.* = try Buffer.init(allocator, buffer_size);
            buffers[i] = sb;
        }

        return .{ .mutex = .{}, .buffers = buffers, .allocator = allocator, .available = pool_size, .buffer_size = buffer_size };
    }

    pub fn deinit(self: *Pool) void {
        const allocator = self.allocator;
        for (self.buffers) |sb| {
            sb.deinit();
            allocator.destroy(sb);
        }
        allocator.free(self.buffers);
    }

    pub fn acquire(self: *Pool) !*Buffer {
        return self.acquireWithAllocator(self.allocator);
    }

    pub fn acquireWithAllocator(self: *Pool, dyn_allocator: Allocator) !*Buffer {
        const buffers = self.buffers;

        self.mutex.lock();
        const available = self.available;
        if (available == 0) {
            // dont hold the lock over factory
            self.mutex.unlock();

            const allocator = self.allocator;
            const sb = try allocator.create(Buffer);
            sb.* = try Buffer.init(allocator, self.buffer_size);
            sb._da = dyn_allocator;
            return sb;
        }
        const index = available - 1;
        const sb = buffers[index];
        self.available = index;
        self.mutex.unlock();
        sb._da = dyn_allocator;
        return sb;
    }

    pub fn release(self: *Pool, sb: *Buffer) void {
        sb.reset();
        self.mutex.lock();

        var buffers = self.buffers;
        const available = self.available;
        if (available == buffers.len) {
            self.mutex.unlock();
            const allocator = self.allocator;
            sb.deinit();
            allocator.destroy(sb);
            return;
        }
        buffers[available] = sb;
        self.available = available + 1;
        self.mutex.unlock();
    }
};

const t = @import("t.zig");
test "pool: acquire and release" {
    var p = try Pool.init(t.allocator, 2, 100);
    defer p.deinit();

    const sb1a = p.acquire() catch unreachable;
    const sb2a = p.acquire() catch unreachable;
    const sb3a = p.acquire() catch unreachable; // this should be dynamically generated

    try t.expectEqual(false, sb1a == sb2a);
    try t.expectEqual(false, sb2a == sb3a);

    p.release(sb1a);

    const sb1b = p.acquire() catch unreachable;
    try t.expectEqual(true, sb1a == sb1b);

    p.release(sb3a);
    p.release(sb2a);
    p.release(sb1b);
}

test "pool: dynamic allocator" {
    var p = try Pool.init(t.allocator, 2, 5);
    defer p.deinit();

    var arena = std.heap.ArenaAllocator.init(t.allocator);
    defer arena.deinit();

    var sb = p.acquireWithAllocator(arena.allocator()) catch unreachable;
    try sb.write("hello world how's it going?");
    try sb.write("he");
    try sb.write("hello world");
    try sb.write("are you doing well? I hope so, I don't love how this is being implemented, but I think the feature is worthwhile");
    p.release(sb);
}

test "pool: threadsafety" {
    var p = try Pool.init(t.allocator, 3, 20);
    defer p.deinit();

    // initialize this to 0 since we're asserting that it's 0
    for (p.buffers) |sb| {
        sb.buf[0] = 0;
    }

    const t1 = try std.Thread.spawn(.{}, testPool, .{&p});
    const t2 = try std.Thread.spawn(.{}, testPool, .{&p});
    const t3 = try std.Thread.spawn(.{}, testPool, .{&p});

    t1.join();
    t2.join();
    t3.join();
}

fn testPool(p: *Pool) void {
    var r = t.getRandom();
    const random = r.random();

    for (0..5000) |_| {
        var sb = p.acquire() catch unreachable;
        // no other thread should have set this to 255
        std.debug.assert(sb.buf[0] == 0);

        sb.buf[0] = 255;
        std.Thread.sleep(random.uintAtMost(u32, 100000));
        sb.buf[0] = 0;
        p.release(sb);
    }
}
