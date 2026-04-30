const std = @import("std");
const buffer = @import("buffer");
const lib = @import("../lib.zig");
const types = @import("../types.zig");

pub const Cidr = struct {
    pub const encoding = &types.binary_encoding;
    pub const oid = types.OID.make(650);
    pub const inet_oid = types.OID.make(869);

    address: []const u8,
    netmask: u8,
    family: Family,

    pub const Family = enum {
        v4,
        v6,
    };

    pub fn decode(comptime fail_mode: lib.FailMode, data: []const u8, data_oid: i32) if (fail_mode == .unsafe) Cidr else lib.TypeError!Cidr {
        lib.verifyDecodeType(fail_mode, Cidr, &.{ Cidr.oid.decimal, Cidr.inet_oid.decimal }, data_oid) catch |err| {
            if (fail_mode == .unsafe) unreachable;
            return err;
        };

        lib.assert(data.len == 8 or data.len == 20);
        return decodeKnown(data);
    }

    pub fn decodeKnown(data: []const u8) Cidr {
        // data[0] is 2 for v4 and 3 for v6, but we can infer this from the length
        // data[1] is the netmask
        // data[2] is an is_cidr flag, don't think we need to care about that?
        // data[3] is the length of the address, which we can ignore since the rest of the payload is the address
        return .{
            .address = data[4..],
            .netmask = data[1],
            .family = if (data.len == 20) .v6 else .v4,
        };
    }
};
