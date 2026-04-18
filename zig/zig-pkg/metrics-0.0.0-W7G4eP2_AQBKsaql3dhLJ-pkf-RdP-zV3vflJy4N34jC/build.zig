const std = @import("std");

pub fn build(b: *std.Build) !void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const metrics_module = b.addModule("metrics", .{
        .root_source_file = b.path("src/metrics.zig"),
        .target = target,
        .optimize = optimize,
    });

    {
        // setup example
        const example_module = b.createModule(.{
            .root_source_file = b.path("example/main.zig"),
            .target = target,
            .optimize = optimize,
        });
        const example = b.addExecutable(.{
            .name = "metrics demo",
            .root_module = example_module,
        });
        example.root_module.addImport("metrics", metrics_module);
        b.installArtifact(example);

        const run_example_cmd = b.addRunArtifact(example);
        run_example_cmd.step.dependOn(b.getInstallStep());
        if (b.args) |args| {
            run_example_cmd.addArgs(args);
        }
        const run_step = b.step("run", "Run the app");
        run_step.dependOn(&run_example_cmd.step);
    }

    {
        // setup tests
        const lib_test = b.addTest(.{
            .root_module = metrics_module,
            .test_runner = .{ .path = b.path("test_runner.zig"), .mode = .simple },
        });
        const run_test = b.addRunArtifact(lib_test);
        run_test.has_side_effects = true;

        const test_step = b.step("test", "Run tests");
        test_step.dependOn(&run_test.step);
    }
}
