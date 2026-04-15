// Used internall by files in this folder like a "utils". Underscore filename
// because I like having this clearly separate in the file view. Would be nice
// if editors let you override file ordering.
const std = @import("std");

pub const Buffer = @import("buffer").Buffer;
pub const testing = @import("../lib.zig").testing;

pub const Reader = struct {
    pos: usize,
    data: []const u8,

    pub fn init(data: []const u8) Reader {
        return .{
            .pos = 0,
            .data = data,
        };
    }

    pub fn byte(self: *Reader) !u8 {
        if (!self.hasAtLeast(1)) {
            return error.NoMoreData;
        }
        const pos = self.pos;
        const value = self.data[pos];
        self.pos = pos + 1;
        return value;
    }

    pub fn optionalString(self: *Reader) ?[]const u8 {
        const pos = self.pos;
        const data = self.data;
        const index = std.mem.indexOfScalarPos(u8, data, pos, 0) orelse return null;

        const value = data[pos..index];
        self.pos = index + 1; // +1 to consume the null terminator
        return value;
    }

    pub fn string(self: *Reader) ![]const u8 {
        if (!self.hasAtLeast(1)) {
            return error.NoMoreData;
        }
        return self.optionalString() orelse return error.NotAString;
    }

    pub fn int16(self: *Reader) !u16 {
        if (!self.hasAtLeast(2)) {
            return error.NoMoreData;
        }
        const pos = self.pos;
        const end = pos + 2;
        const value = std.mem.readInt(u16, self.data[pos..end][0..2], .big);
        self.pos = end;
        return value;
    }

    pub fn int32(self: *Reader) !u32 {
        if (!self.hasAtLeast(4)) {
            return error.NoMoreData;
        }
        const pos = self.pos;
        const end = pos + 4;
        const value = std.mem.readInt(u32, self.data[pos..end][0..4], .big);
        self.pos = end;
        return value;
    }

    // does not consume
    pub fn rest(self: *Reader) []const u8 {
        return self.data[self.pos..];
    }

    pub fn restAsString(self: *Reader) ![]const u8 {
        const r = self.data[self.pos..];
        if (r[r.len - 1] != 0) {
            return error.NotAString;
        }
        return r[0 .. r.len - 1];
    }

    pub fn hasAtLeast(self: Reader, n: usize) bool {
        return self.pos + n <= self.data.len;
    }
};
