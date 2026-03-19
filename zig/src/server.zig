// TurboServer – Zig HTTP server core.
// Placeholder that registers routes and runs an event loop.
// The actual HTTP serving uses Zig's std.net / std.http.

const std = @import("std");
const py = @import("py.zig");
const c = py.c;
const router_mod = @import("router.zig");
const dhi = @import("dhi_validator.zig");
const db = @import("db.zig");

const allocator = std.heap.c_allocator;

// ── Route storage ───────────────────────────────────────────────────────────

const MAX_PARAMS: usize = 16;

const ParamType = enum(u8) { str, int, float, bool_val };

const ParamMeta = struct {
    name: []const u8,
    type_tag: ParamType,
    has_default: bool, // true → skip if missing (let Python use its own default)
};

fn parseParamType(s: []const u8) ParamType {
    if (std.mem.eql(u8, s, "int")) return .int;
    if (std.mem.eql(u8, s, "float")) return .float;
    if (std.mem.eql(u8, s, "bool")) return .bool_val;
    return .str;
}

/// Parse "name:type|name:type|..." into out[]. Returns count of parsed params.
/// Slices point into meta_str, so meta_str must outlive the result.
/// Parse "name:type[?]|name:type[?]|..." into out[]. Returns count of parsed params.
/// '?' suffix on type means the param has a Python default — skip if missing.
/// Slices point into meta_str, so meta_str must outlive the result.
fn parseParamMeta(meta_str: []const u8, out: *[MAX_PARAMS]ParamMeta) usize {
    if (meta_str.len == 0) return 0;
    var count: usize = 0;
    var it = std.mem.splitScalar(u8, meta_str, '|');
    while (it.next()) |pair| {
        if (pair.len == 0 or count >= MAX_PARAMS) break;
        const colon = std.mem.indexOfScalar(u8, pair, ':') orelse continue;
        var type_str = pair[colon + 1 ..];
        const has_default = type_str.len > 0 and type_str[type_str.len - 1] == '?';
        if (has_default) type_str = type_str[0 .. type_str.len - 1];
        out[count] = .{
            .name = pair[0..colon],
            .type_tag = parseParamType(type_str),
            .has_default = has_default,
        };
        count += 1;
    }
    return count;
}

/// Fast query-string value lookup. Format: "k1=v1&k2=v2&...".
/// No percent-decoding (fine for int/float/simple str params in hot path).
/// Fast query-string value lookup. Format: "k1=v1&k2=v2&...".
fn queryStringGet(qs: []const u8, key: []const u8) ?[]const u8 {
    var it = std.mem.splitScalar(u8, qs, '&');
    while (it.next()) |pair| {
        const eq = std.mem.indexOfScalar(u8, pair, '=') orelse continue;
        if (std.mem.eql(u8, pair[0..eq], key)) return pair[eq + 1 ..];
    }
    return null;
}

fn hexNibble(ch: u8) ?u8 {
    return switch (ch) {
        '0'...'9' => ch - '0',
        'a'...'f' => ch - 'a' + 10,
        'A'...'F' => ch - 'A' + 10,
        else => null,
    };
}

/// Percent-decode src into buf. '+' → space, '%XX' → byte. Returns decoded slice.
/// If buf is too small, copies as many bytes as fit (safe truncation).
fn percentDecode(src: []const u8, buf: []u8) []u8 {
    var out: usize = 0;
    var i: usize = 0;
    while (i < src.len and out < buf.len) {
        if (src[i] == '+') {
            buf[out] = ' ';
            out += 1;
            i += 1;
        } else if (src[i] == '%' and i + 2 < src.len) {
            const hi = hexNibble(src[i + 1]);
            const lo = hexNibble(src[i + 2]);
            if (hi != null and lo != null) {
                buf[out] = (hi.? << 4) | lo.?;
                out += 1;
                i += 3;
            } else {
                buf[out] = src[i];
                out += 1;
                i += 1;
            }
        } else {
            buf[out] = src[i];
            out += 1;
            i += 1;
        }
    }
    return buf[0..out];
}

const HandlerType = enum(u8) {
    simple_sync_noargs,
    simple_sync,
    model_sync,
    body_sync,
    enhanced,
};

fn parseHandlerType(s: []const u8) HandlerType {
    if (std.mem.eql(u8, s, "simple_sync_noargs")) return .simple_sync_noargs;
    if (std.mem.eql(u8, s, "simple_sync")) return .simple_sync;
    if (std.mem.eql(u8, s, "model_sync")) return .model_sync;
    if (std.mem.eql(u8, s, "body_sync")) return .body_sync;
    return .enhanced;
}

const HandlerEntry = struct {
    handler: *c.PyObject,
    handler_type: []const u8,
    handler_tag: HandlerType = .enhanced,
    param_types_json: []const u8,
    original_handler: ?*c.PyObject,
    model_param_name: ?[]const u8,
    model_class: ?*c.PyObject,
    // Vectorcall dispatch: ordered param metadata parsed at registration time
    param_meta: [MAX_PARAMS]ParamMeta = undefined,
    param_count: usize = 0,
};

const HeaderPair = struct {
    name: []const u8,
    value: []const u8,
};

const PythonResponse = struct {
    status_code: u16,
    content_type: []const u8,
    body: []const u8,
    ct_owned: bool = true,

    fn deinit(self: PythonResponse) void {
        if (self.ct_owned and self.content_type.len > 0) allocator.free(self.content_type);
        if (self.body.len > 0) allocator.free(self.body);
    }
};

// ── FFI native handler types (matching turboapi_ffi.h) ──────────────────────

const FfiRequest = extern struct {
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

const FfiResponse = extern struct {
    status_code: u16,
    content_type: [*c]const u8,
    content_type_len: usize,
    body: [*c]const u8,
    body_len: usize,
};

const NativeHandlerFn = *const fn (*const FfiRequest) callconv(.c) FfiResponse;
const NativeInitFn = *const fn () callconv(.c) c_int;

const NativeHandlerEntry = struct {
    handler_fn: NativeHandlerFn,
    lib_handle: *anyopaque,
};
// ── Static route entry — pre-rendered response bytes, zero runtime overhead ──

const StaticRouteEntry = struct {
    response_bytes: []const u8, // complete HTTP response, ready to writeAll
};

var routes: ?std.StringHashMap(HandlerEntry) = null;
var native_routes: ?std.StringHashMap(NativeHandlerEntry) = null;
var static_routes: ?std.StringHashMap(StaticRouteEntry) = null;
var response_cache: ?std.StringHashMap([]const u8) = null;
var response_cache_count: usize = 0;
const MAX_CACHE_ENTRIES: usize = 10_000; // bounded to prevent OOM via unique paths
var model_schemas: ?std.StringHashMap(dhi.ModelSchema) = null;
var router: ?router_mod.Router = null;
var server_host: []const u8 = "127.0.0.1";
var server_port: u16 = 8000;
var cache_noargs_responses: bool = false;

// Interpreter reference captured before releasing the GIL at server start.
// Workers use this to create their own PyThreadState rather than calling
// PyGILState_Ensure (which pays a per-call thread-state lookup cost).
var py_interp: ?*anyopaque = null;

fn getRoutes() *std.StringHashMap(HandlerEntry) {
    if (routes == null) {
        routes = std.StringHashMap(HandlerEntry).init(allocator);
    }
    return &routes.?;
}

fn getNativeRoutes() *std.StringHashMap(NativeHandlerEntry) {
    if (native_routes == null) {
        native_routes = std.StringHashMap(NativeHandlerEntry).init(allocator);
    }
    return &native_routes.?;
}

fn getStaticRoutes() *std.StringHashMap(StaticRouteEntry) {
    if (static_routes == null) {
        static_routes = std.StringHashMap(StaticRouteEntry).init(allocator);
    }
    return &static_routes.?;
}

fn getResponseCache() *std.StringHashMap([]const u8) {
    if (response_cache == null) {
        response_cache = std.StringHashMap([]const u8).init(allocator);
    }
    return &response_cache.?;
}

/// Cache a pre-rendered response, respecting MAX_CACHE_ENTRIES to prevent OOM.
fn cacheResponse(key: []const u8, rendered: []const u8) void {
    if (response_cache_count >= MAX_CACHE_ENTRIES) return; // bounded — reject when full
    const key_dupe = allocator.dupe(u8, key) catch return;
    getResponseCache().put(key_dupe, rendered) catch {
        allocator.free(rendered);
        allocator.free(key_dupe);
        return;
    };
    response_cache_count += 1;
}

fn getModelSchemas() *std.StringHashMap(dhi.ModelSchema) {
    if (model_schemas == null) {
        model_schemas = std.StringHashMap(dhi.ModelSchema).init(allocator);
    }
    return &model_schemas.?;
}

pub fn getRouter() *router_mod.Router {
    if (router == null) {
        router = router_mod.Router.init(allocator);
    }
    return &router.?;
}

// ── server_new(host, port) -> state dict ────────────────────────────────────

pub fn server_new(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var host: [*c]const u8 = "127.0.0.1";
    var port: c_long = 8000;

    if (args) |a| {
        const n = c.PyTuple_Size(a);
        if (n >= 1) {
            const h = c.PyTuple_GetItem(a, 0);
            if (h) |item| {
                if (c.PyUnicode_Check(item) != 0) {
                    host = c.PyUnicode_AsUTF8(item) orelse "127.0.0.1";
                }
            }
        }
        if (n >= 2) {
            const p = c.PyTuple_GetItem(a, 1);
            if (p) |item| {
                if (c.PyLong_Check(item) != 0) {
                    port = c.PyLong_AsLong(item);
                }
            }
        }
    }

    // Validate port range before truncating to u16
    if (port < 1 or port > 65535) {
        py.setError("port must be in range 1-65535, got {d}", .{port});
        return null;
    }

    // Dupe the host string — the Python string's internal buffer may be freed
    // by the GC once the Python object is collected.
    server_host = allocator.dupe(u8, std.mem.span(host)) catch "127.0.0.1";
    server_port = @intCast(port);

    // Eagerly initialize all globals — workers must never hit the lazy-init
    // path, which has a check-then-act race condition.
    _ = getRoutes();
    _ = getNativeRoutes();
    _ = getStaticRoutes();
    _ = getResponseCache();
    _ = getModelSchemas();
    _ = getRouter();
    // Return a state dict
    const d = c.PyDict_New() orelse return null;
    const h_obj = c.PyUnicode_FromString(host) orelse return null;
    _ = c.PyDict_SetItemString(d, "host", h_obj);
    c.Py_DecRef(h_obj);
    const p_obj = c.PyLong_FromLong(@intCast(port)) orelse return null;
    _ = c.PyDict_SetItemString(d, "port", p_obj);
    c.Py_DecRef(p_obj);
    return d;
}

// ── add_route(method, path, handler) ────────────────────────────────────────

pub fn server_add_route(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var method: [*c]const u8 = null;
    var path: [*c]const u8 = null;
    var handler: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "ssO", &method, &path, &handler) == 0) return null;

    c.Py_IncRef(handler.?);
    const method_s = std.mem.span(method);
    const path_s = std.mem.span(path);
    const key = std.fmt.allocPrint(allocator, "{s} {s}", .{ method_s, path_s }) catch return null;
    getRoutes().put(key, .{
        .handler = handler.?,
        .handler_type = "enhanced",
        .handler_tag = .enhanced,
        .param_types_json = "{}",
        .original_handler = null,
        .model_param_name = null,
        .model_class = null,
    }) catch return null;
    getRouter().addRoute(method_s, path_s, key) catch return null;

    return py.pyNone();
}

