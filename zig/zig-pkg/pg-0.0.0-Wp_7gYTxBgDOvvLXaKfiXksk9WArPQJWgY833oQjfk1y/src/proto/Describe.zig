const std = @import("std");
const proto = @import("_proto.zig");

const Describe = @This();

name: []const u8 = "",
type: Type = .portal,

pub const Type = enum {
    portal,
    prepared_statement,
};

pub fn write(self: Describe, buf: *proto.Buffer) !void {
    // 4   + 1     + N    + 1
    // len + $type + $name + 0
    const payload_len = 6 + self.name.len;

    // +1 for the type field, 'D'
    const total_length = payload_len + 1;

    try buf.ensureTotalCapacity(total_length);

    var view = buf.skip(total_length) catch unreachable;
    view.writeByte('D');
    view.writeIntBig(u32, @intCast(payload_len));
    view.writeByte(switch (self.type) {
        .portal => 'P',
        .prepared_statement => 'S',
    });

    view.write(self.name);
    view.writeByte(0);
}

const t = proto.testing;
const Reader = proto.Reader;
test "Describe: write portal no name" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    const p = Describe{};
    try p.write(&buf);

    var reader = Reader.init(buf.string());
    try t.expectEqual('D', try reader.byte());
    try t.expectEqual(6, try reader.int32()); // payload length
    try t.expectEqual('P', try reader.byte());
    try t.expectString("", try reader.restAsString());
}

test "Describe: write prepared statement with name" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    const p = Describe{ .type = .prepared_statement, .name = "the-name" };
    try p.write(&buf);

    var reader = Reader.init(buf.string());
    try t.expectEqual('D', try reader.byte());
    try t.expectEqual(14, try reader.int32()); // payload length
    try t.expectEqual('S', try reader.byte());
    try t.expectString("the-name", try reader.restAsString());
}
