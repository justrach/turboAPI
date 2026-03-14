const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // ── Python configuration ──
    // Normally auto-detected by build_turbonet.py; can also be set manually.
    const py_version = b.option([]const u8, "python", "Python label: 3.13, 3.14, or 3.14t") orelse "3.13";
    const is_free_threaded = std.mem.eql(u8, py_version, "3.14t");

    const include_path = b.option([]const u8, "py-include", "Python include path (required)") orelse
        @panic("pass -Dpy-include=<path> or use: python zig/build_turbonet.py");
    const lib_path = b.option([]const u8, "py-libdir", "Python lib path (required)") orelse
        @panic("pass -Dpy-libdir=<path> or use: python zig/build_turbonet.py");

    const py_lib_name: []const u8 = if (is_free_threaded)
        "python3.14t"
    else if (std.mem.eql(u8, py_version, "3.14"))
        "python3.14"
    else
        "python3.13";

    // ── dhi modules ──
    const dhi_path = b.option([]const u8, "dhi-path", "Path to dhi repository (or set DHI_PATH env)") orelse
        @panic("pass -Ddhi-path=<path> or set DHI_PATH env var");
    const dhi_root: std.Build.LazyPath = .{ .cwd_relative = dhi_path };

    const validator_mod = b.createModule(.{
        .root_source_file = dhi_root.path(b, "src/validator.zig"),
        .target = target,
        .optimize = optimize,
    });

    const json_validator_mod = b.createModule(.{
        .root_source_file = dhi_root.path(b, "src/json_validator.zig"),
        .target = target,
        .optimize = optimize,
    });
    json_validator_mod.addImport("validator", validator_mod);

    const validators_comprehensive_mod = b.createModule(.{
        .root_source_file = dhi_root.path(b, "src/validators_comprehensive.zig"),
        .target = target,
        .optimize = optimize,
    });

    const model_mod = b.createModule(.{
        .root_source_file = dhi_root.path(b, "src/model.zig"),
        .target = target,
        .optimize = optimize,
    });
    model_mod.addImport("validators_comprehensive", validators_comprehensive_mod);

    // ── shared library (turbonet) ──
    const lib = b.addLibrary(.{
        .name = "turbonet",
        .linkage = .dynamic,
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
            .link_libc = true,
        }),
    });

    lib.root_module.addImport("validator", validator_mod);
    lib.root_module.addImport("json_validator", json_validator_mod);
    lib.root_module.addImport("validators_comprehensive", validators_comprehensive_mod);
    lib.root_module.addImport("model", model_mod);

    lib.addIncludePath(.{ .cwd_relative = include_path });
    lib.root_module.addRPathSpecial("@loader_path");

    if (is_free_threaded) {
        // Free-threaded: link libpython + atomic shim
        lib.addLibraryPath(.{ .cwd_relative = lib_path });
        lib.linkSystemLibrary(py_lib_name);
        lib.addCSourceFile(.{
            .file = b.path("src/py_atomic_shim.c"),
            .flags = &.{ "-I", include_path },
        });
    } else {
        // Standard: allow undefined (symbols resolve at import time)
        lib.linker_allow_shlib_undefined = true;
    }

    b.installArtifact(lib);

    // ── unit tests ──
    const tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
            .link_libc = true,
        }),
    });
    tests.root_module.addImport("validator", validator_mod);
    tests.root_module.addImport("json_validator", json_validator_mod);
    tests.root_module.addImport("validators_comprehensive", validators_comprehensive_mod);
    tests.root_module.addImport("model", model_mod);

    tests.addIncludePath(.{ .cwd_relative = include_path });
    tests.addLibraryPath(.{ .cwd_relative = lib_path });
    tests.linkSystemLibrary(py_lib_name);

    if (is_free_threaded) {
        tests.addCSourceFile(.{
            .file = b.path("src/py_atomic_shim.c"),
            .flags = &.{ "-I", include_path },
        });
    }

    const run_tests = b.addRunArtifact(tests);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&run_tests.step);
}
