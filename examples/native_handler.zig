//! Example native FFI handler for TurboAPI.
//! Compile: zig build-lib -dynamic -OReleaseFast native_handler.zig
//! Register: app.native_route("GET", "/native/health", "./libnative_handler.dylib", "handle_health")

const std = @import("std");

// ── FFI types (matching turboapi_ffi.h) ──

const Request = extern struct {
    method: [*c]const u8,
    method_len: usize,
    path: [*c]const u8,
    path_len: usize,
    query_string: [*c]const u8,
    query_len: usize,
    body: [*c]const u8,
    body_len: usize,
    header_names: [*c]const [*c]const u8,
    header_name_lens: [*c]const usize,
    header_values: [*c]const [*c]const u8,
    header_value_lens: [*c]const usize,
    header_count: usize,
    param_names: [*c]const [*c]const u8,
    param_name_lens: [*c]const usize,
    param_values: [*c]const [*c]const u8,
    param_value_lens: [*c]const usize,
    param_count: usize,
};

const Response = extern struct {
    status_code: u16,
    content_type: [*c]const u8,
    content_type_len: usize,
    body: [*c]const u8,
    body_len: usize,
};

// ── Handlers ──

export fn handle_health(_: *const Request) callconv(.c) Response {
    const body = "{\"status\":\"ok\",\"engine\":\"zig-native\"}";
    return .{
        .status_code = 200,
        .content_type = "application/json",
        .content_type_len = 16,
        .body = body,
        .body_len = body.len,
    };
}

export fn handle_echo(req: *const Request) callconv(.c) Response {
    // Echo back the request body — zero-copy, body is valid for the request lifetime
    return .{
        .status_code = 200,
        .content_type = "application/json",
        .content_type_len = 16,
        .body = req.body,
        .body_len = req.body_len,
    };
}

// Optional init function
export fn turboapi_init() callconv(.c) c_int {
    std.debug.print("[NATIVE] Handler library loaded\n", .{});
    return 0;
}