// ── add_route_fast(method, path, handler, handler_type, param_types_json, original) ──

pub fn server_add_route_fast(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var method: [*c]const u8 = null;
    var path: [*c]const u8 = null;
    var handler: ?*c.PyObject = null;
    var ht: [*c]const u8 = null;
    var ptj: [*c]const u8 = null;
    var orig: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "ssOssO", &method, &path, &handler, &ht, &ptj, &orig) == 0) return null;

    c.Py_IncRef(handler.?);
    c.Py_IncRef(orig.?);
    const method_s = std.mem.span(method);
    const path_s = std.mem.span(path);

    // Dupe handler_type and param_types_json — the Python string's internal buffer
    // becomes a dangling pointer once the Python object is collected.
    const ht_s = allocator.dupe(u8, std.mem.span(ht)) catch return null;
    const ptj_s = allocator.dupe(u8, std.mem.span(ptj)) catch {
        allocator.free(ht_s);
        return null;
    };
    const key = std.fmt.allocPrint(allocator, "{s} {s}", .{ method_s, path_s }) catch {
        allocator.free(ht_s);
        allocator.free(ptj_s);
        return null;
    };

    // For simple_sync: parse "name:type|..." metadata into ordered ParamMeta array.
    // Slices in param_meta point into ptj_s which we own.
    var entry = HandlerEntry{
        .handler = handler.?,
        .handler_type = ht_s,
        .handler_tag = parseHandlerType(ht_s),
        .param_types_json = ptj_s,
        .original_handler = orig,
        .model_param_name = null,
        .model_class = null,
    };

    if (std.mem.eql(u8, ht_s, "simple_sync")) {
        entry.param_count = parseParamMeta(ptj_s, &entry.param_meta);
    }

    getRoutes().put(key, entry) catch return null;
    getRouter().addRoute(method_s, path_s, key) catch return null;

    return py.pyNone();
}

// ── add_route_model(method, path, handler, param_name, model_class, original) ──

pub fn server_add_route_model(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var method: [*c]const u8 = null;
    var path: [*c]const u8 = null;
    var handler: ?*c.PyObject = null;
    var param_name: [*c]const u8 = null;
    var model_class: ?*c.PyObject = null;
    var orig: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "ssOsOO", &method, &path, &handler, &param_name, &model_class, &orig) == 0) return null;

    c.Py_IncRef(handler.?);
    c.Py_IncRef(model_class.?);
    c.Py_IncRef(orig.?);
    const method_s = std.mem.span(method);
    const path_s = std.mem.span(path);
    const key = std.fmt.allocPrint(allocator, "{s} {s}", .{ method_s, path_s }) catch return null;
    getRoutes().put(key, .{
        .handler = handler.?,
        .handler_type = "model_sync",
        .handler_tag = .model_sync,
        .param_types_json = "{}",
        .original_handler = orig,
        .model_param_name = std.mem.span(param_name),
        .model_class = model_class,
    }) catch return null;
    getRouter().addRoute(method_s, path_s, key) catch return null;

    return py.pyNone();
}

// ── add_route_model_validated(method, path, handler, param_name, model_class, original, schema_json) ──
// Like add_route_model but also registers a JSON schema for Zig-native validation

pub fn server_add_route_model_validated(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var method: [*c]const u8 = null;
    var path: [*c]const u8 = null;
    var handler: ?*c.PyObject = null;
    var param_name: [*c]const u8 = null;
    var model_class: ?*c.PyObject = null;
    var orig: ?*c.PyObject = null;
    var schema_json: [*c]const u8 = null;
    if (c.PyArg_ParseTuple(args, "ssOsOOs", &method, &path, &handler, &param_name, &model_class, &orig, &schema_json) == 0) return null;

    c.Py_IncRef(handler.?);
    c.Py_IncRef(model_class.?);
    c.Py_IncRef(orig.?);
    const method_s = std.mem.span(method);
    const path_s = std.mem.span(path);
    const key = std.fmt.allocPrint(allocator, "{s} {s}", .{ method_s, path_s }) catch return null;
    getRoutes().put(key, .{
        .handler = handler.?,
        .handler_type = "model_sync",
        .handler_tag = .model_sync,
        .param_types_json = "{}",
        .original_handler = orig,
        .model_param_name = std.mem.span(param_name),
        .model_class = model_class,
    }) catch return null;
    getRouter().addRoute(method_s, path_s, key) catch return null;

    // Parse and register the schema for Zig-native validation
    const schema_s = std.mem.span(schema_json);
    if (dhi.parseSchema(schema_s)) |schema| {
        getModelSchemas().put(key, schema) catch {};
        std.debug.print("[DHI] Registered schema for {s}: {d} fields\n", .{ key, schema.fields.len });
    }

    return py.pyNone();
}

// ── add_route_async_fast(method, path, handler, handler_type, param_types_json, original) ──

pub fn server_add_route_async_fast(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    // Same signature as add_route_fast
    return server_add_route_fast(null, args);
}

// ── add_native_route(method, path, lib_path, symbol_name) ───────────────────

pub fn server_add_native_route(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var method: [*c]const u8 = null;
    var path: [*c]const u8 = null;
    var lib_path: [*c]const u8 = null;
    var symbol_name: [*c]const u8 = null;
    if (c.PyArg_ParseTuple(args, "ssss", &method, &path, &lib_path, &symbol_name) == 0) return null;

    const method_s = std.mem.span(method);
    const path_s = std.mem.span(path);
    const lib_path_s = std.mem.span(lib_path);
    const symbol_name_s = std.mem.span(symbol_name);

    // dlopen the shared library
    const lib_path_z = allocator.dupeZ(u8, lib_path_s) catch {
        py.setError("OOM for lib path", .{});
        return null;
    };
    defer allocator.free(lib_path_z);

    const handle = std.c.dlopen(lib_path_z, .{}) orelse {
        py.setError("dlopen failed for {s}", .{lib_path_s});
        return null;
    };

    // Try to call turboapi_init if it exists
    const init_sym = std.c.dlsym(handle, "turboapi_init");
    if (init_sym) |sym| {
        const init_fn: NativeInitFn = @ptrCast(@alignCast(sym));
        const rc = init_fn();
        if (rc != 0) {
            py.setError("turboapi_init returned {d}", .{rc});
            _ = std.c.dlclose(handle);
            return null;
        }
    }

    // Resolve the handler symbol
    const sym_z = allocator.dupeZ(u8, symbol_name_s) catch {
        py.setError("OOM for symbol name", .{});
        _ = std.c.dlclose(handle);
        return null;
    };
    defer allocator.free(sym_z);

    const handler_sym = std.c.dlsym(handle, sym_z) orelse {
        py.setError("dlsym failed for {s} in {s}", .{ symbol_name_s, lib_path_s });
        _ = std.c.dlclose(handle);
        return null;
    };
    const handler_fn: NativeHandlerFn = @ptrCast(@alignCast(handler_sym));

    // Register in router + native_routes
    const key = std.fmt.allocPrint(allocator, "{s} {s}", .{ method_s, path_s }) catch {
        _ = std.c.dlclose(handle);
        return null;
    };
    getNativeRoutes().put(key, .{
        .handler_fn = handler_fn,
        .lib_handle = handle,
    }) catch {
        _ = std.c.dlclose(handle);
        return null;
    };
    getRouter().addRoute(method_s, path_s, key) catch {
        _ = std.c.dlclose(handle);
        return null;
    };

    std.debug.print("[FFI] Registered native handler: {s} {s} -> {s}:{s}\n", .{ method_s, path_s, lib_path_s, symbol_name_s });
    return py.pyNone();
}

// ── add_static_route(method, path, status, content_type, body) ──────────────
// Pre-renders the complete HTTP response at registration time.
// At dispatch time: single writeAll, zero parsing, zero allocation.

