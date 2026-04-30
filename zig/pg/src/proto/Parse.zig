const std = @import("std");
const proto = @import("_proto.zig");

const Parse = @This();

prepared_statement: []const u8 = "",
sql: []const u8,

pub fn write(self: Parse, buf: *proto.Buffer) !void {
    // 4   + N     + 1 + S   + 1  + 2
    // len + $name + 0 + $sql + 0 + u16(0)
    const payload_len = 8 + self.prepared_statement.len + self.sql.len;

    // +1 for the type field, 'P'
    const total_length = payload_len + 1;

    try buf.ensureTotalCapacity(total_length);

    var view = buf.skip(total_length) catch unreachable;
    view.writeByte('P');
    view.writeIntBig(u32, @intCast(payload_len));
    view.write(self.prepared_statement);
    view.writeByte(0);
    view.write(self.sql);
    view.writeByte(0);
    // this is the # of parameters types that we plan on describing
    view.write(&.{ 0, 0 }); // 0 as a u16
}

const t = proto.testing;
const Reader = proto.Reader;
test "Parse: write no name" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    const p = Parse{ .sql = "select 1" };
    try p.write(&buf);

    var reader = Reader.init(buf.string());
    try t.expectEqual('P', try reader.byte());
    try t.expectEqual(16, try reader.int32()); // payload length
    try t.expectString("", try reader.string());
    try t.expectString("select 1", try reader.string());
    try t.expectEqual(0, try reader.int16());
    try t.expectString("", reader.rest());
}

test "Parse: write with name" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    const p = Parse{ .sql = "select 1", .prepared_statement = "a name" };
    try p.write(&buf);

    var reader = Reader.init(buf.string());
    try t.expectEqual('P', try reader.byte());
    try t.expectEqual(22, try reader.int32()); // payload length
    try t.expectString("a name", try reader.string());
    try t.expectString("select 1", try reader.string());
    try t.expectEqual(0, try reader.int16());
    try t.expectString("", reader.rest());
}
