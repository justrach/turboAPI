const std = @import("std");
const lib = @import("lib.zig");
const builtin = @import("builtin");

const posix = std.posix;
const Conn = lib.Conn;
const Allocator = std.mem.Allocator;

// to everyone else, this is our reader
pub const Reader = ReaderT(lib.Stream);

const zero_timeval = std.mem.toBytes(posix.timeval{ .sec = 0, .usec = 0 });

// generic just for testing within this file
fn ReaderT(comptime T: type) type {
    return struct {
        // Whether or not we've put a timeout on the request. This helps avoid
        // system calls when no timeout is set.
        has_timeout: bool,

        // Provided when the reader was allocated (which is the allocator given
        // when the connection/pool was created). Owns `static` and unless a query-
        // specific allocator is provided, will be used for any dynamic allocations.
        default_allocator: Allocator,

        // Current active allocator. This will normally reference `default_allocator`
        // but a query can provide a specific allocator to use for the processing
        // of said query. (via startFlow)
        allocator: Allocator,

        // Exists for the lifetime of the reader, but normally references this, but
        // for messages that don't fit, we'll allocate memory dynamically and
        // eventually revert back to buf.
        static: []u8,

        // buffer to read into
        buf: []u8,

        // start within buf of the next message
        start: usize = 0,

        // position in buf that we have valid data up to
        pos: usize = 0,

        stream: T,

        const Self = @This();

        pub fn init(allocator: Allocator, size: usize, stream: T) !Self {
            const static = try allocator.alloc(u8, size);
            return .{
                .buf = static,
                .stream = stream,
                .static = static,
                .has_timeout = false,
                .allocator = allocator,
                .default_allocator = allocator,
            };
        }

        pub fn deinit(self: Self) void {
            if (self.static.ptr != self.buf.ptr) {
                self.allocator.free(self.buf);
            }
            self.default_allocator.free(self.static);
        }

        // Between a call to startFlow and endFlow, the reader can re-use any
        // dynamic buffer it creates. The idea beind this is that if reading 1 row
        // requires more than static.len other rows within the same result might
        // as well.
        pub fn startFlow(self: *Self, allocator: ?Allocator, timeout_ms: ?u32) !void {
            if (timeout_ms) |ms| {
                const timeval = std.mem.toBytes(posix.timeval{
                    .sec = @intCast(@divTrunc(ms, 1000)),
                    .usec = @intCast(@mod(ms, 1000) * 1000),
                });
                try posix.setsockopt(self.stream.socket, posix.SOL.SOCKET, posix.SO.RCVTIMEO, &timeval);
                self.has_timeout = true;
            } else if (self.has_timeout) {
                try posix.setsockopt(self.stream.socket, posix.SOL.SOCKET, posix.SO.RCVTIMEO, &zero_timeval);
                self.has_timeout = false;
            }

            self.allocator = allocator orelse self.default_allocator;
        }

        pub fn endFlow(self: *Self) !void {
            const buf = self.buf;
            const allocator = self.allocator;

            self.allocator = self.default_allocator;
            if (self.static.ptr == buf.ptr) {
                // we never created a dynamic buffer
                return;
            }

            // even if the following fails, we want to free this
            defer allocator.free(buf);

            // Normally, when an "flow" ends, we expect our read buffer to be empty.
            // This is true because data from PG is normally only sent in response
            // to a request. If we've ended our "flow", then we should have read
            // everything from PG. But PG can occasionally send data on its own.
            // So it's possible that we over-read and now our dynamic buffer has
            // data unrelated to this flow.
            const pos = self.pos;
            const start = self.start;
            const extra = pos - start;

            var new_buf: []u8 = undefined;
            if (extra > self.static.len) {
                // This is unusual. Not only did we overread, but we've overread so
                // much that we can't use our static buffer.

                const default_allocator = self.default_allocator;
                if (allocator.ptr == default_allocator.ptr) {
                    // The dynamic buffer was allocated with our default allocator, so
                    // we can keep it as-is
                    return;
                }

                // This is the worst. We have extra data in our dynamically buffer AND
                // we have a query-specific allocator. This data _cannot_ remain
                // where it is (because we have no guarantee that the allocator is valid
                // beyond this query).
                // So we'll copy it to a new buffer using our default allocator.
                new_buf = try default_allocator.dupe(u8, self.buf[start..pos]);
            } else {
                // We either have no extra data, or we have extra data, but it fits in
                // our static buffer. Either way, we're reverting self.buf to self.static;
                new_buf = self.static;
                if (extra > 0) {
                    // We read extra data, copy this into our static buffer
                    @memcpy(new_buf[0..extra], self.buf[start..pos]);
                }
            }

            self.pos = extra;
            self.start = 0;
            self.buf = new_buf;
        }

        // If you execute "select * from invalid_table", PostgreSQL will return
        // an error early in the process of preparing the statement - as part
        // of parsing the statement, it knows that "invalid_table" isn't a valid table.

        // But if you execute "create table already_exists", the error is is only
        // returned once you try to read the result.
        //
        // This difference results in an inconsistent api: some error are returned
        // immediately by conn.query() and some errors are only returned when
        // result.next() is first called.
        //
        // Here we attempt to fix this by eagerly reading the next message. If it's
        // an error, we return it. If it isn't an error, we put it back for the next
        // successful read.
        pub fn peekForError(self: *Self) !?[]const u8 {
            const message = self.buffered(self.pos, true) orelse try self.read(true);
            return if (message.type == 'E') message.data else null;
        }

        pub fn next(self: *Self) !Message {
            return self.buffered(self.pos, false) orelse self.read(false);
        }

        fn read(self: *Self, error_peek: bool) !Message {
            var stream = self.stream;
            // const spare = buf.len - pos; // how much space we have left in our buffer

            // Every PG message has 1 type byte followed by a 4 byte length prefix.
            // Since the length prefix includes itself (but not the type byte) the
            // minimum possible length is 4. We use 0 to denote "unknown".
            var buf = self.buf;
            var pos = self.pos;
            var message_length: usize = 0;

            while (true) {
                if (message_length == 0) {
                    // we don't yet know the length of this message

                    const start = self.start;

                    // how much of the next message we have
                    const current_length = pos - start;

                    // we have enough data to figure the message length
                    if (current_length > 4) {
                        // + 1 for the type byte
                        message_length = std.mem.readInt(u32, buf[start + 1 .. start + 5][0..4], .big) + 1;

                        if (message_length > buf.len) {
                            var new_buf: []u8 = undefined;
                            const allocator = self.allocator;

                            if (buf.ptr == self.static.ptr) {
                                //currently using our static buffer, we need to allocate a larger one
                                new_buf = try allocator.alloc(u8, message_length);
                                @memcpy(new_buf[0..current_length], buf[start..pos]);
                                lib.metrics.allocReader(message_length);
                            } else {
                                // currently using a dynamically allocated buffer, we'll
                                // grow or allocate a larger one (which is what realloc does)
                                new_buf = try allocator.realloc(buf, message_length);
                                if (start > 0) {
                                    std.mem.copyForwards(u8, new_buf[0..current_length], new_buf[start..pos]);
                                }
                                lib.metrics.allocReader(message_length - current_length);
                            }

                            self.start = 0;
                            pos = current_length;
                            buf = new_buf;
                            self.buf = new_buf;
                        } else if (message_length > buf.len - start) {
                            // our buffer is big enough, but not from where we're currently starting
                            std.mem.copyForwards(u8, buf[0..current_length], buf[start..pos]);
                            pos = current_length;
                            self.start = 0;
                        }
                    } else if (buf.len - start < 5) {
                        // we don't even have enough space to read the 5 byte header
                        std.mem.copyForwards(u8, buf[0..current_length], buf[start..pos]);
                        pos = current_length;
                        self.start = 0;
                    }
                }

                const n = try stream.read(buf[pos..]);
                if (n == 0) {
                    return error.Closed;
                }
                pos += n;
                if (self.buffered(pos, error_peek)) |msg| {
                    return msg;
                }
            }
        }

        // checks and consume if we already have a message buffered
        fn buffered(self: *Self, pos: usize, error_peek: bool) ?Message {
            const start = self.start;
            const available = pos - start;

            // we always need at least 5 bytes, 1 for the type and 4 for the length
            if (available < 5) {
                return null;
            }
            const buf = self.buf;

            const len_end = start + 5;
            const len = std.mem.readInt(u32, buf[start + 1 .. len_end][0..4], .big);

            // +1 because the first byte, the message type, isn't included in the length
            if (available < len + 1) {
                return null;
            }

            // -4 because the len includes the 4 byte length header itself
            const end = len_end + len - 4;

            const message_type = buf[start];

            if (error_peek == false or message_type == 'E') {
                // how much extra data we already have
                const extra = pos - end;
                if (extra == 0) {
                    // we have no more data in the buffer, reset everything to the start
                    // so that we have the full buffer for future messages
                    self.pos = 0;
                    self.start = 0;
                } else {
                    self.pos = pos;
                    self.start = end;
                }
            } else {
                self.pos = pos;
            }

            return .{
                .type = message_type,
                .data = buf[len_end..end],
            };
        }
    };
}

