const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    // Create validator module
    const validator_mod = b.addModule("validator", .{
        .root_source_file = b.path("src/validator.zig"),
    });

    const combinators_mod = b.addModule("combinators", .{
        .root_source_file = b.path("src/combinators.zig"),
    });
    combinators_mod.addImport("validator", validator_mod);
    const json_validator_mod = b.addModule("json_validator", .{
        .root_source_file = b.path("src/json_validator.zig"),
    });
    json_validator_mod.addImport("validator", validator_mod);

    // Create SIMD JSON parser module
    const simd_json_mod = b.addModule("simd_json_parser", .{
        .root_source_file = b.path("src/simd_json_parser.zig"),
    });

    // Creates a step for building the library
    const lib = b.addLibrary(.{
        .name = "dhi-zig",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/root.zig"),
            .target = target,
            .optimize = optimize,
        }),
        .linkage = .static,
    });
    lib.root_module.addImport("validator", validator_mod);
    lib.root_module.addImport("combinators", combinators_mod);
    lib.root_module.addImport("json_validator", json_validator_mod);

    b.installArtifact(lib);

    // Build shared library for Python bindings
    const c_lib = b.addLibrary(.{
        .name = "dhi",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/c_api.zig"),
            .target = target,
            .optimize = optimize,
        }),
        .linkage = .dynamic,
    });
    c_lib.root_module.addImport("validator", validator_mod);
    c_lib.root_module.addImport("simd_json_parser", simd_json_mod);
    b.installArtifact(c_lib);

    // Build WASM library for JavaScript bindings
    const wasm_lib = b.addExecutable(.{
        .name = "dhi",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/wasm_api.zig"),
            .target = b.resolveTargetQuery(.{
                .cpu_arch = .wasm32,
                .os_tag = .freestanding,
            }),
            .optimize = optimize,
        }),
    });
    wasm_lib.entry = .disabled;
    wasm_lib.rdynamic = true;
    b.installArtifact(wasm_lib);

    // Build N-API native addon for Node.js
    const node_include = b.option([]const u8, "node_include", "Path to Node.js include directory for N-API") orelse "";

    if (node_include.len > 0) {
        const validators_comprehensive_mod = b.addModule("validators_comprehensive", .{
            .root_source_file = b.path("src/validators_comprehensive.zig"),
        });

        const napi_lib = b.addLibrary(.{
            .name = "dhi_native",
            .root_module = b.createModule(.{
                .root_source_file = b.path("src/napi_api.zig"),
                .target = target,
                .optimize = optimize,
            }),
            .linkage = .dynamic,
        });
        napi_lib.root_module.addIncludePath(.{ .cwd_relative = node_include });
        napi_lib.root_module.addImport("validators_comprehensive", validators_comprehensive_mod);
        // Link against libc (required on macOS/Linux for N-API)
        napi_lib.root_module.link_libc = true;
        // N-API symbols are resolved at runtime by Node.js - allow undefined symbols
        napi_lib.linker_allow_shlib_undefined = true;
        b.installArtifact(napi_lib);
    }

    // Create model module (Pydantic-style API)
    const model_mod = b.addModule("model", .{
        .root_source_file = b.path("src/model.zig"),
    });

    // Export module for use as a dependency (no target/optimize — inherited from consumer)
    const dhi_module = b.addModule("dhi", .{
        .root_source_file = b.path("src/root.zig"),
    });
    dhi_module.addImport("validator", validator_mod);
    dhi_module.addImport("combinators", combinators_mod);
    dhi_module.addImport("json_validator", json_validator_mod);

    // Example: basic_usage
    const basic_example = b.addExecutable(.{
        .name = "basic_usage",
        .root_module = b.createModule(.{
            .root_source_file = b.path("examples/basic_usage.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    basic_example.root_module.addImport("validator", validator_mod);
    basic_example.root_module.addImport("combinators", combinators_mod);

    const run_basic = b.addRunArtifact(basic_example);
    const basic_step = b.step("run-basic", "Run basic usage example");
    basic_step.dependOn(&run_basic.step);

    // Example: json_example
    const json_example = b.addExecutable(.{
        .name = "json_example",
        .root_module = b.createModule(.{
            .root_source_file = b.path("examples/json_example.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    json_example.root_module.addImport("validator", validator_mod);
    json_example.root_module.addImport("json_validator", json_validator_mod);

    const run_json = b.addRunArtifact(json_example);
    const json_step = b.step("run-json", "Run JSON validation example");
    json_step.dependOn(&run_json.step);

    // Example: advanced_example
    const advanced_example = b.addExecutable(.{
        .name = "advanced_example",
        .root_module = b.createModule(.{
            .root_source_file = b.path("examples/advanced_example.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    advanced_example.root_module.addImport("validator", validator_mod);
    advanced_example.root_module.addImport("combinators", combinators_mod);
    advanced_example.root_module.addImport("json_validator", json_validator_mod);

    const run_advanced = b.addRunArtifact(advanced_example);
    const advanced_step = b.step("run-advanced", "Run advanced validation example");
    advanced_step.dependOn(&run_advanced.step);

    // Example: model_example (Pydantic-style API)
    const model_example = b.addExecutable(.{
        .name = "model_example",
        .root_module = b.createModule(.{
            .root_source_file = b.path("examples/model_example.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    model_example.root_module.addImport("model", model_mod);

    const run_model = b.addRunArtifact(model_example);
    const model_step = b.step("run-model", "Run Pydantic-style model example");
    model_step.dependOn(&run_model.step);

    // Run all examples
    const run_all = b.step("run-all", "Run all examples");
    run_all.dependOn(&run_basic.step);
    run_all.dependOn(&run_json.step);
    run_all.dependOn(&run_advanced.step);
    run_all.dependOn(&run_model.step);

    // Tests for validator module
    const validator_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/validator.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });

    const run_validator_tests = b.addRunArtifact(validator_tests);

    // Tests for combinators module
    const combinators_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/combinators.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    combinators_tests.root_module.addImport("validator", validator_mod);

    const run_combinators_tests = b.addRunArtifact(combinators_tests);

    // Tests for json_validator module
    const json_validator_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/json_validator.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    json_validator_tests.root_module.addImport("validator", validator_mod);

    const run_json_validator_tests = b.addRunArtifact(json_validator_tests);

    // Tests for model module (Pydantic-style API)
    const model_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/model.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });

    const run_model_tests = b.addRunArtifact(model_tests);

    // Tests for SIMD JSON parser module
    const simd_json_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/simd_json_parser.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });

    const run_simd_json_tests = b.addRunArtifact(simd_json_tests);

    // Test step runs all tests
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&run_validator_tests.step);
    test_step.dependOn(&run_combinators_tests.step);
    test_step.dependOn(&run_json_validator_tests.step);
    test_step.dependOn(&run_model_tests.step);
    test_step.dependOn(&run_simd_json_tests.step);

    // Benchmark executable
    const benchmark = b.addExecutable(.{
        .name = "benchmark",
        .root_module = b.createModule(.{
            .root_source_file = b.path("benchmarks/benchmark.zig"),
            .target = target,
            .optimize = .ReleaseFast,
        }),
    });
    benchmark.root_module.addImport("validator", validator_mod);
    benchmark.root_module.addImport("combinators", combinators_mod);
    benchmark.root_module.addImport("json_validator", json_validator_mod);

    const run_benchmark = b.addRunArtifact(benchmark);
    const bench_step = b.step("bench", "Run performance benchmarks");
    bench_step.dependOn(&run_benchmark.step);
}