pub fn server_add_static_route(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var method: [*c]const u8 = null;
    var path: [*c]const u8 = null;
    var status: c_int = 200;
    var content_type: [*c]const u8 = null;
    var body: [*c]const u8 = null;
    if (c.PyArg_ParseTuple(args, "ssiss", &method, &path, &status, &content_type, &body) == 0) return null;

    const method_s = std.mem.span(method);
    const path_s = std.mem.span(path);
    const ct_s = std.mem.span(content_type);
    const body_s = std.mem.span(body);
    const st: u16 = if (status >= 100 and status <= 599) @intCast(status) else 200;

    const status_text = statusText(st);
    const response_bytes = std.fmt.allocPrint(allocator,
        "HTTP/1.1 {d} {s}\r\nContent-Type: {s}\r\nContent-Length: {d}\r\nConnection: keep-alive\r\n\r\n{s}",
        .{ st, status_text, ct_s, body_s.len, body_s },
    ) catch return null;

    const key = std.fmt.allocPrint(allocator, "{s} {s}", .{ method_s, path_s }) catch {
        allocator.free(response_bytes);
        return null;
    };

    getStaticRoutes().put(key, .{ .response_bytes = response_bytes }) catch {
        allocator.free(response_bytes);
        return null;
    };
    getRouter().addRoute(method_s, path_s, key) catch return null;

    std.debug.print("[STATIC] Registered: {s} {s} -> {d} ({d} bytes pre-rendered)\n", .{ method_s, path_s, st, response_bytes.len });
    return py.pyNone();
}

// ── Zig-native CORS — zero per-request overhead ─────────────────────────────
// CORS headers are pre-rendered once at configure_cors() time.  sendResponse
// injects them via a single memcpy into the stack buffer.  OPTIONS preflight
// is handled in handleOneRequest before touching Python.

var cors_headers: []const u8 = ""; // "" = disabled; otherwise pre-rendered CORS header block
var cors_enabled: bool = false;

pub fn server_configure_cors(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var origins: [*c]const u8 = "*";
    var methods: [*c]const u8 = "GET, POST, PUT, DELETE, OPTIONS, PATCH, HEAD";
    var hdrs: [*c]const u8 = "*";
    var max_age: c_int = 600;
    var credentials: c_int = 0;
    if (c.PyArg_ParseTuple(args, "|sssii", &origins, &methods, &hdrs, &max_age, &credentials) == 0) return null;

    const origins_s = std.mem.span(origins);
    const methods_s = std.mem.span(methods);
    const hdrs_s = std.mem.span(hdrs);

    // Reject CRLF in CORS values — prevents header injection
    for ([_][]const u8{ origins_s, methods_s, hdrs_s }) |val| {
        if (std.mem.indexOfAny(u8, val, "\r\n") != null) {
            py.setError("CORS values must not contain CR or LF", .{});
            return null;
        }
    }

    // Pre-render the CORS header block (injected into every response)
    const cred_hdr: []const u8 = if (credentials != 0) "\r\nAccess-Control-Allow-Credentials: true" else "";
    var age_buf: [16]u8 = undefined;
    const age_str = std.fmt.bufPrint(&age_buf, "{d}", .{max_age}) catch "600";

    cors_headers = std.fmt.allocPrint(allocator,
        "\r\nAccess-Control-Allow-Origin: {s}" ++
        "\r\nAccess-Control-Allow-Methods: {s}" ++
        "\r\nAccess-Control-Allow-Headers: {s}" ++
        "{s}" ++
        "\r\nAccess-Control-Max-Age: {s}",
        .{ origins_s, methods_s, hdrs_s, cred_hdr, age_str },
    ) catch return null;
    cors_enabled = true;

    std.debug.print("[CORS] Zig-native CORS enabled: origin={s} methods={s}\n", .{ origins_s, methods_s });
    return py.pyNone();
}

// ── add_middleware(middleware_obj) – currently a no-op ──

pub fn server_add_middleware(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    return py.pyNone();
}

// ── Response cache for noargs handlers ──────────────────────────────────────
// After the first Python call, the pre-rendered response bytes are cached.
// Subsequent calls serve from cache — zero Python, zero GIL, single writeAll.

pub fn server_enable_response_cache(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    cache_noargs_responses = true;
    std.debug.print("[CACHE] Response caching enabled for noargs handlers\n", .{});
    return py.pyNone();
}

/// Pre-render a full HTTP response into a heap-allocated buffer.
fn renderResponse(status: u16, content_type: []const u8, body: []const u8) ?[]const u8 {
    const cors = cors_headers;
    // Note: Date is static for cached responses. TFB just needs the header present.
    var date_buf: [40]u8 = undefined;
    const ts = std.time.timestamp();
    const es: std.time.epoch.EpochSeconds = .{ .secs = @intCast(ts) };
    const ds = es.getDaySeconds();
    const ed = es.getEpochDay();
    const yd = ed.calculateYearDay();
    const md = yd.calculateMonthDay();
    const di: usize = @intCast(@mod(@as(i32, @intCast(ed.day)) + 3, 7));
    const dw = [7][]const u8{ "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun" };
    const mn = [12][]const u8{ "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" };
    const dt = std.fmt.bufPrint(&date_buf, "{s}, {d:0>2} {s} {d} {d:0>2}:{d:0>2}:{d:0>2} GMT", .{
        dw[di], md.day_index + 1, mn[@intFromEnum(md.month) - 1], yd.year,
        ds.getHoursIntoDay(), ds.getMinutesIntoHour(), ds.getSecondsIntoMinute(),
    }) catch "Thu, 01 Jan 2026 00:00:00 GMT";
    return std.fmt.allocPrint(allocator,
        "HTTP/1.1 {d} {s}\r\nServer: TurboAPI\r\nDate: {s}\r\nContent-Type: {s}\r\nContent-Length: {d}\r\nConnection: keep-alive{s}\r\n\r\n{s}",
        .{ status, statusText(status), dt, content_type, body.len, cors, body },
    ) catch null;
}

// ── run() – start the HTTP server ──

// ── Thread pool for connection handling ─────────────────────────────────────

const POOL_SIZE = 24; // 2x 12-core M-series; overridden at runtime below if needed

const ConnectionPool = struct {
    queue: Queue,
    threads: [POOL_SIZE]std.Thread = undefined,

    const Queue = struct {
        items: [4096]std.net.Stream = undefined,
        head: usize = 0,
        tail: usize = 0,
        count: usize = 0,
        mutex: std.Thread.Mutex = .{},
        not_empty: std.Thread.Condition = .{},

        fn push(self: *Queue, stream: std.net.Stream) void {
            self.mutex.lock();
            defer self.mutex.unlock();
            if (self.count >= self.items.len) {
                stream.close();
                return;
            }
            self.items[self.tail] = stream;
            self.tail = (self.tail + 1) % self.items.len;
            self.count += 1;
            self.not_empty.signal();
        }

        fn pop(self: *Queue) std.net.Stream {
            self.mutex.lock();
            defer self.mutex.unlock();
            while (self.count == 0) {
                self.not_empty.wait(&self.mutex);
            }
            const stream = self.items[self.head];
            self.head = (self.head + 1) % self.items.len;
            self.count -= 1;
            return stream;
        }
    };

    fn init(self: *ConnectionPool) void {
        self.queue = .{};
        for (0..POOL_SIZE) |i| {
            self.threads[i] = std.Thread.spawn(.{}, workerLoop, .{&self.queue}) catch @panic("thread spawn");
        }
    }

    // Each worker creates its own PyThreadState once and reuses it for every
    // request. This replaces PyGILState_Ensure/Release (which re-does a
    // thread-state lookup on every call) with the cheaper AcquireThread path.
    fn workerLoop(queue: *Queue) void {
        const tstate = py.PyThreadState_New(py_interp) orelse @panic("PyThreadState_New failed");
        defer {
            py.PyEval_AcquireThread(tstate);
            py.PyThreadState_Clear(tstate);
            py.PyThreadState_DeleteCurrent();
        }

        while (true) {
            const stream = queue.pop();
            handleConnection(stream, tstate);
        }
    }
};

var pool: ConnectionPool = undefined;

pub fn server_run(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    const addr = std.net.Address.parseIp4(server_host, server_port) catch {
        py.setError("Invalid address: {s}:{d}", .{ server_host, server_port });
        return null;
    };

    var tcp_server = addr.listen(.{ .reuse_address = true }) catch {
        py.setError("Failed to bind to {s}:{d}", .{ server_host, server_port });
        return null;
    };
    defer tcp_server.deinit();

    // Capture interpreter state before releasing the GIL.
    // Workers need this to create their own PyThreadState.
    py_interp = py.PyInterpreterState_Get();

    // Start thread pool (workers create their tstates after this point,
    // but py_interp is set before SaveThread so there's no race).
    pool.init();

    std.debug.print("🚀 TurboNet-Zig server listening on {s}:{d}\n", .{ server_host, server_port });
    std.debug.print("🎯 Zig HTTP core active – {d}-thread pool, per-worker tstate!\n", .{POOL_SIZE});

    // Release the GIL — workers acquire it per-request via AcquireThread.
    const save = py.PyEval_SaveThread();

    while (true) {
        const conn = tcp_server.accept() catch continue;
        pool.queue.push(conn.stream);
    }

    py.PyEval_RestoreThread(save);
    return py.pyNone();
}


const HeaderList = std.ArrayListUnmanaged(HeaderPair);

fn parseHeaders(request_data: []const u8, first_line_end: usize, header_end_pos: usize) HeaderList {
    var headers: HeaderList = .empty;

    var pos = first_line_end + 2; // skip past first \r\n
    while (pos < header_end_pos) {
        const line_end = std.mem.indexOfPos(u8, request_data, pos, "\r\n") orelse header_end_pos;
        const line = request_data[pos..line_end];
        pos = line_end + 2;

        if (line.len == 0) break;

        const colon = std.mem.indexOfScalar(u8, line, ':') orelse continue;
        const name = std.mem.trim(u8, line[0..colon], " \t");
        const value = std.mem.trim(u8, line[colon + 1 ..], " \t");

        if (name.len == 0) continue;
        headers.append(allocator, .{ .name = name, .value = value }) catch continue;
    }

    return headers;
}

fn handleConnection(stream: std.net.Stream, tstate: ?*anyopaque) void {
    defer stream.close();

    // Slowloris protection: if client sends nothing for 30s, read() times out
    // and the worker is freed. No kqueue needed — just a socket option.
    const timeout = std.posix.timeval{ .sec = 30, .usec = 0 };
    std.posix.setsockopt(stream.handle, std.posix.SOL.SOCKET, std.posix.SO.RCVTIMEO, std.mem.asBytes(&timeout)) catch {};

    while (true) {
        handleOneRequest(stream, tstate) catch return;
    }
}

