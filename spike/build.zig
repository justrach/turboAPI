const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const nanoapi_dep = b.dependency("nanoapi", .{
        .target = target,
        .optimize = optimize,
    });
    const nanoapi_mod = nanoapi_dep.module("nanoapi");

    const spike = b.addExecutable(.{
        .name = "spike",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
            .link_libc = true,
        }),
    });
    spike.root_module.addImport("nanoapi", nanoapi_mod);
    b.installArtifact(spike);

    const run_spike = b.addRunArtifact(spike);
    const spike_step = b.step("run", "Run nanoapi runtime-layer spike");
    spike_step.dependOn(&run_spike.step);
}