pub const Message = struct {
    type: u8,
    data: []const u8,
};

const t = lib.testing;
test "Reader: next" {
    const R = ReaderT(*t.Stream);
    var s = t.Stream.init();
    defer s.deinit();

    {
        s.reset();
        s.add(&[_]u8{ 8, 0, 0, 0, 4 });
        var reader = R.init(t.allocator, 10, s) catch unreachable;
        defer reader.deinit();
        const msg = try reader.next();
        try t.expectEqual(8, msg.type);
        try t.expectSlice(u8, &[_]u8{}, msg.data);
    }

    {
        s.reset();
        s.add(&[_]u8{ 1, 0, 0, 0, 5, 2 });
        var reader = R.init(t.allocator, 10, s) catch unreachable;
        defer reader.deinit();
        const msg = try reader.next();
        try t.expectEqual(1, msg.type);
        try t.expectSlice(u8, &[_]u8{2}, msg.data);
    }

    {
        s.reset();
        s.add(&[_]u8{ 1, 0, 0, 0, 9, 1, 2, 3, 4, 19 });
        var reader = R.init(t.allocator, 10, s) catch unreachable;
        defer reader.deinit();
        const msg = try reader.next();
        try t.expectEqual(1, msg.type);
        try t.expectSlice(u8, &[_]u8{ 1, 2, 3, 4, 19 }, msg.data);
        // optimization, resets pos to 0 since we read an exact message
        try t.expectEqual(0, reader.pos);
    }

    {
        // partial 2nd message, but closed without all the data
        s.reset();
        s.add(&[_]u8{ 1, 0, 0, 0, 9, 1, 2, 3, 4, 19, 2 });
        var reader = R.init(t.allocator, 10, s) catch unreachable;
        defer reader.deinit();
        const msg = try reader.next();
        try t.expectEqual(1, msg.type);
        try t.expectSlice(u8, &[_]u8{ 1, 2, 3, 4, 19 }, msg.data);
        try t.expectError(error.Closed, reader.next());
    }

    {
        // 2 full messages, 2nd message has no data
        s.reset();
        s.add(&[_]u8{ 99, 0, 0, 0, 6, 200, 201, 2, 0, 0, 0, 4 });
        var reader = R.init(t.allocator, 20, s) catch unreachable;
        defer reader.deinit();

        const msg1 = try reader.next();
        try t.expectEqual(99, msg1.type);
        try t.expectSlice(u8, &[_]u8{ 200, 201 }, msg1.data);

        const msg2 = try reader.next();
        try t.expectEqual(2, msg2.type);
        try t.expectSlice(u8, &[_]u8{}, msg2.data);
    }

    {
        // 2 full messages, 2nd message has data
        s.reset();
        s.add(&[_]u8{ 99, 0, 0, 0, 6, 200, 201, 3, 0, 0, 0, 7, 1, 8, 2 });
        var reader = R.init(t.allocator, 20, s) catch unreachable;
        defer reader.deinit();

        const msg1 = try reader.next();
        try t.expectEqual(99, msg1.type);
        try t.expectSlice(u8, &[_]u8{ 200, 201 }, msg1.data);

        const msg2 = try reader.next();
        try t.expectEqual(3, msg2.type);
        try t.expectSlice(u8, &[_]u8{ 1, 8, 2 }, msg2.data);
    }

    {
        // 2 full messages, split across packets
        s.reset();
        s.add(&[_]u8{ 91, 0, 0, 0, 6, 200, 22, 4, 0, 0, 0, 5 });
        var reader = R.init(t.allocator, 20, s) catch unreachable;
        defer reader.deinit();

        const msg1 = try reader.next();
        try t.expectEqual(91, msg1.type);
        try t.expectSlice(u8, &[_]u8{ 200, 22 }, msg1.data);

        s.add(&[_]u8{73});
        const msg2 = try reader.next();
        try t.expectEqual(4, msg2.type);
        try t.expectSlice(u8, &[_]u8{73}, msg2.data);
    }

    {
        // not enough room in buffer for header of 2nd message
        s.reset();
        s.add(&[_]u8{ 17, 0, 0, 0, 4, 5 });
        var reader = R.init(t.allocator, 8, s) catch unreachable;
        defer reader.deinit();

        const msg1 = try reader.next();
        try t.expectEqual(17, msg1.type);
        try t.expectSlice(u8, &[_]u8{}, msg1.data);

        s.add(&[_]u8{ 0, 0, 0, 6, 10, 12 });
        const msg2 = try reader.next();
        try t.expectEqual(5, msg2.type);
        try t.expectSlice(u8, &[_]u8{ 10, 12 }, msg2.data);
    }

    {
        // not enough room in buffer for header of 2nd message across multiple callss
        s.reset();
        s.add(&[_]u8{ 17, 0, 0, 0, 5, 1, 200 });
        var reader = R.init(t.allocator, 8, s) catch unreachable;
        defer reader.deinit();

        const msg1 = try reader.next();
        try t.expectEqual(17, msg1.type);
        try t.expectSlice(u8, &[_]u8{1}, msg1.data);

        s.add(&[_]u8{ 0, 0 });
        s.add(&[_]u8{0});
        s.add(&[_]u8{ 7, 10, 12, 14 });
        const msg2 = try reader.next();
        try t.expectEqual(200, msg2.type);
        try t.expectSlice(u8, &[_]u8{ 10, 12, 14 }, msg2.data);
    }
}

