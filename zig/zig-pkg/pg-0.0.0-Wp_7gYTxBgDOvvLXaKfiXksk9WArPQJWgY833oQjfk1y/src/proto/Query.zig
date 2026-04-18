const std = @import("std");
const proto = @import("_proto.zig");

const Query = @This();

sql: []const u8,

pub fn write(self: Query, buf: *proto.Buffer) !void {
    // 4   + S    + 1
    // len + $sql + 0
    const payload_len = 5 + self.sql.len;

    // +1 for the type field, 'Q'
    const total_length = payload_len + 1;

    try buf.ensureTotalCapacity(total_length);

    var view = buf.skip(total_length) catch unreachable;
    view.writeByte('Q');
    view.writeIntBig(u32, @intCast(payload_len));
    view.write(self.sql);
    view.writeByte(0);
}

const t = proto.testing;
const Reader = proto.Reader;
test "Query: write" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    const q = Query{ .sql = "select 1" };
    try q.write(&buf);

    var reader = Reader.init(buf.string());
    try t.expectEqual('Q', try reader.byte());
    try t.expectEqual(13, try reader.int32()); // payload length
    try t.expectString("select 1", try reader.restAsString());
}