fn handleOneRequest(stream: std.net.Stream, tstate: ?*anyopaque) !void {
    // Phase 1: Read headers into a fixed buffer (headers are typically < 8KB)
    var header_buf: [8192]u8 = undefined;
    var total_read: usize = 0;
    var header_end_pos: ?usize = null;

    // Read until we find \r\n\r\n (end of headers) or fill the header buffer
    while (total_read < header_buf.len) {
        const n = stream.read(header_buf[total_read..]) catch return error.ReadError;
        if (n == 0) return error.ConnectionClosed;
        total_read += n;

        // Check if we've received the full headers
        if (std.mem.indexOf(u8, header_buf[0..total_read], "\r\n\r\n")) |pos| {
            header_end_pos = pos;
            break;
        }
    }
    if (total_read == 0) return error.ConnectionClosed;

    const he = header_end_pos orelse {
        sendResponse(stream, 431, "text/plain", "Request Header Fields Too Large");
        return error.HeadersTooLarge;
    };

    const request_head = header_buf[0..total_read];

    // Phase 2: Parse the first line to get method + path (cheap — no allocs)
    const first_line_end = std.mem.indexOf(u8, request_head, "\r\n") orelse return;
    const first_line = request_head[0..first_line_end];

    var parts = std.mem.splitScalar(u8, first_line, ' ');
    const method = parts.next() orelse return;
    const raw_path = parts.next() orelse return;

    const q_idx = std.mem.indexOf(u8, raw_path, "?");
    const path = if (q_idx) |i| raw_path[0..i] else raw_path;
    const query_string = if (q_idx) |i| raw_path[i + 1 ..] else "";

    // Phase 3: Route match EARLY — before header parsing, so fast handlers
    // can skip the expensive parseHeaders + body read entirely.
    const rt = getRouter();
    var match = rt.findRoute(method, path) orelse {
        std.debug.print("[ZIG] 404 for {s} {s}\n", .{ method, path });
        sendResponse(stream, 404, "application/json", "{\"error\": \"Not Found\"}");
        return;
    };
    defer match.deinit();

    // ── Fast-exit paths: no header parsing, no body read ──

    // CORS preflight — immediate 204, no Python
    if (cors_enabled and std.mem.eql(u8, method, "OPTIONS")) {
        sendResponse(stream, 204, "", "");
        return;
    }

    // Static routes — single writeAll of pre-rendered bytes
    const sr = getStaticRoutes();
    if (sr.get(match.handler_key)) |static_entry| {
        stream.writeAll(static_entry.response_bytes) catch return;
        return;
    }

    // Native FFI routes — no GIL, no Python
    const nr = getNativeRoutes();
    if (nr.get(match.handler_key)) |native_entry| {
        // Native handlers need headers — parse them
        var headers = parseHeaders(request_head, first_line_end, he);
        defer headers.deinit(allocator);

        // Reject Transfer-Encoding in FFI path (same smuggling guard)
        for (headers.items) |h| {
            if (std.ascii.eqlIgnoreCase(h.name, "transfer-encoding")) {
                sendResponse(stream, 501, "application/json", "{\"error\": \"Transfer-Encoding not supported\"}");
                return;
            }
        }
        const ffi_resp = callNativeHandler(native_entry, method, path, query_string, "", headers.items, &match.params);
        const resp_ct = ffi_resp.content_type[0..ffi_resp.content_type_len];
        const resp_body = ffi_resp.body[0..ffi_resp.body_len];
        sendResponse(stream, ffi_resp.status_code, resp_ct, resp_body);
        return;
    }

    // DB routes — full Zig request cycle, no Python, no GIL
    const dbr = db.getDbRoutes();
    if (dbr.get(match.handler_key)) |*db_entry| {
        if (db_entry.op == .insert) {
            // INSERT needs body — parse headers + read body
            var db_headers = parseHeaders(request_head, first_line_end, he);
            defer db_headers.deinit(allocator);
            var db_cl: usize = 0;
            for (db_headers.items) |h| {
                if (std.ascii.eqlIgnoreCase(h.name, "content-length")) {
                    db_cl = std.fmt.parseInt(usize, h.value, 10) catch 0;
                }
            }
            const db_body_start = he + 4;
            const db_already = request_head[db_body_start..total_read];
            var db_body: []const u8 = "";
            var db_body_owned: ?[]u8 = null;
            defer if (db_body_owned) |b| allocator.free(b);
            if (db_cl == 0) {
                db_body = db_already;
            } else if (db_already.len >= db_cl) {
                db_body = db_already[0..db_cl];
            } else {
                const full = allocator.alloc(u8, db_cl) catch {
                    sendResponse(stream, 500, "application/json", "{\"error\": \"Out of memory\"}");
                    return;
                };
                db_body_owned = full;
                @memcpy(full[0..db_already.len], db_already);
                var br: usize = db_already.len;
                while (br < db_cl) {
                    const n = stream.read(full[br..db_cl]) catch return;
                    if (n == 0) break;
                    br += n;
                }
                db_body = full[0..br];
            }
            db.handleDbRoute(stream, db_entry, db_body, &match.params, query_string, &sendResponse);
        } else {
            // GET/DELETE — no body needed
            db.handleDbRoute(stream, db_entry, "", &match.params, query_string, &sendResponse);
        }
        return;
    }

    // Python handler lookup
    const r = getRoutes();
    const entry = r.get(match.handler_key) orelse {
        std.debug.print("[ZIG] handler entry missing for key: {s}\n", .{match.handler_key});
        sendResponse(stream, 500, "application/json", "{\"error\": \"Internal Server Error\"}");
        return;
    };

    // ── Ultra-fast path: simple handlers that don't need headers or body ──
    switch (entry.handler_tag) {
        .simple_sync_noargs => {
            if (cache_noargs_responses) {
                if (getResponseCache().get(match.handler_key)) |cached| {
                    // Cache hit: body-only cache, sendResponse adds fresh Date header
                    sendResponse(stream, 200, "application/json", cached);
                    return;
                }
                callPythonNoArgsCaching(tstate, entry, stream, match.handler_key);
            } else {
                callPythonNoArgs(tstate, entry, stream);
            }
            return;
        },
        .simple_sync => {
            // Param-aware cache: key is "METHOD /full/path" (includes param values)
            if (cache_noargs_responses) {
                // Build cache key from method + path + query (e.g. "GET /users/123?sort=name")
                var cache_key_buf: [512]u8 = undefined;
                const cache_key = if (query_string.len > 0)
                    std.fmt.bufPrint(&cache_key_buf, "{s} {s}?{s}", .{ method, path, query_string }) catch path
                else
                    std.fmt.bufPrint(&cache_key_buf, "{s} {s}", .{ method, path }) catch path;
                if (getResponseCache().get(cache_key)) |cached| {
                    sendResponse(stream, 200, "application/json", cached);
                    return;
                }
                callPythonVectorcallCaching(tstate, entry, query_string, &match.params, stream, cache_key);
            } else {
                callPythonVectorcall(tstate, entry, query_string, &match.params, stream);
            }
            return;
        },
        else => {},
    }

    // ── Full path: parse headers + read body (only for handlers that need them) ──

    var headers = parseHeaders(request_head, first_line_end, he);
    defer headers.deinit(allocator);

    const body_start = he + 4;
    const already_read_body = request_head[body_start..total_read];

    // Reject Transfer-Encoding (chunked not implemented — accepting silently causes request smuggling)
    var has_te = false;
    var has_cl = false;
    var content_length: usize = 0;
    for (headers.items) |h| {
        if (std.ascii.eqlIgnoreCase(h.name, "transfer-encoding")) has_te = true;
        if (std.ascii.eqlIgnoreCase(h.name, "content-length")) {
            has_cl = true;
            content_length = std.fmt.parseInt(usize, h.value, 10) catch 0;
        }
    }
    if (has_te) {
        if (has_cl) {
            // TE + CL = smuggling attack (RFC 7230 §3.3.3)
            sendResponse(stream, 400, "application/json", "{\"error\": \"Conflicting Transfer-Encoding and Content-Length\"}");
        } else {
            // TE alone = unsupported encoding
            sendResponse(stream, 501, "application/json", "{\"error\": \"Transfer-Encoding not supported\"}");
        }
        return;
    }

    const max_body: usize = 16 * 1024 * 1024;
    if (content_length > max_body) {
        sendResponse(stream, 413, "application/json", "{\"error\": \"Payload Too Large\"}");
        return;
    }

    var body: []const u8 = "";
    var body_owned: ?[]u8 = null;
    defer if (body_owned) |b| allocator.free(b);

    if (content_length == 0) {
        body = already_read_body;
    } else if (already_read_body.len >= content_length) {
        body = already_read_body[0..content_length];
    } else {
        const full_body = allocator.alloc(u8, content_length) catch {
            sendResponse(stream, 500, "application/json", "{\"error\": \"Out of memory\"}");
            return;
        };
        body_owned = full_body;
        @memcpy(full_body[0..already_read_body.len], already_read_body);
        var body_read: usize = already_read_body.len;
        while (body_read < content_length) {
            const n = stream.read(full_body[body_read..content_length]) catch |err| {
                std.debug.print("[ZIG] body read error: {}\n", .{err});
                return;
            };
            if (n == 0) break;
            body_read += n;
        }
        body = full_body[0..body_read];
    }

    // DHI validation for model_sync — single parse, retain tree
    var cached_parse: ?std.json.Parsed(std.json.Value) = null;
    defer if (cached_parse) |*cp| cp.deinit();

    if (body.len > 0) {
        const ms = getModelSchemas();
        if (ms.get(match.handler_key)) |schema| {
            const vr = dhi.validateJsonRetainParsed(body, &schema);
            switch (vr) {
                .ok => |parsed| { cached_parse = parsed; },
                .err => |ve| {
                    defer ve.deinit();
                    std.debug.print("[DHI] validation failed for {s}\n", .{match.handler_key});
                    sendResponse(stream, ve.status_code, "application/json", ve.body);
                    return;
                },
            }
        }
    }

    // Dispatch remaining handler types
    switch (entry.handler_tag) {
        .simple_sync_noargs, .simple_sync => unreachable, // handled above
        .model_sync => {
            if (body.len > 0) {
                if (cached_parse) |cp| {
                    callPythonModelHandlerParsed(tstate, entry, cp.value, &match.params, stream);
                } else {
                    callPythonModelHandlerDirect(tstate, entry, body, &match.params, stream);
                }
                return;
            }
            callPythonHandlerDirect(tstate, entry, query_string, body, &match.params, stream);
        },
        .body_sync => {
            callPythonHandlerDirect(tstate, entry, query_string, body, &match.params, stream);
        },
        .enhanced => {
            const resp = callPythonHandler(tstate, entry, method, path, query_string, body, headers.items, &match.params);
            defer resp.deinit();
            sendResponse(stream, resp.status_code, resp.content_type, resp.body);
        },
    }
}