// simulates message fragmentations
test "Reader: fuzz" {
    const R = ReaderT(*t.Stream);

    var r = t.getRandom();
    const random = r.random();

    const messages = [_]u8{ 1, 0, 0, 0, 4, 2, 0, 0, 0, 5, 1, 3, 0, 0, 0, 6, 1, 2, 4, 0, 0, 0, 24, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 5, 0, 0, 0, 8, 1, 2, 3, 4, 6, 0, 0, 0, 9, 1, 2, 3, 4, 5, 7, 0, 0, 0, 10, 1, 2, 3, 4, 5, 6, 8, 0, 0, 0, 11, 1, 2, 3, 4, 5, 6, 7, 9, 0, 0, 0, 25, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21 };

    for (0..400) |_| {
        var s = t.Stream.init();
        defer s.deinit();
        var reader = R.init(t.allocator, 12, s) catch unreachable;
        defer reader.deinit();

        for (0..4) |_| {
            var buf: []const u8 = messages[0..];
            while (buf.len > 0) {
                const l = random.uintAtMost(usize, buf.len - 1) + 1;
                s.add(buf[0..l]);
                buf = buf[l..];
            }

            var arena = std.heap.ArenaAllocator.init(t.allocator);
            defer arena.deinit();

            const allocator: ?Allocator = if (random.uintAtMost(usize, 1) == 1) arena.allocator() else null;

            try reader.startFlow(allocator, null);
            defer reader.endFlow() catch unreachable;

            {
                const msg = try reader.next();
                try t.expectEqual(1, msg.type);
                try t.expectSlice(u8, &[_]u8{}, msg.data);
            }

            {
                const msg = try reader.next();
                try t.expectEqual(2, msg.type);
                try t.expectSlice(u8, &[_]u8{1}, msg.data);
            }

            {
                const msg = try reader.next();
                try t.expectEqual(3, msg.type);
                try t.expectSlice(u8, &[_]u8{ 1, 2 }, msg.data);
            }

            {
                const msg = try reader.next();
                try t.expectEqual(4, msg.type);
                try t.expectSlice(u8, &[_]u8{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20 }, msg.data);
            }

            {
                const msg = try reader.next();
                try t.expectEqual(5, msg.type);
                try t.expectSlice(u8, &[_]u8{ 1, 2, 3, 4 }, msg.data);
            }

            {
                const msg = try reader.next();
                try t.expectEqual(6, msg.type);
                try t.expectSlice(u8, &[_]u8{ 1, 2, 3, 4, 5 }, msg.data);
            }

            {
                const msg = try reader.next();
                try t.expectEqual(7, msg.type);
                try t.expectSlice(u8, &[_]u8{ 1, 2, 3, 4, 5, 6 }, msg.data);
            }

            {
                const msg = try reader.next();
                try t.expectEqual(8, msg.type);
                try t.expectSlice(u8, &[_]u8{ 1, 2, 3, 4, 5, 6, 7 }, msg.data);
            }

            {
                const msg = try reader.next();
                try t.expectEqual(9, msg.type);
                try t.expectSlice(u8, &[_]u8{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21 }, msg.data);
            }
            try t.expectError(error.Closed, reader.next());
        }
    }
}

