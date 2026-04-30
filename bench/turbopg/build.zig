const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const iouring = b.option(bool, "iouring", "Use io_uring transport") orelse false;

    const pg_dep = b.dependency("pg", .{
        .target = target,
        .optimize = optimize,
        .iouring = iouring,
    });

    const exe = b.addExecutable(.{
        .name = "turbopg-bench",
        .root_module = b.createModule(.{
            .target = target,
            .optimize = optimize,
            .root_source_file = b.path("bench.zig"),
            .link_libc = true,
            .imports = &.{
                .{ .name = "pg", .module = pg_dep.module("pg") },
            },
        }),
    });

    b.installArtifact(exe);
    const run_cmd = b.addRunArtifact(exe);
    run_cmd.step.dependOn(b.getInstallStep());
    if (b.args) |args| run_cmd.addArgs(args);
    const run_step = b.step("run", "Run the bench");
    run_step.dependOn(&run_cmd.step);
}