// ── FFI native handler dispatch (no GIL, no Python) ─────────────────────────

fn callNativeHandler(
    entry: NativeHandlerEntry,
    method: []const u8,
    path: []const u8,
    query_string: []const u8,
    body: []const u8,
    headers: []const HeaderPair,
    params: *const router_mod.RouteParams,
) FfiResponse {
    // Build parallel arrays for headers
    const hcount = headers.len;
    const h_names = allocator.alloc([*c]const u8, hcount) catch return ffiError();
    defer allocator.free(h_names);
    const h_name_lens = allocator.alloc(usize, hcount) catch return ffiError();
    defer allocator.free(h_name_lens);
    const h_values = allocator.alloc([*c]const u8, hcount) catch return ffiError();
    defer allocator.free(h_values);
    const h_value_lens = allocator.alloc(usize, hcount) catch return ffiError();
    defer allocator.free(h_value_lens);

    for (headers, 0..) |h, i| {
        h_names[i] = h.name.ptr;
        h_name_lens[i] = h.name.len;
        h_values[i] = h.value.ptr;
        h_value_lens[i] = h.value.len;
    }

    // Build parallel arrays for path params
    var p_names_list: std.ArrayListUnmanaged([*c]const u8) = .empty;
    defer p_names_list.deinit(allocator);
    var p_name_lens_list: std.ArrayListUnmanaged(usize) = .empty;
    defer p_name_lens_list.deinit(allocator);
    var p_values_list: std.ArrayListUnmanaged([*c]const u8) = .empty;
    defer p_values_list.deinit(allocator);
    var p_value_lens_list: std.ArrayListUnmanaged(usize) = .empty;
    defer p_value_lens_list.deinit(allocator);

    for (params.entries()) |pe| {
        p_names_list.append(allocator, pe.key.ptr) catch continue;
        p_name_lens_list.append(allocator, pe.key.len) catch continue;
        p_values_list.append(allocator, pe.value.ptr) catch continue;
        p_value_lens_list.append(allocator, pe.value.len) catch continue;
    }

    const ffi_req = FfiRequest{
        .method = method.ptr,
        .method_len = method.len,
        .path = path.ptr,
        .path_len = path.len,
        .query_string = query_string.ptr,
        .query_len = query_string.len,
        .body = body.ptr,
        .body_len = body.len,
        .header_names = h_names.ptr,
        .header_name_lens = h_name_lens.ptr,
        .header_values = h_values.ptr,
        .header_value_lens = h_value_lens.ptr,
        .header_count = hcount,
        .param_names = p_names_list.items.ptr,
        .param_name_lens = p_name_lens_list.items.ptr,
        .param_values = p_values_list.items.ptr,
        .param_value_lens = p_value_lens_list.items.ptr,
        .param_count = p_names_list.items.len,
    };

    return entry.handler_fn(&ffi_req);
}

fn ffiError() FfiResponse {
    const body = "{\"error\": \"FFI dispatch error\"}";
    return .{
        .status_code = 500,
        .content_type = "application/json",
        .content_type_len = 16,
        .body = body,
        .body_len = body.len,
    };
}

// ── Tuple ABI helper ─────────────────────────────────────────────────────────
// Python fast handlers return (status_code, content_type, body_str).
// Unpack and send — no dict key lookups, no hash computation.

fn sendTupleResponse(stream: std.net.Stream, result: *c.PyObject) void {
    const sc_obj = py.PyTuple_GetItem(result, 0) orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"bad tuple[0]\"}");
        return;
    };
    const ct_obj = py.PyTuple_GetItem(result, 1) orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"bad tuple[1]\"}");
        return;
    };
    const body_obj = py.PyTuple_GetItem(result, 2) orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"bad tuple[2]\"}");
        return;
    };

    const status_code: u16 = @intCast(c.PyLong_AsLong(sc_obj));
    const ct_cstr: [*c]const u8 = c.PyUnicode_AsUTF8(ct_obj) orelse "application/json";
    const content_type = std.mem.span(ct_cstr);

    if (c.PyUnicode_Check(body_obj) != 0) {
        if (c.PyUnicode_AsUTF8(body_obj)) |cs| {
            sendResponse(stream, status_code, content_type, std.mem.span(cs));
            return;
        }
    } else if (c.PyBytes_Check(body_obj) != 0) {
        var size: c.Py_ssize_t = 0;
        var buf: [*c]u8 = undefined;
        if (c.PyBytes_AsStringAndSize(body_obj, @ptrCast(&buf), &size) == 0) {
            sendResponse(stream, status_code, content_type, buf[0..@intCast(size)]);
            return;
        }
    }
    sendResponse(stream, 500, "application/json", "{\"error\":\"bad tuple body\"}");
}

// ── simple_sync_noargs: PyObject_CallNoArgs — no tuple/dict construction ─────

fn callPythonNoArgs(tstate: ?*anyopaque, entry: HandlerEntry, stream: std.net.Stream) void {
    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    const result = py.PyObject_CallNoArgs(entry.handler) orelse {
        c.PyErr_Print();
        sendResponse(stream, 500, "application/json", "{\"error\":\"handler failed\"}");
        return;
    };
    defer c.Py_DecRef(result);
    sendTupleResponse(stream, result);
}

/// Like callPythonNoArgs but caches the pre-rendered response for subsequent calls.
fn callPythonNoArgsCaching(tstate: ?*anyopaque, entry: HandlerEntry, stream: std.net.Stream, handler_key: []const u8) void {
    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    const result = py.PyObject_CallNoArgs(entry.handler) orelse {
        c.PyErr_Print();
        sendResponse(stream, 500, "application/json", "{\"error\":\"handler failed\"}");
        return;
    };
    defer c.Py_DecRef(result);

    // Extract tuple (status, content_type, body) and cache pre-rendered response
    const sc_obj = py.PyTuple_GetItem(result, 0) orelse return;
    const ct_obj = py.PyTuple_GetItem(result, 1) orelse return;
    const body_obj = py.PyTuple_GetItem(result, 2) orelse return;

    const status_code: u16 = @intCast(c.PyLong_AsLong(sc_obj));
    const ct_cstr: [*c]const u8 = c.PyUnicode_AsUTF8(ct_obj) orelse "application/json";
    const content_type = std.mem.span(ct_cstr);

    var body_slice: []const u8 = "";
    if (c.PyUnicode_Check(body_obj) != 0) {
        if (c.PyUnicode_AsUTF8(body_obj)) |cs| body_slice = std.mem.span(cs);
    } else if (c.PyBytes_Check(body_obj) != 0) {
        var size: c.Py_ssize_t = 0;
        var buf: [*c]u8 = undefined;
        if (c.PyBytes_AsStringAndSize(body_obj, @ptrCast(&buf), &size) == 0) {
            body_slice = buf[0..@intCast(size)];
        }
    }

    // Send response now
    sendResponse(stream, status_code, content_type, body_slice);

    // Cache body only (sendResponse adds fresh Date headers on each hit)
    const body_dupe = allocator.dupe(u8, body_slice) catch return;
    cacheResponse(handler_key, body_dupe);
}

