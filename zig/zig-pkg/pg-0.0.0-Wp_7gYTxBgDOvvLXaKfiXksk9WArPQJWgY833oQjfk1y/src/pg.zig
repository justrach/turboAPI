const std = @import("std");
const lib = @import("lib.zig");

pub const Row = lib.Row;
pub const Conn = lib.Conn;
pub const Pool = lib.Pool;
pub const Stmt = lib.Stmt;
pub const Result = lib.Result;
pub const Iterator = lib.Iterator;
pub const QueryRow = lib.QueryRow;
pub const Mapper = lib.Mapper;
pub const Binary = lib.Binary;

pub const Listener = @import("listener.zig").Listener;

pub const types = lib.types;
pub const DynamicValue = types.DynamicValue;
pub const Cidr = types.Cidr;
pub const Numeric = types.Numeric;
pub const Vector = types.Vector;
pub const Error = lib.proto.Error;
pub const printSSLError = lib.printSSLError;

pub fn uuidToHex(uuid: []const u8) ![36]u8 {
    return lib.types.UUID.toString(uuid);
}

pub fn writeMetrics(writer: anytype) !void {
    return @import("metrics.zig").write(writer);
}

const t = lib.testing;
test {
    try t.setup();
    std.testing.refAllDecls(@This());
}

test "pg: uuidToHex" {
    try t.expectError(error.InvalidUUID, uuidToHex(&.{ 73, 190, 142, 9, 170, 250, 176, 16, 73, 21 }));

    const s = try uuidToHex(&.{ 183, 204, 40, 47, 236, 67, 73, 190, 142, 9, 170, 250, 176, 16, 73, 21 });
    try t.expectString("b7cc282f-ec43-49be-8e09-aafab0104915", &s);
}