test "Reader: dynamic" {
    const R = ReaderT(*t.Stream);
    var s = t.Stream.init();
    defer s.deinit();

    {
        //  message bigger than static buffer
        s.add(&[_]u8{ 200, 0, 0, 0, 14, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 });
        var reader = R.init(t.allocator, 10, s) catch unreachable;
        defer reader.deinit();
        const msg = try reader.next();
        try t.expectEqual(200, msg.type);
        try t.expectSlice(u8, &.{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 }, msg.data);
    }

    {
        //  2nd message bigger than static buffer
        s.add(&[_]u8{ 199, 0, 0, 0, 6, 9, 8, 200, 0, 0, 0, 14, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 });
        var reader = R.init(t.allocator, 10, s) catch unreachable;
        defer reader.deinit();

        const msg1 = try reader.next();
        try t.expectEqual(199, msg1.type);
        try t.expectSlice(u8, &.{ 9, 8 }, msg1.data);

        const msg2 = try reader.next();
        try t.expectEqual(200, msg2.type);
        try t.expectSlice(u8, &.{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 }, msg2.data);
    }

    {
        // middle message bigger than static
        s.add(&[_]u8{ 199, 0, 0, 0, 6, 9, 8, 200, 0, 0, 0, 14, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 198, 0, 0, 0, 5, 1 });
        var reader = R.init(t.allocator, 10, s) catch unreachable;
        defer reader.deinit();

        const msg1 = try reader.next();
        try t.expectEqual(199, msg1.type);
        try t.expectSlice(u8, &.{ 9, 8 }, msg1.data);

        const msg2 = try reader.next();
        try t.expectEqual(200, msg2.type);
        try t.expectSlice(u8, &.{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 }, msg2.data);

        const msg3 = try reader.next();
        try t.expectEqual(198, msg3.type);
        try t.expectSlice(u8, &.{1}, msg3.data);
    }
}

