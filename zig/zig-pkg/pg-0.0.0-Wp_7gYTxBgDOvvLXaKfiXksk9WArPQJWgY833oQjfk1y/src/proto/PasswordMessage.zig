const std = @import("std");
const proto = @import("_proto.zig");

const PasswordMessage = @This();

password: []const u8,

pub fn write(self: PasswordMessage, buf: *proto.Buffer) !void {
    // +4 since the payload length includes the length itself
    // +1 for null terminated string
    const payload_len = self.password.len + 5;

    // +1 for the type field, 'p'
    const total_length = payload_len + 1;

    try buf.ensureTotalCapacity(total_length);

    var view = buf.skip(total_length) catch unreachable;
    view.writeByte('p');
    view.writeIntBig(u32, @intCast(payload_len));
    view.write(self.password);
    view.writeByte(0);
}

const t = proto.testing;
const Reader = proto.Reader;
test "PasswordMessage: write" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    const pw = PasswordMessage{ .password = "gh@nim@" };
    try pw.write(&buf);

    var reader = Reader.init(buf.string());
    try t.expectEqual('p', try reader.byte());
    try t.expectEqual(12, try reader.int32()); // payload length
    try t.expectString("gh@nim@", try reader.string());
}
