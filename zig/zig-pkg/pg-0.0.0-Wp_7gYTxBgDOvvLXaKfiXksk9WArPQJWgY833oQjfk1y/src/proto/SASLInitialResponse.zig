const std = @import("std");
const proto = @import("_proto.zig");

//Client sends this based on getting a request.sasl
const SASLInitialResponse = @This();

response: []const u8,
mechanism: []const u8,

pub fn write(self: SASLInitialResponse, buf: *proto.Buffer) !void {
    // 4 +   M          + 1 + 4             + R
    // len + $mechanism + 0 + $response.len + $response
    const payload_len = 9 + self.mechanism.len + self.response.len;

    // + 1 for the leading 'p'
    const total_length = payload_len + 1;
    try buf.ensureTotalCapacity(total_length);

    // this nonsense is to skip the buffers bound checking, since we've already
    // ensured the available capacity
    var view = buf.skip(total_length) catch unreachable;
    view.writeByte('p');
    view.writeIntBig(u32, @intCast(payload_len));
    view.write(self.mechanism);
    view.writeByte(0);
    view.writeIntBig(u32, @intCast(self.response.len));
    view.write(self.response);
}

const t = proto.testing;
const Reader = proto.Reader;
test "SASLInitialResponse: write" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    const s = SASLInitialResponse{
        .mechanism = "SCRAM-SHA-256",
        .response = "a sasl response",
    };
    try s.write(&buf);

    var reader = Reader.init(buf.string());
    try t.expectEqual('p', try reader.byte());
    try t.expectEqual(37, try reader.int32()); // payload length
    try t.expectString("SCRAM-SHA-256", try reader.string());
    try t.expectEqual(15, try reader.int32()); // length of response
    try t.expectString("a sasl response", reader.rest());
}
