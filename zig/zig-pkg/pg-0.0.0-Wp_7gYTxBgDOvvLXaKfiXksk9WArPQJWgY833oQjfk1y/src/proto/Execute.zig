const std = @import("std");
const proto = @import("_proto.zig");

const Execute = @This();

portal: []const u8 = "",
// 0 == no limit, don't use a nullable, since that would imply
// that 0 means something else.
max_rows: u32 = 0,

pub fn write(self: Execute, buf: *proto.Buffer) !void {
    // 4   + N       + 1 + 4
    // len + $portal + 0 + $max_rows
    const payload_len = 9 + self.portal.len;

    // +1 for the type field, 'P'
    const total_length = payload_len + 1;

    try buf.ensureTotalCapacity(total_length);

    var view = buf.skip(total_length) catch unreachable;
    view.writeByte('E');
    view.writeIntBig(u32, @intCast(payload_len));
    view.write(self.portal);
    view.writeByte(0);
    view.writeIntBig(u32, self.max_rows);
}

const t = proto.testing;
const Reader = proto.Reader;
test "Execute: write no name" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    const e = Execute{};
    try e.write(&buf);

    var reader = Reader.init(buf.string());
    try t.expectEqual('E', try reader.byte());
    try t.expectEqual(9, try reader.int32()); // payload length
    try t.expectString("", try reader.string());
    try t.expectEqual(0, try reader.int32());
    try t.expectString("", reader.rest());
}

test "Execute: write with name" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    const p = Execute{ .portal = "a name", .max_rows = 500 };
    try p.write(&buf);

    var reader = Reader.init(buf.string());
    try t.expectEqual('E', try reader.byte());
    try t.expectEqual(15, try reader.int32()); // payload length
    try t.expectString("a name", try reader.string());
    try t.expectEqual(500, try reader.int32());
    try t.expectString("", reader.rest());
}
