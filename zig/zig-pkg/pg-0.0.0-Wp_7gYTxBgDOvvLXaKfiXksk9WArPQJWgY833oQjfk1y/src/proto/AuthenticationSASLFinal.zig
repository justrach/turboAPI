const std = @import("std");
const proto = @import("_proto.zig");

const Reader = proto.Reader;

// #4 - Server finalizes with this
const AuthenticationSASLFinal = @This();

data: []const u8,

pub fn parse(data: []const u8) !AuthenticationSASLFinal {
    var reader = Reader.init(data);

    if (try reader.int32() != 12) {
        return error.NotSASLChallenge;
    }

    // can't really parse this, since it technically depends on the SASL
    // mechanism in use
    return .{
        .data = reader.rest(),
    };
}

const t = proto.testing;
test "AuthenticationSASLFinal: parse" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    {
        // too short
        try t.expectError(error.NoMoreData, AuthenticationSASLFinal.parse(buf.string()));

        try buf.write("123");
        try t.expectError(error.NoMoreData, AuthenticationSASLFinal.parse(buf.string()));
    }

    {
        // wrong special sasl type
        buf.reset();
        try buf.writeIntBig(u32, 13);
        try t.expectError(error.NotSASLChallenge, AuthenticationSASLFinal.parse(buf.string()));
    }

    {
        // success
        buf.reset();
        try buf.writeIntBig(u32, 12);
        try buf.write("some server data");

        const final = try AuthenticationSASLFinal.parse(buf.string());
        try t.expectString("some server data", final.data);
    }
}