/// Fast path for simple_sync handlers with 1+ params.
/// Zig assembles the positional arg vector from path/query params — no Python
/// dict allocation, no parse_qs, no call_kwargs. Calls via PyObject_Vectorcall.
/// Fast path for simple_sync handlers with 1+ params.
/// Zig assembles the positional arg vector from path/query params — no Python
/// dict allocation, no parse_qs, no call_kwargs. Calls via PyObject_Vectorcall.
/// Params with has_default=true that are missing from the request are omitted
/// from the tail of the arg vector, letting Python apply its own defaults.
/// Fast path for simple_sync handlers with 1+ params.
/// Zig assembles the positional arg vector from path/query params — no Python
/// dict allocation, no parse_qs, no call_kwargs. Calls via PyObject_Vectorcall.
/// Params with has_default=true that are missing from the request are omitted
/// from the tail of the arg vector, letting Python apply its own defaults.
fn callPythonVectorcall(
    tstate: ?*anyopaque,
    entry: HandlerEntry,
    query_string: []const u8,
    params: *const router_mod.RouteParams,
    stream: std.net.Stream,
) void {
    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    const argc = entry.param_count;
    var argv: [MAX_PARAMS]?*c.PyObject = undefined;
    // Track created objects for Py_DecRef after the call.
    var created: [MAX_PARAMS]?*c.PyObject = [_]?*c.PyObject{null} ** MAX_PARAMS;
    defer for (created[0..argc]) |obj| {
        if (obj) |o| c.Py_DecRef(o);
    };

    // Per-param decode buffer for percent-decoding str query values.
    var decode_buf: [2048]u8 = undefined;

    // last_filled: highest index+1 where we have a real value.
    // Trailing optional params with no value are excluded from the vectorcall
    // so Python uses its own default — never passes None for missing optionals.
    var last_filled: usize = 0;

    for (entry.param_meta[0..argc], 0..) |pm, i| {
        // Path params take priority; fall back to query string.
        const val_str: ?[]const u8 = params.get(pm.name) orelse queryStringGet(query_string, pm.name);

        if (val_str) |vs| {
            const py_obj: ?*c.PyObject = switch (pm.type_tag) {
                .int => blk: {
                    const n = std.fmt.parseInt(i64, vs, 10) catch 0;
                    break :blk c.PyLong_FromLongLong(n);
                },
                .float => blk: {
                    const f = std.fmt.parseFloat(f64, vs) catch 0.0;
                    break :blk c.PyFloat_FromDouble(f);
                },
                .bool_val => blk: {
                    const b: c_long = if (std.mem.eql(u8, vs, "true") or std.mem.eql(u8, vs, "1")) 1 else 0;
                    break :blk c.PyBool_FromLong(b);
                },
                .str => blk: {
                    // Percent-decode query string values (%20 → space, + → space)
                    const decoded = percentDecode(vs, &decode_buf);
                    break :blk c.PyUnicode_FromStringAndSize(decoded.ptr, @intCast(decoded.len));
                },
            };
            if (py_obj) |obj| {
                argv[i] = obj;
                created[i] = obj;
                last_filled = i + 1;
            } else {
                argv[i] = @ptrCast(&c._Py_NoneStruct);
                if (!pm.has_default) last_filled = i + 1;
            }
        } else {
            // Missing param: if required, pass None; if optional, skip (Python uses default)
            argv[i] = @ptrCast(&c._Py_NoneStruct);
            if (!pm.has_default) last_filled = i + 1;
        }
    }

    const result = py.PyObject_Vectorcall(
        entry.handler,
        @as([*]const ?*c.PyObject, @ptrCast(&argv)),
        last_filled, // excludes trailing missing optionals
        null,
    ) orelse {
        c.PyErr_Print();
        sendResponse(stream, 500, "application/json", "{\"error\":\"handler failed\"}");
        return;
    };
    defer c.Py_DecRef(result);
    sendTupleResponse(stream, result);
}

/// Like callPythonVectorcall but caches the pre-rendered response keyed by full path.
fn callPythonVectorcallCaching(
    tstate: ?*anyopaque,
    entry: HandlerEntry,
    query_string: []const u8,
    params: *const router_mod.RouteParams,
    stream: std.net.Stream,
    cache_key: []const u8,
) void {
    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    const argc = entry.param_count;
    var args: [MAX_PARAMS + 1]*c.PyObject = undefined;
    args[0] = entry.handler;
    var decode_buf: [2048]u8 = undefined;
    var last_filled: usize = 0;

    for (entry.param_meta[0..argc], 0..) |pm, i| {
        const val_str: ?[]const u8 = params.get(pm.name) orelse queryStringGet(query_string, pm.name);
        if (val_str) |vs| {
            const py_obj: ?*c.PyObject = switch (pm.type_tag) {
                .int => blk: {
                    const n = std.fmt.parseInt(i64, vs, 10) catch 0;
                    break :blk c.PyLong_FromLongLong(n);
                },
                .float => blk: {
                    const f = std.fmt.parseFloat(f64, vs) catch 0;
                    break :blk c.PyFloat_FromDouble(f);
                },
                .bool_val => blk: {
                    const is_true = std.mem.eql(u8, vs, "true") or std.mem.eql(u8, vs, "1");
                    break :blk if (is_true) py.pyTrue() else py.pyFalse();
                },
                .str => blk: {
                    const decoded = percentDecode(vs, &decode_buf);
                    break :blk c.PyUnicode_FromStringAndSize(decoded.ptr, @intCast(decoded.len));
                },
            };
            if (py_obj) |obj| {
                args[i + 1] = obj;
                last_filled = i + 1;
            } else {
                sendResponse(stream, 500, "application/json", "{\"error\":\"arg conversion failed\"}");
                for (1..i + 1) |j| c.Py_DecRef(args[j]);
                return;
            }
        } else {
            if (pm.has_default) break;
            sendResponse(stream, 422, "application/json", "{\"error\":\"missing required param\"}");
            for (1..i + 1) |j| c.Py_DecRef(args[j]);
            return;
        }
    }
    defer for (1..last_filled + 1) |j| c.Py_DecRef(args[j]);

    const nargs = last_filled;
    const result = py.PyObject_Vectorcall(entry.handler, @ptrCast(&args[1]), nargs, null) orelse {
        c.PyErr_Print();
        sendResponse(stream, 500, "application/json", "{\"error\":\"handler failed\"}");
        return;
    };
    defer c.Py_DecRef(result);

    // Extract tuple and send + cache
    const sc_obj = py.PyTuple_GetItem(result, 0) orelse return;
    const ct_obj = py.PyTuple_GetItem(result, 1) orelse return;
    const body_obj = py.PyTuple_GetItem(result, 2) orelse return;

    const status_code: u16 = @intCast(c.PyLong_AsLong(sc_obj));
    const ct_cstr: [*c]const u8 = c.PyUnicode_AsUTF8(ct_obj) orelse "application/json";
    const content_type = std.mem.span(ct_cstr);

    var body_slice: []const u8 = "";
    if (c.PyUnicode_Check(body_obj) != 0) {
        if (c.PyUnicode_AsUTF8(body_obj)) |cs| body_slice = std.mem.span(cs);
    } else if (c.PyBytes_Check(body_obj) != 0) {
        var size: c.Py_ssize_t = 0;
        var buf: [*c]u8 = undefined;
        if (c.PyBytes_AsStringAndSize(body_obj, @ptrCast(&buf), &size) == 0) {
            body_slice = buf[0..@intCast(size)];
        }
    }

    sendResponse(stream, status_code, content_type, body_slice);

    // Cache body only (sendResponse adds fresh Date headers on each hit)
    const body_dupe = allocator.dupe(u8, body_slice) catch return;
    cacheResponse(cache_key, body_dupe);
}

// ── Fast Python handler dispatch (simple_sync/body_sync) ─────────────────────
// Calls Python with kwargs dict, unpacks 3-tuple response — zero extra allocs.

fn callPythonHandlerDirect(tstate: ?*anyopaque, entry: HandlerEntry, query_string: []const u8, body: []const u8, params: *const router_mod.RouteParams, stream: std.net.Stream) void {
    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    const kwargs = c.PyDict_New() orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
    defer c.Py_DecRef(kwargs);

    const py_path_params = c.PyDict_New() orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
    defer c.Py_DecRef(py_path_params);
    {
        for (params.entries()) |pe| {
            const pk = py.newString(pe.key) orelse continue;
            const pv = py.newString(pe.value) orelse {
                c.Py_DecRef(pk);
                continue;
            };
            _ = c.PyDict_SetItem(py_path_params, pk, pv);
            c.Py_DecRef(pk);
            c.Py_DecRef(pv);
        }
    }
    _ = c.PyDict_SetItemString(kwargs, "path_params", py_path_params);

    if (query_string.len > 0) {
        if (py.newString(query_string)) |v| {
            _ = c.PyDict_SetItemString(kwargs, "query_string", v);
            c.Py_DecRef(v);
        }
    }

    if (body.len > 0) {
        const py_body = c.PyBytes_FromStringAndSize(@ptrCast(body.ptr), @intCast(body.len)) orelse {
            sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
            return;
        };
        _ = c.PyDict_SetItemString(kwargs, "body", py_body);
        c.Py_DecRef(py_body);
    }

    const empty_tuple = c.PyTuple_New(0) orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
    defer c.Py_DecRef(empty_tuple);

    const result = c.PyObject_Call(entry.handler, empty_tuple, kwargs) orelse {
        c.PyErr_Print();
        sendResponse(stream, 500, "application/json", "{\"error\":\"handler failed\"}");
        return;
    };
    defer c.Py_DecRef(result);

    // Unpack (status_code, content_type, body_str) 3-tuple
    sendTupleResponse(stream, result);
}

// ── JSON-to-Python conversion (eliminates Python json.loads round-trip) ──────

fn jsonValueToPyObject(val: std.json.Value) ?*c.PyObject {
    return switch (val) {
        .null => py.pyNone(),
        .bool => |b| if (b) py.pyTrue() else py.pyFalse(),
        .integer => |i| py.newInt(i),
        .float => |f| c.PyFloat_FromDouble(f),
        .string => |s| py.newString(s),
        .array => |arr| blk: {
            const list = c.PyList_New(@intCast(arr.items.len)) orelse break :blk null;
            for (arr.items, 0..) |item, idx| {
                const py_item = jsonValueToPyObject(item) orelse {
                    c.Py_DecRef(list);
                    break :blk null;
                };
                // PyList_SetItem steals the reference
                _ = c.PyList_SetItem(list, @intCast(idx), py_item);
            }
            break :blk list;
        },
        .object => |obj| blk: {
            const dict = c.PyDict_New() orelse break :blk null;
            var it = obj.iterator();
            while (it.next()) |entry| {
                const py_key = py.newString(entry.key_ptr.*) orelse {
                    c.Py_DecRef(dict);
                    break :blk null;
                };
                const py_val = jsonValueToPyObject(entry.value_ptr.*) orelse {
                    c.Py_DecRef(py_key);
                    c.Py_DecRef(dict);
                    break :blk null;
                };
                _ = c.PyDict_SetItem(dict, py_key, py_val);
                c.Py_DecRef(py_key);
                c.Py_DecRef(py_val);
            }
            break :blk dict;
        },
        .number_string => |s| blk: {
            // Fallback: try to parse as Python int/float from string
            break :blk py.newString(s);
        },
    };
}

// ── model_sync fast dispatch: Zig-parsed JSON → Python dict (no json.loads) ──

