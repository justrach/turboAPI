const std = @import("std");
const proto = @import("_proto.zig");

const Sync = @This();
pub fn write(_: Sync, buf: *proto.Buffer) !void {
    try buf.ensureTotalCapacity(5);
    var view = buf.skip(5) catch unreachable;
    view.write(&.{ 'S', 0, 0, 0, 4 });
}

const t = proto.testing;
const Reader = proto.Reader;
test "Sync: write" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    const s = Sync{};
    try s.write(&buf);

    var reader = Reader.init(buf.string());
    try t.expectEqual('S', try reader.byte());
    try t.expectEqual(4, try reader.int32()); // payload length
    try t.expectString("", reader.rest());
}
