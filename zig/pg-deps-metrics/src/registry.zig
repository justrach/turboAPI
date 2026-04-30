const std = @import("std");

// Not sure what I want to do about a "registry"
// But I think I want to wait until comptime allocation is available

pub const Opts = struct {
    prefix: []const u8 = "",
    exclude: ?[]const []const u8 = null,

    pub fn shouldExclude(self: Opts, name: []const u8) bool {
        const excludes = self.exclude orelse return false;
        for (excludes) |exclude| {
            if (std.mem.eql(u8, exclude, name)) {
                return true;
            }
        }
        return false;
    }
};

const t = @import("t.zig");
test "Registry.Opts: shouldExclude" {
    try t.expectEqual(false, (Opts{}).shouldExclude("abc"));
    try t.expectEqual(false, (Opts{ .exclude = &.{ "ABC", "other" } }).shouldExclude("abc"));
    try t.expectEqual(true, (Opts{ .exclude = &.{ "abc", "other" } }).shouldExclude("abc"));
    try t.expectEqual(true, (Opts{ .exclude = &.{ "a", "otaher", "abc" } }).shouldExclude("abc"));
}
