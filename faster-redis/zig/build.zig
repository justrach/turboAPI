const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const py_include = b.option([]const u8, "py-include", "Python include path") orelse "/usr/include/python3.13";
    const py_libdir = b.option([]const u8, "py-libdir", "Python lib path") orelse "/usr/lib";

    const mod = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });

    const lib = b.addLibrary(.{
        .name = "redis_accel",
        .root_module = mod,
        .linkage = .dynamic,
    });

    lib.addIncludePath(.{ .cwd_relative = py_include });
    lib.addLibraryPath(.{ .cwd_relative = py_libdir });
    lib.linkLibC();
    lib.linker_allow_shlib_undefined = true;
    b.installArtifact(lib);

    // Tests
    const test_mod = b.createModule(.{
        .root_source_file = b.path("src/resp.zig"),
        .target = target,
        .optimize = optimize,
    });
    const tests = b.addTest(.{ .root_module = test_mod });
    b.step("test", "Run RESP parser tests").dependOn(&b.addRunArtifact(tests).step);
}
