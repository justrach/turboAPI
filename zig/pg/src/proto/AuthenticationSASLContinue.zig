const std = @import("std");
const proto = @import("_proto.zig");
const Reader = proto.Reader;

// #2 - Server responds with this
const AuthenticationSASLContinue = @This();

data: []const u8,

pub fn parse(data: []const u8) !AuthenticationSASLContinue {
    var reader = Reader.init(data);

    if (try reader.int32() != 11) {
        return error.NotSASLChallenge;
    }

    return .{
        .data = reader.rest(),
    };
}

const t = proto.testing;
test "AuthenticationSASLContinue: parse" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    {
        // too short
        try t.expectError(error.NoMoreData, AuthenticationSASLContinue.parse(buf.string()));

        try buf.write("123");
        try t.expectError(error.NoMoreData, AuthenticationSASLContinue.parse(buf.string()));
    }

    {
        // wrong special sasl type
        buf.reset();
        try buf.writeIntBig(u32, 12);
        try t.expectError(error.NotSASLChallenge, AuthenticationSASLContinue.parse(buf.string()));
    }

    {
        // success
        buf.reset();
        try buf.writeIntBig(u32, 11);
        try buf.write("r=a-nounce,s=the-S@lt,i=4096");

        const c = try AuthenticationSASLContinue.parse(buf.string());
        try t.expectString("r=a-nounce,s=the-S@lt,i=4096", c.data);
    }
}