test "Reader: start/endFlow basic" {
    const R = ReaderT(*t.Stream);
    var s = t.Stream.init();
    defer s.deinit();

    // 1st message is bigge than static
    s.add(&[_]u8{ 1, 0, 0, 0, 8, 1, 2, 3, 4 });

    // 2nd message is bigger than first
    s.add(&[_]u8{ 2, 0, 0, 0, 10, 1, 2, 3, 4, 5, 6 });

    // 3rd message is smaller than 2nd (should re-use previous buffer)
    s.add(&[_]u8{ 3, 0, 0, 0, 9, 1, 2, 3, 4, 5 });

    var reader = R.init(t.allocator, 5, s) catch unreachable;
    defer reader.deinit();

    try reader.startFlow(null, null);
    const msg1 = try reader.next();
    try t.expectSlice(u8, &.{ 1, 2, 3, 4 }, msg1.data);

    const msg2 = try reader.next();
    try t.expectSlice(u8, &.{ 1, 2, 3, 4, 5, 6 }, msg2.data);

    const msg3 = try reader.next();
    try t.expectSlice(u8, &.{ 1, 2, 3, 4, 5 }, msg3.data);
    reader.endFlow() catch unreachable;
}

test "Reader: start/endFlow overread into static" {
    const R = ReaderT(*t.Stream);
    var s = t.Stream.init();
    defer s.deinit();

    // 1st message is bigge than static
    s.add(&[_]u8{ 1, 0, 0, 0, 8, 1, 2, 3, 4 });

    // 2nd message is bigger than first
    s.add(&[_]u8{ 2, 0, 0, 0, 10, 1, 2, 3, 4, 5, 6 });

    // 3rd message is smaller than 2nd (should re-use previous buffer)
    s.add(&[_]u8{ 3, 0, 0, 0, 9, 1, 2, 3, 4, 5 });

    // 4th message is overread and fits in static
    s.add(&[_]u8{ 3, 0, 0, 0, 5, 255 });

    var reader = R.init(t.allocator, 7, s) catch unreachable;
    defer reader.deinit();

    try reader.startFlow(null, null);
    const msg1 = try reader.next();
    try t.expectSlice(u8, &.{ 1, 2, 3, 4 }, msg1.data);

    const msg2 = try reader.next();
    try t.expectSlice(u8, &.{ 1, 2, 3, 4, 5, 6 }, msg2.data);

    const msg3 = try reader.next();
    try t.expectSlice(u8, &.{ 1, 2, 3, 4, 5 }, msg3.data);
    reader.endFlow() catch unreachable;

    const msg4 = try reader.next();
    try t.expectSlice(u8, &.{255}, msg4.data);
}

