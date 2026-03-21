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
        .name = "sigv4_accel",
        .root_module = mod,
        .linkage = .dynamic,
    });

    lib.addIncludePath(.{ .cwd_relative = py_include });
    lib.addLibraryPath(.{ .cwd_relative = py_libdir });
    lib.linkLibC();
    // Python symbols resolve at import time
    lib.linker_allow_shlib_undefined = true;

    b.installArtifact(lib);

    // Tests (no Python dependency)
    const test_mod = b.createModule(.{
        .root_source_file = b.path("src/sigv4.zig"),
        .target = target,
        .optimize = optimize,
    });
    const tests = b.addTest(.{ .root_module = test_mod });
    const run_tests = b.addRunArtifact(tests);
    b.step("test", "Run SigV4 tests").dependOn(&run_tests.step);
}
