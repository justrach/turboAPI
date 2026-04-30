const std = @import("std");
const proto = @import("_proto.zig");
const Reader = proto.Reader;

// The server making an authentication request to the client. This is in response
// to a Startup message sent from the client. In my mind, this is really a
// "Response", but the documentation calls it a "Request" and, from the point of
// view of the server, that's what it is.
pub const AuthenticationRequest = union(enum) {
    ok: void,
    password: void,
    md5: []const u8,
    sasl: SASL,

    pub const SASL = struct {
        scram_sha_256: bool = false,
        scram_sha_256_plus: bool = false,
    };

    pub fn parse(data: []const u8) !AuthenticationRequest {
        var reader = Reader.init(data);

        switch (try reader.int32()) {
            0 => return .{ .ok = {} }, // authentication ok
            3 => return .{ .password = {} }, // authentication requires a plain-text password
            5 => {
                // 4           + 4 + 4
                // payload_len + 5 + $salt
                if (data.len != 8) {
                    return error.NoMoreData;
                }
                return .{ .md5 = reader.rest() };
            },
            10 => {
                var sasl = SASL{};
                while (reader.optionalString()) |auth_mechanism| {
                    if (std.ascii.eqlIgnoreCase(auth_mechanism, "SCRAM-SHA-256")) {
                        sasl.scram_sha_256 = true;
                    } else if (std.ascii.eqlIgnoreCase(auth_mechanism, "SCRAM-SHA-256-PLUS")) {
                        sasl.scram_sha_256_plus = true;
                    }
                }
                return .{ .sasl = sasl };
            },
            else => return error.AuthNotSupported,
        }
    }
};

const t = proto.testing;
test "AuthenticationRequest: invalid" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    {
        // empty
        try t.expectError(error.NoMoreData, AuthenticationRequest.parse(buf.string()));
    }

    {
        // less than minimum length
        try buf.write("123");
        try t.expectError(error.NoMoreData, AuthenticationRequest.parse(buf.string()));
    }

    {
        // unknown auth type
        buf.reset();
        try buf.writeIntBig(u32, 99);
        try t.expectError(error.AuthNotSupported, AuthenticationRequest.parse(buf.string()));
    }
}

test "AuthenticationRequest: ok" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    try buf.writeIntBig(u32, 0);
    const request = try AuthenticationRequest.parse(buf.string());
    try t.expectEqual({}, request.ok);
}

test "AuthenticationRequest: password" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    try buf.writeIntBig(u32, 3);
    const request = try AuthenticationRequest.parse(buf.string());
    try t.expectEqual({}, request.password);
}

test "AuthenticationRequest: md5" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    try buf.writeIntBig(u32, 5);
    try buf.write("s@Lt");
    const request = try AuthenticationRequest.parse(buf.string());
    try t.expectString("s@Lt", request.md5);
}

test "AuthenticationRequest: sasl with 1 mechanism" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    {
        try buf.writeIntBig(u32, 10);
        try buf.write("SCRAM-SHA-256");
        try buf.writeByte(0);

        const request = try AuthenticationRequest.parse(buf.string());
        try t.expectEqual(true, request.sasl.scram_sha_256);
        try t.expectEqual(false, request.sasl.scram_sha_256_plus);
    }

    {
        buf.reset();
        try buf.writeIntBig(u32, 10);
        try buf.write("SCRAM-SHA-256-PLUS");
        try buf.writeByte(0);

        const request = try AuthenticationRequest.parse(buf.string());
        try t.expectEqual(false, request.sasl.scram_sha_256);
        try t.expectEqual(true, request.sasl.scram_sha_256_plus);
    }
}

test "AuthenticationRequest: sasl with multiple including unknown" {
    var buf = try proto.Buffer.init(t.allocator, 128);
    defer buf.deinit();

    try buf.writeIntBig(u32, 10);
    try buf.write("SCRAM-SHA-256-PLUS");
    try buf.writeByte(0);
    try buf.write("SCRAM-SHA-256");
    try buf.writeByte(0);
    try buf.write("SCRAM-MD5");
    try buf.writeByte(0);

    const request = try AuthenticationRequest.parse(buf.string());
    try t.expectEqual(true, request.sasl.scram_sha_256);
    try t.expectEqual(true, request.sasl.scram_sha_256_plus);
}