fn callPythonModelHandlerDirect(tstate: ?*anyopaque, entry: HandlerEntry, body: []const u8, params: *const router_mod.RouteParams, stream: std.net.Stream) void {
    const parsed = std.json.parseFromSlice(std.json.Value, allocator, body, .{}) catch {
        sendResponse(stream, 400, "application/json", "{\"error\":\"Invalid JSON\"}");
        return;
    };
    defer parsed.deinit();

    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    const py_body_dict = jsonValueToPyObject(parsed.value) orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"JSON conversion failed\"}");
        return;
    };
    defer c.Py_DecRef(py_body_dict);

    const kwargs = c.PyDict_New() orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
    defer c.Py_DecRef(kwargs);

    _ = c.PyDict_SetItemString(kwargs, "body_dict", py_body_dict);

    const py_path_params = c.PyDict_New() orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
    defer c.Py_DecRef(py_path_params);
    {
        for (params.entries()) |pe| {
            const pk = py.newString(pe.key) orelse continue;
            const pv = py.newString(pe.value) orelse {
                c.Py_DecRef(pk);
                continue;
            };
            _ = c.PyDict_SetItem(py_path_params, pk, pv);
            c.Py_DecRef(pk);
            c.Py_DecRef(pv);
        }
    }
    _ = c.PyDict_SetItemString(kwargs, "path_params", py_path_params);

    const empty_tuple = c.PyTuple_New(0) orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
    defer c.Py_DecRef(empty_tuple);

    const result = c.PyObject_Call(entry.handler, empty_tuple, kwargs) orelse {
        c.PyErr_Print();
        sendResponse(stream, 500, "application/json", "{\"error\":\"handler failed\"}");
        return;
    };
    defer c.Py_DecRef(result);

    sendTupleResponse(stream, result);
}

/// Single-parse variant: takes a pre-parsed std.json.Value from validateJsonRetainParsed.
/// Eliminates the second JSON parse that callPythonModelHandlerDirect does.
fn callPythonModelHandlerParsed(tstate: ?*anyopaque, entry: HandlerEntry, json_value: std.json.Value, params: *const router_mod.RouteParams, stream: std.net.Stream) void {
    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    const py_body_dict = jsonValueToPyObject(json_value) orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"JSON conversion failed\"}");
        return;
    };
    defer c.Py_DecRef(py_body_dict);

    const kwargs = c.PyDict_New() orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
    defer c.Py_DecRef(kwargs);

    _ = c.PyDict_SetItemString(kwargs, "body_dict", py_body_dict);

    const py_path_params = c.PyDict_New() orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
    defer c.Py_DecRef(py_path_params);
    {
        for (params.entries()) |pe| {
            const pk = py.newString(pe.key) orelse continue;
            const pv = py.newString(pe.value) orelse {
                c.Py_DecRef(pk);
                continue;
            };
            _ = c.PyDict_SetItem(py_path_params, pk, pv);
            c.Py_DecRef(pk);
            c.Py_DecRef(pv);
        }
    }
    _ = c.PyDict_SetItemString(kwargs, "path_params", py_path_params);

    const empty_tuple = c.PyTuple_New(0) orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
    defer c.Py_DecRef(empty_tuple);

    const result = c.PyObject_Call(entry.handler, empty_tuple, kwargs) orelse {
        c.PyErr_Print();
        sendResponse(stream, 500, "application/json", "{\"error\":\"handler failed\"}");
        return;
    };
    defer c.Py_DecRef(result);

    sendTupleResponse(stream, result);
}

// ── Python handler dispatch (full kwargs — enhanced/model handlers) ──────────

fn callPythonHandler(tstate: ?*anyopaque, entry: HandlerEntry, method: []const u8, path: []const u8, query_string: []const u8, body: []const u8, headers: []const HeaderPair, params: *const router_mod.RouteParams) PythonResponse {
    const err_body = "{\"error\": \"Internal Server Error\"}";
    const err_ct = "application/json";

    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    // ── Build the kwargs dict for enhanced_handler(**kwargs) ──
    const kwargs = c.PyDict_New() orelse return errorResponse(err_ct, err_body);
    defer c.Py_DecRef(kwargs);

    // method
    if (py.newString(method)) |v| {
        _ = c.PyDict_SetItemString(kwargs, "method", v);
        c.Py_DecRef(v);
    }
    // path
    if (py.newString(path)) |v| {
        _ = c.PyDict_SetItemString(kwargs, "path", v);
        c.Py_DecRef(v);
    }
    // body (as bytes, not string)
    const py_body = c.PyBytes_FromStringAndSize(@ptrCast(body.ptr), @intCast(body.len)) orelse return errorResponse(err_ct, err_body);
    _ = c.PyDict_SetItemString(kwargs, "body", py_body);
    c.Py_DecRef(py_body);
    // query_string
    if (py.newString(query_string)) |v| {
        _ = c.PyDict_SetItemString(kwargs, "query_string", v);
        c.Py_DecRef(v);
    }

    // ── headers dict from HeaderPair slice ──
    const py_headers = c.PyDict_New() orelse return errorResponse(err_ct, err_body);
    defer c.Py_DecRef(py_headers);
    for (headers) |h| {
        const hk = py.newString(h.name) orelse continue;
        const hv = py.newString(h.value) orelse {
            c.Py_DecRef(hk);
            continue;
        };
        _ = c.PyDict_SetItem(py_headers, hk, hv);
        c.Py_DecRef(hk);
        c.Py_DecRef(hv);
    }
    _ = c.PyDict_SetItemString(kwargs, "headers", py_headers);

    // ── path_params dict from StringHashMap ──
    const py_path_params = c.PyDict_New() orelse return errorResponse(err_ct, err_body);
    defer c.Py_DecRef(py_path_params);
    {
        for (params.entries()) |pe| {
            const pk = py.newString(pe.key) orelse continue;
            const pv = py.newString(pe.value) orelse {
                c.Py_DecRef(pk);
                continue;
            };
            _ = c.PyDict_SetItem(py_path_params, pk, pv);
            c.Py_DecRef(pk);
            c.Py_DecRef(pv);
        }
    }
    _ = c.PyDict_SetItemString(kwargs, "path_params", py_path_params);

    // ── Call handler with PyObject_Call(handler, empty_tuple, kwargs) ──
    const empty_tuple = c.PyTuple_New(0) orelse return errorResponse(err_ct, err_body);
    defer c.Py_DecRef(empty_tuple);

    var result = c.PyObject_Call(entry.handler, empty_tuple, kwargs) orelse {
        c.PyErr_Print();
        return errorResponse(err_ct, err_body);
    };
    defer c.Py_DecRef(result);

    // ── Async handler support: await coroutine via asyncio.run() ──
    if (c.PyCoro_CheckExact(result) != 0) {
        const asyncio = c.PyImport_ImportModule("asyncio") orelse {
            c.PyErr_Print();
            return errorResponse(err_ct, err_body);
        };
        defer c.Py_DecRef(asyncio);
        const run_fn = c.PyObject_GetAttrString(asyncio, "run") orelse {
            c.PyErr_Print();
            return errorResponse(err_ct, err_body);
        };
        defer c.Py_DecRef(run_fn);
        const run_args = c.PyTuple_Pack(1, result) orelse return errorResponse(err_ct, err_body);
        defer c.Py_DecRef(run_args);
        const awaited = c.PyObject_CallObject(run_fn, run_args) orelse {
            c.PyErr_Print();
            return errorResponse(err_ct, err_body);
        };
        // Replace result with the awaited value
        c.Py_DecRef(result);
        result = awaited;
    }

    // ── Extract response fields from returned dict ──
    // status_code (default 200)
    var status_code: u16 = 200;
    if (c.PyDict_GetItemString(result, "status_code")) |sc| {
        const code = c.PyLong_AsLong(sc);
        if (code >= 100 and code <= 599) {
            status_code = @intCast(code);
        }
    }

    // content_type (default "application/json")
    var ct_slice: []const u8 = "application/json";
    if (c.PyDict_GetItemString(result, "content_type")) |ct_obj| {
        if (c.PyUnicode_AsUTF8(ct_obj)) |cs| {
            ct_slice = std.mem.span(cs);
        }
    }

    // content — json.dumps() if not already a string
    var body_slice: []const u8 = "null";
    if (c.PyDict_GetItemString(result, "content")) |content_obj| {
        if (c.PyUnicode_Check(content_obj) != 0) {
            // Already a string, use directly
            if (c.PyUnicode_AsUTF8(content_obj)) |cs| {
                body_slice = std.mem.span(cs);
            }
        } else {
            // Serialize via json.dumps()
            const json_mod = c.PyImport_ImportModule("json");
            if (json_mod) |jm| {
                defer c.Py_DecRef(jm);
                const dumps_fn = c.PyObject_GetAttrString(jm, "dumps");
                if (dumps_fn) |df| {
                    defer c.Py_DecRef(df);
                    const dump_args = c.PyTuple_Pack(1, content_obj);
                    if (dump_args) |da| {
                        defer c.Py_DecRef(da);
                        const json_result = c.PyObject_CallObject(df, da);
                        if (json_result) |jr| {
                            defer c.Py_DecRef(jr);
                            if (c.PyUnicode_AsUTF8(jr)) |cs| {
                                body_slice = std.mem.span(cs);
                            }
                        }
                    }
                }
            }
        }
    }

    // ── Return PythonResponse with owned copies ──
    const owned_ct = allocator.dupe(u8, ct_slice) catch return errorResponse(err_ct, err_body);
    const owned_body = allocator.dupe(u8, body_slice) catch {
        allocator.free(owned_ct);
        return errorResponse(err_ct, err_body);
    };

    return PythonResponse{
        .status_code = status_code,
        .content_type = owned_ct,
        .body = owned_body,
    };
}

fn errorResponse(ct: []const u8, body_str: []const u8) PythonResponse {
    const owned_ct = allocator.dupe(u8, ct) catch return PythonResponse{
        .status_code = 500,
        .content_type = &.{},
        .body = &.{},
    };
    const owned_body = allocator.dupe(u8, body_str) catch {
        allocator.free(owned_ct);
        return PythonResponse{
            .status_code = 500,
            .content_type = &.{},
            .body = &.{},
        };
    };
    return PythonResponse{
        .status_code = 500,
        .content_type = owned_ct,
        .body = owned_body,
    };
}

