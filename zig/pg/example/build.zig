const std = @import("std");

pub fn build(b: *std.Build) void {
	const target = b.standardTargetOptions(.{});
	const optimize = b.standardOptimizeOption(.{});

	const pg_module = b.dependency("pg", .{}).module("pg");

	const exe = b.addExecutable(.{
		.name = "example",
        .root_module = b.createModule(.{
            .root_source_file = b.path("main.zig"),
            .target = target,
            .optimize = optimize,
            .imports = &.{
                .{ .name = "pg", .module = pg_module },
            },
        }),
	});

	b.installArtifact(exe);

	const run_cmd = b.addRunArtifact(exe);
	run_cmd.step.dependOn(b.getInstallStep());
	const run_step = b.step("run", "Run the app");
	run_step.dependOn(&run_cmd.step);
}