test "Reader: start/endFlow large overread" {
    const R = ReaderT(*t.Stream);
    var s = t.Stream.init();
    defer s.deinit();

    // 1st message is bigger than static
    s.add(&[_]u8{ 1, 0, 0, 0, 8, 1, 2, 3, 4 });

    // 2nd message is bigger than first
    s.add(&[_]u8{ 2, 0, 0, 0, 18, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14 });

    // 3rd message is smaller than 2nd (should re-use previous buffer)
    s.add(&[_]u8{ 3, 0, 0, 0, 9, 1, 2, 3, 4, 5 });

    // 4rd message is huge
    s.add(&[_]u8{ 4, 0, 0, 19, 140 } ++ "z" ** 5000);

    // 5th message is overread and does not fit into static
    s.add(&[_]u8{ 5, 0, 0, 0, 11, 255, 250, 245, 240, 235, 230, 225 });

    var reader = R.init(t.allocator, 7, s) catch unreachable;
    defer reader.deinit();

    try reader.startFlow(null, null);
    const msg1 = try reader.next();
    try t.expectSlice(u8, &.{ 1, 2, 3, 4 }, msg1.data);

    const msg2 = try reader.next();
    try t.expectSlice(u8, &.{ 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14 }, msg2.data);

    const msg3 = try reader.next();
    try t.expectSlice(u8, &.{ 1, 2, 3, 4, 5 }, msg3.data);

    const msg4 = try reader.next();
    try t.expectSlice(u8, "z" ** 5000, msg4.data);
    reader.endFlow() catch unreachable;

    const msg5 = try reader.next();
    try t.expectSlice(u8, &.{ 255, 250, 245, 240, 235, 230, 225 }, msg5.data);
}

test "Reader: start/endFlow large overread with flow-specific allocator" {
    defer t.reset();
    const R = ReaderT(*t.Stream);
    var s = t.Stream.init();
    defer s.deinit();

    // 1st message is bigger than static
    s.add(&[_]u8{ 1, 0, 0, 0, 8, 1, 2, 3, 4 });

    // 2nd message is bigger than first
    s.add(&[_]u8{ 2, 0, 0, 0, 10, 1, 2, 3, 4, 5, 6 });

    // 3rd message is smaller than 2nd (should re-use previous buffer)
    s.add(&[_]u8{ 3, 0, 0, 0, 9, 1, 2, 3, 4, 5 });

    // 4th message is overread and does not fit into static
    s.add(&[_]u8{ 3, 0, 0, 0, 11, 255, 250, 245, 240, 235, 230, 225 });

    var reader = R.init(t.allocator, 7, s) catch unreachable;
    defer reader.deinit();

    try reader.startFlow(t.arena.allocator(), null);
    const msg1 = try reader.next();
    try t.expectSlice(u8, &.{ 1, 2, 3, 4 }, msg1.data);

    const msg2 = try reader.next();
    try t.expectSlice(u8, &.{ 1, 2, 3, 4, 5, 6 }, msg2.data);

    const msg3 = try reader.next();
    try t.expectSlice(u8, &.{ 1, 2, 3, 4, 5 }, msg3.data);
    reader.endFlow() catch unreachable;

    const msg4 = try reader.next();
    try t.expectSlice(u8, &.{ 255, 250, 245, 240, 235, 230, 225 }, msg4.data);
}

test "Reader: startFlow with dynamic allocation into deinit " {
    // This can happen on an error case, where we start a flow, but an error
    // happens during processing, causing conn.deinit() to be called (say, when
    // it's released back into the pool in an error state).
    defer t.reset();
    const R = ReaderT(*t.Stream);
    var s = t.Stream.init();
    defer s.deinit();

    // 1st message is bigger than static
    s.add(&[_]u8{ 1, 0, 0, 0, 8, 1, 2, 3, 4 });

    var reader = R.init(t.allocator, 7, s) catch unreachable;
    defer reader.deinit();

    try reader.startFlow(t.arena.allocator(), null);
    const msg1 = try reader.next();
    try t.expectSlice(u8, &.{ 1, 2, 3, 4 }, msg1.data);
}