fn statusText(status: u16) []const u8 {
    return switch (status) {
        200 => "OK",
        201 => "Created",
        204 => "No Content",
        301 => "Moved Permanently",
        302 => "Found",
        304 => "Not Modified",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        405 => "Method Not Allowed",
        413 => "Payload Too Large",
        422 => "Unprocessable Entity",
        429 => "Too Many Requests",
        431 => "Request Header Fields Too Large",
        500 => "Internal Server Error",
        502 => "Bad Gateway",
        503 => "Service Unavailable",
        else => "Unknown",
    };
}

/// Zero-alloc response writer.  Header + body are concatenated into a stack
/// buffer for a single write syscall (most API responses are <4KB).
/// Falls back to two writes only for large responses.
pub fn sendResponse(stream: std.net.Stream, status: u16, content_type: []const u8, body: []const u8) void {
    // TFB requires Server + Date headers
    var date_buf: [40]u8 = undefined;
    const timestamp = std.time.timestamp();
    const epoch_secs: std.time.epoch.EpochSeconds = .{ .secs = @intCast(timestamp) };
    const day_secs = epoch_secs.getDaySeconds();
    const epoch_day = epoch_secs.getEpochDay();
    const year_day = epoch_day.calculateYearDay();
    const month_day = year_day.calculateMonthDay();
    const dow_idx: usize = @intCast(@mod(@as(i32, @intCast(epoch_day.day)) + 3, 7)); // 0=Mon
    const dow_names = [7][]const u8{ "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun" };
    const mon_names = [12][]const u8{ "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" };
    const dow_str = dow_names[dow_idx];
    const mon_str = mon_names[@intFromEnum(month_day.month) - 1];
    // RFC 2822: "Wed, 19 Mar 2026 11:30:27 GMT"
    const date_str = std.fmt.bufPrint(&date_buf, "{s}, {d:0>2} {s} {d} {d:0>2}:{d:0>2}:{d:0>2} GMT", .{
        dow_str, month_day.day_index + 1, mon_str, year_day.year,
        day_secs.getHoursIntoDay(), day_secs.getMinutesIntoHour(), day_secs.getSecondsIntoMinute(),
    }) catch "Thu, 01 Jan 2026 00:00:00 GMT";

    var header_buf: [512]u8 = undefined;
    const header = std.fmt.bufPrint(&header_buf,
        "HTTP/1.1 {d} {s}\r\nServer: TurboAPI\r\nDate: {s}\r\nContent-Type: {s}\r\nContent-Length: {d}\r\nConnection: keep-alive",
        .{ status, statusText(status), date_str, content_type, body.len },
    ) catch return;

    // Assemble: header + cors_headers (pre-rendered, "" if disabled) + \r\n\r\n + body
    const cors = cors_headers; // "" when disabled — zero overhead
    const trailer = "\r\n\r\n";
    const total = header.len + cors.len + trailer.len + body.len;
    if (total <= 4096) {
        var resp_buf: [4096]u8 = undefined;
        var pos: usize = 0;
        @memcpy(resp_buf[pos..pos + header.len], header);
        pos += header.len;
        if (cors.len > 0) {
            @memcpy(resp_buf[pos..pos + cors.len], cors);
            pos += cors.len;
        }
        @memcpy(resp_buf[pos..pos + trailer.len], trailer);
        pos += trailer.len;
        @memcpy(resp_buf[pos..pos + body.len], body);
        pos += body.len;
        stream.writeAll(resp_buf[0..pos]) catch return;
    } else {
        stream.writeAll(header) catch return;
        if (cors.len > 0) stream.writeAll(cors) catch return;
        stream.writeAll(trailer) catch return;
        if (body.len > 0) stream.writeAll(body) catch return;
    }
}

// ── configure_rate_limiting(enabled, requests_per_minute) ──

pub fn configure_rate_limiting(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    // No-op for now – will implement later
    return py.pyNone();
}


// ── Fuzz tests ───────────────────────────────────────────────────────────────
// Run: zig build fuzz-http  (then execute the binary with --fuzz)
//
// These tests exercise the parsing functions used by handleOneRequest.
// The invariants are: no panics, no out-of-bounds access, bounded output.

fn fuzz_percentDecode(_: void, input: []const u8) anyerror!void {
    var buf: [4096]u8 = undefined;
    const out = percentDecode(input, &buf);
    // Decoded output is never longer than percent-encoded input
    try std.testing.expect(out.len <= input.len);
    // Output must fit in buffer
    try std.testing.expect(out.len <= buf.len);
    // Output must be a subslice of buf
    const buf_start = @intFromPtr(&buf);
    const buf_end   = buf_start + buf.len;
    const out_start = @intFromPtr(out.ptr);
    try std.testing.expect(out_start >= buf_start and out_start <= buf_end);
}

test "fuzz: percentDecode — output bounded, no OOB" {
    try std.testing.fuzz({}, fuzz_percentDecode, .{ .corpus = &.{
        "%00",                              // null byte
        "%GG",                              // invalid hex digits
        "%",                                // bare percent at end of input
        "%2",                               // truncated percent sequence
        "hello+world",                      // plus → space
        "a%20b%20c",                        // spaces
        "%FF%FE%FD",                        // high bytes
        &([_]u8{'%'} ** 200),               // 200 bare percents
        "%2F%2F..%2F..%2Fetc%2Fpasswd",    // path traversal
        "%00%00%00",                        // three null bytes
    }});
}

fn fuzz_queryStringGet(_: void, input: []const u8) anyerror!void {
    // Split: first 16 bytes = key, remainder = query string
    const split = @min(input.len, 16);
    const key = input[0..split];
    const qs  = if (split < input.len) input[split..] else "";

    const result = queryStringGet(qs, key);
    if (result) |v| {
        // Returned slice must be within the query string buffer
        const qs_start = @intFromPtr(qs.ptr);
        const qs_end   = qs_start + qs.len;
        const v_start  = @intFromPtr(v.ptr);
        try std.testing.expect(v_start >= qs_start and v_start <= qs_end);
    }
}

test "fuzz: queryStringGet — result is within input, no panic" {
    try std.testing.fuzz({}, fuzz_queryStringGet, .{ .corpus = &.{
        "key" ++ "key=value",
        "x"   ++ "x=1&y=2&z=3",
        "a"   ++ "a=&b=c",
        "k"   ++ "k",
        ""    ++ "=value",
        "foo" ++ "foo=bar&foo=baz",         // duplicate key
        "q"   ++ "q=" ++ ("A" ** 2000),     // very long value
        "k"   ++ "k=\x00\xFF",              // binary values
        "k"   ++ "&&&&&",                   // no values, only separators
    }});
}

fn fuzz_requestLineParsing(_: void, input: []const u8) anyerror!void {
    if (input.len == 0) return;

    // The parser searches for \r\n\r\n to delimit headers from body.
    // If absent → server returns 431 and stops. We mirror that.
    const he = std.mem.indexOf(u8, input, "\r\n\r\n") orelse return;

    // Parse the first line (request line).
    const first_line_end = std.mem.indexOf(u8, input[0..he], "\r\n") orelse return;
    const first_line = input[0..first_line_end];

    var parts = std.mem.splitScalar(u8, first_line, ' ');
    const method   = parts.next() orelse return;
    const raw_path = parts.next() orelse return;
    _ = method;

    // Split path from query string at '?'
    const q_idx        = std.mem.indexOf(u8, raw_path, "?");
    const path         = if (q_idx) |i| raw_path[0..i] else raw_path;
    const query_string = if (q_idx) |i| raw_path[i + 1 ..] else "";
    _ = path;
    _ = query_string;

    // Parse headers — real function, same file
    const request_head = input[0 .. he + 4];
    var headers = parseHeaders(request_head, first_line_end, he);
    defer headers.deinit(allocator);

    // Validate Content-Length parsing on adversarial values
    for (headers.items) |h| {
        if (std.ascii.eqlIgnoreCase(h.name, "content-length")) {
            const cl = std.fmt.parseInt(usize, h.value, 10) catch 0;
            const max_body: usize = 16 * 1024 * 1024;
            _ = @min(cl, max_body);
        }
    }
}

test "fuzz: HTTP request-line and header parsing — no panic on malformed input" {
    try std.testing.fuzz({}, fuzz_requestLineParsing, .{ .corpus = &.{
        // Minimal valid GET
        "GET / HTTP/1.1\r\nHost: localhost\r\n\r\n",
        // Valid POST with body
        "POST /items HTTP/1.1\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}",
        // Missing HTTP version token
        "GET /\r\n\r\n",
        // Empty method
        " / HTTP/1.1\r\n\r\n",
        // Huge Content-Length (parser must cap it)
        "POST / HTTP/1.1\r\nContent-Length: 99999999999999999999\r\n\r\n",
        // Negative Content-Length (parseInt → error → 0)
        "POST / HTTP/1.1\r\nContent-Length: -1\r\n\r\n",
        // CRLF injection attempt in header value
        "GET / HTTP/1.1\r\nX-Header: value\r\nInjected: header\r\n\r\n",
        // Header with no colon (should be skipped)
        "GET / HTTP/1.1\r\nMalformedHeaderLine\r\n\r\n",
        // Null byte in path
        "GET /\x00secret HTTP/1.1\r\n\r\n",
        // Very long path (> 8KB header buffer)
        "GET /" ++ ("a" ** 7000) ++ " HTTP/1.1\r\n\r\n",
        // Very long header value
        "GET / HTTP/1.1\r\nX-Custom: " ++ ("B" ** 7000) ++ "\r\n\r\n",
        // Bare \n instead of \r\n
        "GET / HTTP/1.1\nHost: x\n\n",
        // No path at all
        "GET HTTP/1.1\r\n\r\n",
        // Method with no space
        "GETHTTP/1.1\r\n\r\n",
        // Percent-encoded path
        "GET /users%2F42 HTTP/1.1\r\n\r\n",
        // Query string with adversarial chars
        "GET /search?q=%00&limit=-1&page=\xFF HTTP/1.1\r\n\r\n",
    }});
}
