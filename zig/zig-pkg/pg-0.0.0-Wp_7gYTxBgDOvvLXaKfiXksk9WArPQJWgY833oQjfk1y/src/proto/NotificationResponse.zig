const std = @import("std");
const proto = @import("_proto.zig");

const Reader = proto.Reader;

const NotificationResponse = @This();

process_id: u32,
channel: []const u8,
payload: []const u8,

pub fn parse(data: []const u8) !NotificationResponse {
    var reader = Reader.init(data);
    return .{ .process_id = try reader.int32(), .channel = try reader.string(), .payload = try reader.string() };
}

const t = proto.testing;
test "NotificationResponse: parse" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    try buf.writeIntBig(u32, 912);
    try buf.write("chan-1");
    try buf.writeByte(0);
    try buf.write("payload-2");
    try buf.writeByte(0);

    const nr = try NotificationResponse.parse(buf.string());
    try t.expectEqual(912, nr.process_id);
    try t.expectString("chan-1", nr.channel);
    try t.expectString("payload-2", nr.payload);
}
