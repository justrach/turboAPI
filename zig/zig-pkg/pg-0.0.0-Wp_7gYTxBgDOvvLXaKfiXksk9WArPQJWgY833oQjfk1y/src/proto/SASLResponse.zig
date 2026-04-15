const std = @import("std");
const proto = @import("_proto.zig");
const Reader = proto.Reader;

// #3 - Client finalizes with this
const SASLResponse = @This();

data: []const u8,

pub fn write(self: SASLResponse, buf: *proto.Buffer) !void {
    // 4 +   N
    // len + $data
    const payload_len = 4 + self.data.len;

    // + 1 for the leading 'p'
    const total_length = payload_len + 1;
    try buf.ensureTotalCapacity(total_length);

    // this nonsense is to skip the buffers bound checking, since we've already
    // ensured the available capacity
    var view = buf.skip(total_length) catch unreachable;
    view.writeByte('p');
    view.writeIntBig(u32, @intCast(payload_len));
    view.write(self.data);
}

const t = proto.testing;
test "SASLResponse: write" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    const s = SASLResponse{
        .data = "the response",
    };
    try s.write(&buf);

    var reader = Reader.init(buf.string());
    try t.expectEqual('p', try reader.byte());
    try t.expectEqual(16, try reader.int32()); // payload length
    try t.expectString("the response", reader.rest());
}
