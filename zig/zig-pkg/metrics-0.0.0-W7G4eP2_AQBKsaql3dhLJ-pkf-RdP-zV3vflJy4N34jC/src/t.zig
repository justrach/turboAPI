const std = @import("std");

pub const allocator = std.testing.allocator;

pub const expectEqual = std.testing.expectEqual;
pub const expectFmt = std.testing.expectFmt;
pub const expectError = std.testing.expectError;
pub const expectSlice = std.testing.expectEqualSlices;
pub const expectString = std.testing.expectEqualStrings;

// a structure with all the label types we supprot
pub const AllLabels = struct {
    id: i32,
    key: u13,
    active: bool,
    err: anyerror,
    state: State,
    tag: []const u8,

    const State = enum {
        start,
        end,
    };
};
