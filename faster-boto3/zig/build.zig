const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const py_include = b.option([]const u8, "py-include", "Python include path") orelse "/usr/include/python3.13";
    const py_libdir = b.option([]const u8, "py-libdir", "Python lib path") orelse "/usr/lib";

    // ── SigV4 accelerator ───────────────────────────────────────────
    const sigv4_mod = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });

    const sigv4_lib = b.addLibrary(.{
        .name = "sigv4_accel",
        .root_module = sigv4_mod,
        .linkage = .dynamic,
    });

    sigv4_lib.addIncludePath(.{ .cwd_relative = py_include });
    sigv4_lib.addLibraryPath(.{ .cwd_relative = py_libdir });
    sigv4_lib.linkLibC();
    sigv4_lib.linker_allow_shlib_undefined = true;
    b.installArtifact(sigv4_lib);

    // ── HTTP client accelerator ─────────────────────────────────────
    const http_mod = b.createModule(.{
        .root_source_file = b.path("src/http_py.zig"),
        .target = target,
        .optimize = optimize,
    });

    const http_lib = b.addLibrary(.{
        .name = "http_accel",
        .root_module = http_mod,
        .linkage = .dynamic,
    });

    http_lib.addIncludePath(.{ .cwd_relative = py_include });
    http_lib.addLibraryPath(.{ .cwd_relative = py_libdir });
    http_lib.linkLibC();
    http_lib.linker_allow_shlib_undefined = true;
    b.installArtifact(http_lib);

    // ── SIMD parser accelerator ─────────────────────────────────────
    const parser_mod = b.createModule(.{
        .root_source_file = b.path("src/parser_py.zig"),
        .target = target,
        .optimize = optimize,
    });

    const parser_lib = b.addLibrary(.{
        .name = "parser_accel",
        .root_module = parser_mod,
        .linkage = .dynamic,
    });

    parser_lib.addIncludePath(.{ .cwd_relative = py_include });
    parser_lib.addLibraryPath(.{ .cwd_relative = py_libdir });
    parser_lib.linkLibC();
    parser_lib.linker_allow_shlib_undefined = true;
    b.installArtifact(parser_lib);

    // ── Tests ───────────────────────────────────────────────────────
    const test_mod = b.createModule(.{
        .root_source_file = b.path("src/sigv4.zig"),
        .target = target,
        .optimize = optimize,
    });
    const tests = b.addTest(.{ .root_module = test_mod });
    const run_tests = b.addRunArtifact(tests);
    b.step("test", "Run SigV4 tests").dependOn(&run_tests.step);

    const parser_test_mod = b.createModule(.{
        .root_source_file = b.path("src/simd_parser.zig"),
        .target = target,
        .optimize = optimize,
    });
    const parser_tests = b.addTest(.{ .root_module = parser_test_mod });
    const run_parser_tests = b.addRunArtifact(parser_tests);
    b.step("test-parser", "Run SIMD parser tests").dependOn(&run_parser_tests.step);
}
