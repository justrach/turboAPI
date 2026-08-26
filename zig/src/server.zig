// TurboServer – Zig HTTP server core.
// Placeholder that registers routes and runs an event loop.
// The actual HTTP serving uses Zig's std.Io.net (0.16+).

const std = @import("std");
const py = @import("py.zig");
const c = py.c;
const core = @import("turboapi-core");
const router_mod = core.router;
const dhi = @import("dhi_validator.zig");
const db = @import("db.zig");
const multipart_mod = @import("multipart.zig");
const logger = @import("logger.zig");
const runtime = @import("runtime.zig");
const telemetry = @import("telemetry.zig");
const ws = @import("websocket.zig");

const allocator = std.heap.c_allocator;
const posix = std.posix;

// Zig 0.16: std.posix.write removed, std.time.timestamp() removed.
// Use C-level write() and clock_gettime() directly.
extern "c" fn write(fd: c_int, buf: [*]const u8, nbytes: usize) isize;

fn streamWriteAll(stream: std.Io.net.Stream, data: []const u8) !void {
    var remaining = data;
    while (remaining.len > 0) {
        const n = write(stream.socket.handle, remaining.ptr, remaining.len);
        if (n <= 0) return error.BrokenPipe;
        remaining = remaining[@intCast(n)..];
    }
}

fn timestampSeconds() i64 {
    var ts: std.c.timespec = undefined;
    _ = std.c.clock_gettime(.REALTIME, &ts);
    return ts.sec;
}

threadlocal var cached_date_second: i64 = -1;
threadlocal var cached_date_buf: [40]u8 = undefined;
threadlocal var cached_date_len: usize = 0;

fn currentHttpDate() []const u8 {
    const timestamp = timestampSeconds();
    if (cached_date_second == timestamp and cached_date_len > 0) {
        return cached_date_buf[0..cached_date_len];
    }

    const epoch_secs: std.time.epoch.EpochSeconds = .{ .secs = @intCast(timestamp) };
    const day_secs = epoch_secs.getDaySeconds();
    const epoch_day = epoch_secs.getEpochDay();
    const year_day = epoch_day.calculateYearDay();
    const month_day = year_day.calculateMonthDay();
    const dow_idx: usize = @intCast(@mod(@as(i32, @intCast(epoch_day.day)) + 3, 7)); // 0=Mon
    const dow_names = [7][]const u8{ "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun" };
    const mon_names = [12][]const u8{ "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" };

    const formatted = std.fmt.bufPrint(&cached_date_buf, "{s}, {d:0>2} {s} {d} {d:0>2}:{d:0>2}:{d:0>2} GMT", .{
        dow_names[dow_idx],         month_day.day_index + 1,       mon_names[@backingInt(month_day.month) - 1], year_day.year,
        day_secs.getHoursIntoDay(), day_secs.getMinutesIntoHour(), day_secs.getSecondsIntoMinute(),
    }) catch {
        const fallback = "Thu, 01 Jan 2026 00:00:00 GMT";
        @memcpy(cached_date_buf[0..fallback.len], fallback);
        cached_date_second = timestamp;
        cached_date_len = fallback.len;
        return cached_date_buf[0..cached_date_len];
    };

    cached_date_second = timestamp;
    cached_date_len = formatted.len;
    return cached_date_buf[0..cached_date_len];
}

// ── Route storage ───────────────────────────────────────────────────────────

const MAX_PARAMS: usize = 16;

const ParamType = enum(u8) { str, int, float, bool_val };

const ParamMeta = struct {
    name: []const u8,
    type_tag: ParamType,
    has_default: bool, // true → skip if missing (let Python use its own default)
};

const param_type_map = std.StaticStringMap(ParamType).initComptime(.{
    .{ "int", .int },
    .{ "float", .float },
    .{ "bool", .bool_val },
});

fn parseParamType(s: []const u8) ParamType {
    return param_type_map.get(s) orelse .str;
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
        // Bulk-copy clean bytes: SIMD-accelerated indexOfAny skips to next '%' or '+'
        const next = std.mem.indexOfAny(u8, src[i..], "%+") orelse (src.len - i);
        if (next > 0) {
            const copy_len = @min(next, buf.len - out);
            @memcpy(buf[out..][0..copy_len], src[i..][0..copy_len]);
            out += copy_len;
            i += copy_len;
            if (copy_len < next) break; // buf full
            continue;
        }
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
    simple_async,
    simple_async_eager,
    body_async,
    body_async_eager,
    form_sync,
    file_sync,
    enhanced,
};

const handler_type_map = std.StaticStringMap(HandlerType).initComptime(.{
    .{ "simple_sync_noargs", .simple_sync_noargs },
    .{ "simple_sync", .simple_sync },
    .{ "model_sync", .model_sync },
    .{ "body_sync", .body_sync },
    .{ "simple_async", .simple_async },
    .{ "simple_async_eager", .simple_async_eager },
    .{ "body_async", .body_async },
    .{ "body_async_eager", .body_async_eager },
    .{ "form_sync", .form_sync },
    .{ "file_sync", .file_sync },
});

fn parseHandlerType(s: []const u8) HandlerType {
    return handler_type_map.get(s) orelse .enhanced;
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
    cached_body_ptr: std.atomic.Value(usize) = std.atomic.Value(usize).init(0),
    cached_body_len: std.atomic.Value(usize) = std.atomic.Value(usize).init(0),
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
var response_cache_lock: std.Io.Mutex = .init;
var response_cache_count: usize = 0;
const MAX_CACHE_ENTRIES: usize = 10_000; // bounded to prevent OOM via unique paths
var model_schemas: ?std.StringHashMap(dhi.ModelSchema) = null;
var router: ?router_mod.Router = null;
var server_host: []const u8 = "127.0.0.1";
var server_port: u16 = 8000;
var cache_noargs_responses: bool = false;

var asyncio_run_fn: ?*c.PyObject = null;
var turbo_run_coroutine_fn: ?*c.PyObject = null;
var turbo_run_coroutine_response_fn: ?*c.PyObject = null;
var turbo_run_coroutine_response_eager_fn: ?*c.PyObject = null;

fn getAsyncioRunFn() ?*c.PyObject {
    if (asyncio_run_fn) |run_fn| return run_fn;

    const asyncio = c.PyImport_ImportModule("asyncio") orelse return null;
    defer c.Py_DecRef(asyncio);

    asyncio_run_fn = c.PyObject_GetAttrString(asyncio, "run") orelse return null;
    return asyncio_run_fn;
}

fn getTurboRunCoroutineFn() ?*c.PyObject {
    if (turbo_run_coroutine_fn) |run_fn| return run_fn;

    const async_pool = c.PyImport_ImportModule("turboapi.async_pool") orelse return null;
    defer c.Py_DecRef(async_pool);

    turbo_run_coroutine_fn = c.PyObject_GetAttrString(async_pool, "run_coroutine") orelse return null;
    return turbo_run_coroutine_fn;
}

fn getTurboRunCoroutineResponseFn() ?*c.PyObject {
    if (turbo_run_coroutine_response_fn) |run_fn| return run_fn;

    const async_pool = c.PyImport_ImportModule("turboapi.async_pool") orelse return null;
    defer c.Py_DecRef(async_pool);

    turbo_run_coroutine_response_fn = c.PyObject_GetAttrString(async_pool, "run_coroutine_response") orelse return null;
    return turbo_run_coroutine_response_fn;
}

fn getTurboRunCoroutineResponseEagerFn() ?*c.PyObject {
    if (turbo_run_coroutine_response_eager_fn) |run_fn| return run_fn;

    const async_pool = c.PyImport_ImportModule("turboapi.async_pool") orelse return null;
    defer c.Py_DecRef(async_pool);

    turbo_run_coroutine_response_eager_fn = c.PyObject_GetAttrString(async_pool, "run_coroutine_response_eager") orelse return null;
    return turbo_run_coroutine_response_eager_fn;
}

fn awaitPythonCoroutine(coro: *c.PyObject) ?*c.PyObject {
    if (getTurboRunCoroutineFn()) |run_fn| {
        return py.PyObject_CallOneArg(run_fn, coro);
    }

    c.PyErr_Clear();
    const run_fn = getAsyncioRunFn() orelse return null;
    return py.PyObject_CallOneArg(run_fn, coro);
}

fn awaitPythonCoroutineResponse(coro: *c.PyObject) ?*c.PyObject {
    if (getTurboRunCoroutineResponseFn()) |run_fn| {
        return py.PyObject_CallOneArg(run_fn, coro);
    }

    c.PyErr_Clear();
    return null;
}

fn awaitPythonCoroutineResponseEager(coro: *c.PyObject) ?*c.PyObject {
    if (getTurboRunCoroutineResponseEagerFn()) |run_fn| {
        return py.PyObject_CallOneArg(run_fn, coro);
    }

    c.PyErr_Clear();
    return awaitPythonCoroutineResponse(coro);
}

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

fn getCachedResponse(key: []const u8) ?[]const u8 {
    response_cache_lock.lockUncancelable(runtime.io);
    defer response_cache_lock.unlock(runtime.io);
    if (response_cache == null) return null;
    return response_cache.?.get(key);
}

/// Cache a pre-rendered response, respecting MAX_CACHE_ENTRIES to prevent OOM.
fn cacheResponse(key: []const u8, rendered: []const u8) void {
    response_cache_lock.lockUncancelable(runtime.io);
    defer response_cache_lock.unlock(runtime.io);

    if (response_cache_count >= MAX_CACHE_ENTRIES) {
        allocator.free(rendered);
        return;
    }

    const key_dupe = allocator.dupe(u8, key) catch return;
    const cache = getResponseCache();
    const gop = cache.getOrPut(key_dupe) catch {
        allocator.free(rendered);
        allocator.free(key_dupe);
        return;
    };

    if (gop.found_existing) {
        allocator.free(rendered);
        allocator.free(key_dupe);
        return;
    }

    gop.value_ptr.* = rendered;
    response_cache_count += 1;
}

fn getCachedEntryBody(entry: *const HandlerEntry) ?[]const u8 {
    const ptr_val = entry.cached_body_ptr.load(.acquire);
    if (ptr_val == 0) return null;

    const len = entry.cached_body_len.load(.acquire);
    const ptr: [*]const u8 = @ptrFromInt(ptr_val);
    return ptr[0..len];
}

fn cacheEntryBody(entry: *HandlerEntry, rendered: []const u8) void {
    response_cache_lock.lockUncancelable(runtime.io);
    defer response_cache_lock.unlock(runtime.io);

    if (entry.cached_body_ptr.load(.monotonic) != 0) {
        allocator.free(rendered);
        return;
    }

    if (response_cache_count >= MAX_CACHE_ENTRIES) {
        allocator.free(rendered);
        return;
    }

    entry.cached_body_len.store(rendered.len, .release);
    entry.cached_body_ptr.store(@intFromPtr(rendered.ptr), .release);
    response_cache_count += 1;
}

fn sendCachedJsonBody(stream: std.Io.net.Stream, body: []const u8) void {
    if (cors_headers.len > 0) {
        sendResponse(stream, 200, "application/json", body);
        return;
    }

    const date_str = currentHttpDate();
    var len_buf: [20]u8 = undefined;
    const len_str = std.fmt.bufPrint(&len_buf, "{d}", .{body.len}) catch return;

    const h1 = "HTTP/1.1 200 OK\r\nServer: TurboAPI\r\nDate: ";
    const h2 = "\r\nContent-Type: application/json\r\nContent-Length: ";
    const h3 = "\r\nConnection: keep-alive\r\n\r\n";
    const total = h1.len + date_str.len + h2.len + len_str.len + h3.len + body.len;

    if (total <= 4096) {
        var resp_buf: [4096]u8 = undefined;
        var pos: usize = 0;
        @memcpy(resp_buf[pos .. pos + h1.len], h1);
        pos += h1.len;
        @memcpy(resp_buf[pos .. pos + date_str.len], date_str);
        pos += date_str.len;
        @memcpy(resp_buf[pos .. pos + h2.len], h2);
        pos += h2.len;
        @memcpy(resp_buf[pos .. pos + len_str.len], len_str);
        pos += len_str.len;
        @memcpy(resp_buf[pos .. pos + h3.len], h3);
        pos += h3.len;
        @memcpy(resp_buf[pos .. pos + body.len], body);
        pos += body.len;
        streamWriteAll(stream, resp_buf[0..pos]) catch return;
    } else {
        streamWriteAll(stream, h1) catch return;
        streamWriteAll(stream, date_str) catch return;
        streamWriteAll(stream, h2) catch return;
        streamWriteAll(stream, len_str) catch return;
        streamWriteAll(stream, h3) catch return;
        if (body.len > 0) streamWriteAll(stream, body) catch return;
    }
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

    telemetry.init();
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

    if (std.mem.eql(u8, ht_s, "simple_sync") or std.mem.eql(u8, ht_s, "simple_async") or std.mem.eql(u8, ht_s, "simple_async_eager")) {
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
        logger.debug("[DHI] Registered schema for {s}: {d} fields", .{ key, schema.fields.len });
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
    const lib_path_z = allocator.dupeSentinel(u8, lib_path_s, 0) catch {
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
    const sym_z = allocator.dupeSentinel(u8, symbol_name_s, 0) catch {
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

    logger.debug("[FFI] Registered native handler: {s} {s} -> {s}:{s}", .{ method_s, path_s, lib_path_s, symbol_name_s });
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
    const response_bytes = std.fmt.allocPrint(
        allocator,
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

    logger.debug("[STATIC] Registered: {s} {s} -> {d} ({d} bytes pre-rendered)", .{ method_s, path_s, st, response_bytes.len });
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

    cors_headers = std.fmt.allocPrint(
        allocator,
        "\r\nAccess-Control-Allow-Origin: {s}" ++
            "\r\nAccess-Control-Allow-Methods: {s}" ++
            "\r\nAccess-Control-Allow-Headers: {s}" ++
            "{s}" ++
            "\r\nAccess-Control-Max-Age: {s}",
        .{ origins_s, methods_s, hdrs_s, cred_hdr, age_str },
    ) catch return null;
    cors_enabled = true;

    logger.info("[CORS] Zig-native CORS enabled: origin={s} methods={s}", .{ origins_s, methods_s });
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
    // Check if response cache is disabled via env var
    if (std.c.getenv("TURBO_DISABLE_RESPONSE_CACHE")) |_p| {
        const val = std.mem.span(_p);
        if (std.mem.eql(u8, val, "1") or std.mem.eql(u8, val, "true")) {
            cache_noargs_responses = false;
            logger.info("[CACHE] Response caching DISABLED via TURBO_DISABLE_RESPONSE_CACHE", .{});
            return py.pyNone();
        }
    }
    cache_noargs_responses = true;
    logger.info("[CACHE] Response caching enabled for noargs handlers", .{});
    return py.pyNone();
}

/// Pre-render a full HTTP response into a heap-allocated buffer.
fn renderResponse(status: u16, content_type: []const u8, body: []const u8) ?[]const u8 {
    const cors = cors_headers;
    // Note: Date is static for cached responses. TFB just needs the header present.
    var date_buf: [40]u8 = undefined;
    const ts = timestampSeconds();
    const es: std.time.epoch.EpochSeconds = .{ .secs = @intCast(ts) };
    const ds = es.getDaySeconds();
    const ed = es.getEpochDay();
    const yd = ed.calculateYearDay();
    const md = yd.calculateMonthDay();
    const di: usize = @intCast(@mod(@as(i32, @intCast(ed.day)) + 3, 7));
    const dw = [7][]const u8{ "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun" };
    const mn = [12][]const u8{ "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" };
    const dt = std.fmt.bufPrint(&date_buf, "{s}, {d:0>2} {s} {d} {d:0>2}:{d:0>2}:{d:0>2} GMT", .{
        dw[di],               md.day_index + 1,        mn[@backingInt(md.month) - 1], yd.year,
        ds.getHoursIntoDay(), ds.getMinutesIntoHour(), ds.getSecondsIntoMinute(),
    }) catch "Thu, 01 Jan 2026 00:00:00 GMT";
    return std.fmt.allocPrint(
        allocator,
        "HTTP/1.1 {d} {s}\r\nServer: TurboAPI\r\nDate: {s}\r\nContent-Type: {s}\r\nContent-Length: {d}\r\nConnection: keep-alive{s}\r\n\r\n{s}",
        .{ status, statusText(status), dt, content_type, body.len, cors, body },
    ) catch null;
}

// ── run() – start the HTTP server ──

// ── Thread pool for connection handling ─────────────────────────────────────

// Keep the native storage bounded, while allowing deployments with many
// concurrent keep-alive connections to choose a larger pool explicitly. The
// default remains conservative; TURBO_THREAD_POOL_SIZE controls active workers.
const MAX_POOL_SIZE = 512;
const DEFAULT_POOL_SIZE = 24;
const DEFAULT_WS_POOL_SIZE = 24;
const MAX_WS_QUEUE_MESSAGES = 1024;
const MAX_WS_QUEUE_BYTES = 16 * 1024 * 1024;
const DEFAULT_WS_QUEUE_MESSAGES = 64;
const DEFAULT_WS_QUEUE_BYTES = 16 * 1024 * 1024;
const DEFAULT_WS_WRITE_TIMEOUT_MS = 5000;
const MIN_WS_WRITE_TIMEOUT_MS = 100;
const MAX_WS_WRITE_TIMEOUT_MS = 30000;

var ws_queue_message_limit: usize = DEFAULT_WS_QUEUE_MESSAGES;
var ws_queue_byte_limit: usize = DEFAULT_WS_QUEUE_BYTES;
var ws_write_timeout_ms: usize = DEFAULT_WS_WRITE_TIMEOUT_MS;
var http_header_timeout_ms: usize = 30000;

/// WebSockets use a dedicated pool, so a long-lived socket never occupies an
/// ordinary HTTP worker. Admission remains bounded to the WebSocket pool size;
/// this also bounds the number of per-connection Python event loops and reader
/// tasks regardless of client behavior.
const WebSocketCapacity = struct {
    worker_count: usize,
    max_active: usize,
};

var active_websockets: std.atomic.Value(usize) = .init(0);
var max_active_websockets: std.atomic.Value(usize) = .init(0);
var actual_websocket_workers: std.atomic.Value(usize) = .init(0);

/// Parse the cross-language WebSocket numeric environment contract: non-empty
/// ASCII decimal digits representing a u64. Signs, whitespace, non-ASCII
/// digits, and overflow are invalid. Leading zeroes are valid.
fn parseStrictDecimalU64(raw: []const u8) ?u64 {
    if (raw.len == 0) return null;
    var value: u64 = 0;
    for (raw) |byte| {
        if (byte < '0' or byte > '9') return null;
        const multiplied = @mulWithOverflow(value, @as(u64, 10));
        if (multiplied[1] != 0) return null;
        const added = @addWithOverflow(multiplied[0], @as(u64, byte - '0'));
        if (added[1] != 0) return null;
        value = added[0];
    }
    return value;
}

fn normalizeBoundedUsize(
    raw: ?[]const u8,
    fallback: usize,
    hard_min: usize,
    hard_max: usize,
) usize {
    std.debug.assert(hard_min <= hard_max);
    const parsed = parseStrictDecimalU64(raw orelse return fallback) orelse return fallback;
    const bounded = @min(@max(@as(u64, @intCast(hard_min)), parsed), @as(u64, @intCast(hard_max)));
    return @intCast(bounded);
}

fn readBoundedUsizeEnv(
    name: [*:0]const u8,
    fallback: usize,
    hard_min: usize,
    hard_max: usize,
) usize {
    const ptr = std.c.getenv(name) orelse return fallback;
    return normalizeBoundedUsize(std.mem.span(ptr), fallback, hard_min, hard_max);
}

test "strict numeric environment normalization matches Python contract" {
    const invalid = [_]?[]const u8{
        null,
        "",
        "-1",
        " 1",
        "1 ",
        "+1",
        "invalid",
        "\xd9\xa1",
        "18446744073709551616",
    };
    for (invalid) |raw| {
        try std.testing.expectEqual(@as(usize, 64), normalizeBoundedUsize(raw, 64, 1, 1024));
        try std.testing.expectEqual(@as(usize, 24), normalizeBoundedUsize(raw, 24, 0, MAX_POOL_SIZE));
    }

    try std.testing.expectEqual(@as(usize, 1), normalizeBoundedUsize("0", 64, 1, 1024));
    try std.testing.expectEqual(@as(usize, 0), normalizeBoundedUsize("0", 24, 0, MAX_POOL_SIZE));
    try std.testing.expectEqual(@as(usize, 7), normalizeBoundedUsize("7", 64, 1, 1024));
    try std.testing.expectEqual(@as(usize, 1), normalizeBoundedUsize("1", 64, 1, 1024));
    try std.testing.expectEqual(@as(usize, 1024), normalizeBoundedUsize("1024", 64, 1, 1024));
    try std.testing.expectEqual(@as(usize, 1024), normalizeBoundedUsize("1025", 64, 1, 1024));
    try std.testing.expectEqual(@as(usize, 1024), normalizeBoundedUsize("18446744073709551615", 64, 1, 1024));
    try std.testing.expectEqual(@as(usize, 1), normalizeBoundedUsize("000000000000000000000000000000000000", 64, 1, 1024));

    // Every actual WebSocket setting uses the same parser with its own bounds.
    const worker_min = normalizeBoundedUsize("0", DEFAULT_WS_POOL_SIZE, 0, MAX_POOL_SIZE);
    const worker_max = normalizeBoundedUsize("512", DEFAULT_WS_POOL_SIZE, 0, MAX_POOL_SIZE);
    const active_min = normalizeBoundedUsize("0", worker_max, 0, MAX_POOL_SIZE);
    const active_max = normalizeBoundedUsize("512", worker_max, 0, MAX_POOL_SIZE);
    try std.testing.expectEqual(@as(usize, 0), worker_min);
    try std.testing.expectEqual(@as(usize, 512), worker_max);
    try std.testing.expectEqual(@as(usize, 0), active_min);
    try std.testing.expectEqual(@as(usize, 512), active_max);
    try std.testing.expectEqual(@as(usize, 1), normalizeBoundedUsize("1", DEFAULT_WS_QUEUE_MESSAGES, 1, MAX_WS_QUEUE_MESSAGES));
    try std.testing.expectEqual(@as(usize, MAX_WS_QUEUE_MESSAGES), normalizeBoundedUsize("1024", DEFAULT_WS_QUEUE_MESSAGES, 1, MAX_WS_QUEUE_MESSAGES));
    try std.testing.expectEqual(@as(usize, 1), normalizeBoundedUsize("1", DEFAULT_WS_QUEUE_BYTES, 1, MAX_WS_QUEUE_BYTES));
    try std.testing.expectEqual(@as(usize, MAX_WS_QUEUE_BYTES), normalizeBoundedUsize("16777216", DEFAULT_WS_QUEUE_BYTES, 1, MAX_WS_QUEUE_BYTES));
    try std.testing.expectEqual(@as(usize, MIN_WS_WRITE_TIMEOUT_MS), normalizeBoundedUsize("100", DEFAULT_WS_WRITE_TIMEOUT_MS, MIN_WS_WRITE_TIMEOUT_MS, MAX_WS_WRITE_TIMEOUT_MS));
    try std.testing.expectEqual(@as(usize, MAX_WS_WRITE_TIMEOUT_MS), normalizeBoundedUsize("30000", DEFAULT_WS_WRITE_TIMEOUT_MS, MIN_WS_WRITE_TIMEOUT_MS, MAX_WS_WRITE_TIMEOUT_MS));
}

fn clampWebSocketCapacity(worker_count: usize, requested_max: usize) WebSocketCapacity {
    if (worker_count == 0) return .{ .worker_count = 0, .max_active = 0 };
    return .{
        .worker_count = worker_count,
        .max_active = @min(requested_max, worker_count),
    };
}

fn capacityAfterWorkerSpawns(successful_workers: usize, requested_max: usize) error{NoWorkers}!WebSocketCapacity {
    if (successful_workers == 0) return error.NoWorkers;
    return clampWebSocketCapacity(successful_workers, requested_max);
}

test "WebSocket capacity follows partial worker spawn success" {
    const partial = try capacityAfterWorkerSpawns(3, 24);
    try std.testing.expectEqual(@as(usize, 3), partial.worker_count);
    try std.testing.expectEqual(@as(usize, 3), partial.max_active);

    const disabled_admission = try capacityAfterWorkerSpawns(3, 0);
    try std.testing.expectEqual(@as(usize, 3), disabled_admission.worker_count);
    try std.testing.expectEqual(@as(usize, 0), disabled_admission.max_active);

    try std.testing.expectError(error.NoWorkers, capacityAfterWorkerSpawns(0, 24));
}

fn webSocketCapacity() WebSocketCapacity {
    const worker_count = readBoundedUsizeEnv("TURBO_WS_WORKER_POOL_SIZE", DEFAULT_WS_POOL_SIZE, 0, MAX_POOL_SIZE);
    const requested_max = readBoundedUsizeEnv("TURBO_MAX_WEBSOCKETS", worker_count, 0, MAX_POOL_SIZE);
    return clampWebSocketCapacity(worker_count, requested_max);
}

fn tryAcquireWebSocketSlot() bool {
    if (!ws_pool_gate.isReady()) return false;
    const limit = max_active_websockets.load(.acquire);
    var current = active_websockets.load(.acquire);
    while (current < limit) {
        if (active_websockets.cmpxchgWeak(current, current + 1, .acq_rel, .acquire)) |observed| {
            current = observed;
            continue;
        }
        return true;
    }
    return false;
}

fn releaseWebSocketSlot() void {
    const previous = active_websockets.fetchSub(1, .acq_rel);
    std.debug.assert(previous > 0);
}

/// Shared bounded spawn policy. The callback owns each successful worker
/// handle (production detaches it); stopping at the first failure preserves a
/// deterministic partial count without ever panicking or oversubscribing.
fn startBoundedWorkers(
    requested_count: usize,
    context: anytype,
    comptime start_one: anytype,
) error{NoWorkers}!usize {
    var started: usize = 0;
    while (started < @min(requested_count, MAX_POOL_SIZE)) {
        if (!start_one(context)) break;
        started += 1;
    }
    if (started == 0) return error.NoWorkers;
    return started;
}

const ProcessInitGate = struct {
    lock: std.atomic.Mutex = .unlocked,
    ready: std.atomic.Value(bool) = .init(false),

    /// Returns true with the init lock held only for the single initializer.
    fn begin(self: *ProcessInitGate) bool {
        if (self.ready.load(.acquire)) return false;
        while (!self.lock.tryLock()) std.atomic.spinLoopHint();
        if (self.ready.load(.monotonic)) {
            self.lock.unlock();
            return false;
        }
        return true;
    }

    fn publish(self: *ProcessInitGate) void {
        self.ready.store(true, .release);
        self.lock.unlock();
    }

    fn abort(self: *ProcessInitGate) void {
        self.lock.unlock();
    }

    fn isReady(self: *const ProcessInitGate) bool {
        return self.ready.load(.acquire);
    }
};

test "process initialization gate admits exactly one concurrent initializer" {
    const Context = struct {
        gate: *ProcessInitGate,
        initializations: *std.atomic.Value(usize),

        fn run(context: *@This()) void {
            if (!context.gate.begin()) return;
            _ = context.initializations.fetchAdd(1, .acq_rel);
            context.gate.publish();
        }
    };

    var gate = ProcessInitGate{};
    var initializations: std.atomic.Value(usize) = .init(0);
    var context = Context{ .gate = &gate, .initializations = &initializations };
    var threads: [32]std.Thread = undefined;
    for (&threads) |*thread| thread.* = try std.Thread.spawn(.{}, Context.run, .{&context});
    for (threads) |thread| thread.join();

    try std.testing.expect(gate.isReady());
    try std.testing.expectEqual(@as(usize, 1), initializations.load(.acquire));
}

test "process initialization gate publishes only after success and permits retry" {
    var gate = ProcessInitGate{};
    try std.testing.expect(gate.begin());
    try std.testing.expect(!gate.isReady());
    gate.abort();
    try std.testing.expect(!gate.isReady());

    try std.testing.expect(gate.begin());
    try std.testing.expect(!gate.isReady());
    gate.publish();
    try std.testing.expect(gate.isReady());
    try std.testing.expect(!gate.begin());
}

test "bounded worker spawn policy reports zero and partial failures" {
    const FakeSpawner = struct {
        remaining: usize,

        fn start(self: *@This()) bool {
            if (self.remaining == 0) return false;
            self.remaining -= 1;
            return true;
        }
    };

    var zero = FakeSpawner{ .remaining = 0 };
    try std.testing.expectError(error.NoWorkers, startBoundedWorkers(24, &zero, FakeSpawner.start));

    var partial = FakeSpawner{ .remaining = 3 };
    try std.testing.expectEqual(@as(usize, 3), try startBoundedWorkers(24, &partial, FakeSpawner.start));

    var capped = FakeSpawner{ .remaining = MAX_POOL_SIZE + 10 };
    try std.testing.expectEqual(@as(usize, MAX_POOL_SIZE), try startBoundedWorkers(MAX_POOL_SIZE + 10, &capped, FakeSpawner.start));
}

const ConnectionPool = struct {
    queue: Queue = .{},
    thread_count: usize = 0,

    const Queue = struct {
        items: [4096]std.Io.net.Stream = undefined,
        head: usize = 0,
        tail: usize = 0,
        count: usize = 0,
        mutex: std.Io.Mutex = .init,
        not_empty: std.Io.Condition = .init,

        fn push(self: *Queue, stream: std.Io.net.Stream) void {
            self.mutex.lockUncancelable(runtime.io);
            defer self.mutex.unlock(runtime.io);
            if (self.count >= self.items.len) {
                stream.close(runtime.io);
                return;
            }
            self.items[self.tail] = stream;
            self.tail = (self.tail + 1) % self.items.len;
            self.count += 1;
            self.not_empty.signal(runtime.io);
        }

        fn pop(self: *Queue) std.Io.net.Stream {
            self.mutex.lockUncancelable(runtime.io);
            defer self.mutex.unlock(runtime.io);
            while (self.count == 0) {
                self.not_empty.waitUncancelable(runtime.io, &self.mutex);
            }
            const stream = self.items[self.head];
            self.head = (self.head + 1) % self.items.len;
            self.count -= 1;
            return stream;
        }
    };

    fn init(self: *ConnectionPool, requested_count: usize, interp: ?*anyopaque) error{NoWorkers}!usize {
        std.debug.assert(self.thread_count == 0);
        self.queue = .{};
        const worker_limit = @min(requested_count, MAX_POOL_SIZE);
        if (worker_limit == 0 or interp == null) return error.NoWorkers;

        const SpawnContext = struct {
            queue: *Queue,
            interp: ?*anyopaque,

            fn start(context: *@This()) bool {
                const tstate = py.PyThreadState_New(context.interp) orelse {
                    c.PyErr_Clear();
                    return false;
                };
                const thread = std.Thread.spawn(.{}, workerLoop, .{ context.queue, tstate }) catch {
                    py.PyThreadState_Clear(tstate);
                    py.PyThreadState_Delete(tstate);
                    return false;
                };
                thread.detach();
                return true;
            }
        };
        var context = SpawnContext{ .queue = &self.queue, .interp = interp };
        const started = startBoundedWorkers(worker_limit, &context, SpawnContext.start) catch {
            self.thread_count = 0;
            return error.NoWorkers;
        };
        self.thread_count = started;
        return started;
    }

    // Each worker creates its own PyThreadState once and reuses it for every
    // request. This replaces PyGILState_Ensure/Release (which re-does a
    // thread-state lookup on every call) with the cheaper AcquireThread path.
    fn workerLoop(queue: *Queue, tstate: ?*anyopaque) void {
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

var pool: ConnectionPool = .{};
var pool_gate: ProcessInitGate = .{};
var pool_interp: ?*anyopaque = null;
var actual_http_workers: std.atomic.Value(usize) = .init(0);

const HttpRuntimeConfig = struct {
    worker_count: usize,
    header_timeout_ms: usize,
};

fn ensureConnectionPool(
    requested_count: usize,
    requested_header_timeout_ms: usize,
    interp: ?*anyopaque,
) error{ NoWorkers, DifferentInterpreter }!HttpRuntimeConfig {
    if (!pool_gate.begin()) {
        if (interp == null or interp != pool_interp) return error.DifferentInterpreter;
        return .{
            .worker_count = actual_http_workers.load(.acquire),
            .header_timeout_ms = http_header_timeout_ms,
        };
    }
    errdefer pool_gate.abort();

    const started = try pool.init(requested_count, interp);
    pool_interp = interp;
    http_header_timeout_ms = requested_header_timeout_ms;
    actual_http_workers.store(started, .release);
    pool_gate.publish();
    return .{
        .worker_count = started,
        .header_timeout_ms = http_header_timeout_ms,
    };
}

const WebSocketPool = struct {
    queue: Queue = .{},
    thread_count: usize = 0,

    const Queue = struct {
        // Admission is capped at MAX_POOL_SIZE, so this queue can never grow
        // without bound even if all WS workers are momentarily between jobs.
        items: [MAX_POOL_SIZE]WebSocketJob = undefined,
        head: usize = 0,
        tail: usize = 0,
        count: usize = 0,
        mutex: std.Io.Mutex = .init,
        not_empty: std.Io.Condition = .init,

        fn push(self: *Queue, job: WebSocketJob) bool {
            self.mutex.lockUncancelable(runtime.io);
            defer self.mutex.unlock(runtime.io);
            if (self.count >= self.items.len) return false;
            self.items[self.tail] = job;
            self.tail = (self.tail + 1) % self.items.len;
            self.count += 1;
            self.not_empty.signal(runtime.io);
            return true;
        }

        fn pop(self: *Queue) WebSocketJob {
            self.mutex.lockUncancelable(runtime.io);
            defer self.mutex.unlock(runtime.io);
            while (self.count == 0) self.not_empty.waitUncancelable(runtime.io, &self.mutex);
            const job = self.items[self.head];
            self.head = (self.head + 1) % self.items.len;
            self.count -= 1;
            return job;
        }
    };

    /// Initialize this process-global pool once. Python thread states are
    /// allocated while the starting server still owns the interpreter lock,
    /// so a worker cannot asynchronously panic during its own bootstrap.
    /// Successfully spawned workers are detached and retained for the process
    /// lifetime; a later spawn failure freezes the pool at the partial count.
    fn init(self: *WebSocketPool, requested_count: usize, interp: ?*anyopaque) error{NoWorkers}!usize {
        std.debug.assert(self.thread_count == 0);
        self.queue = .{};
        const worker_limit = @min(requested_count, MAX_POOL_SIZE);
        if (worker_limit == 0 or interp == null) return error.NoWorkers;

        const SpawnContext = struct {
            queue: *Queue,
            interp: ?*anyopaque,

            fn start(context: *@This()) bool {
                const tstate = py.PyThreadState_New(context.interp) orelse {
                    c.PyErr_Clear();
                    return false;
                };
                const thread = std.Thread.spawn(.{}, workerLoop, .{ context.queue, tstate }) catch {
                    py.PyThreadState_Clear(tstate);
                    py.PyThreadState_Delete(tstate);
                    return false;
                };
                thread.detach();
                return true;
            }
        };
        var context = SpawnContext{ .queue = &self.queue, .interp = interp };
        const started = startBoundedWorkers(worker_limit, &context, SpawnContext.start) catch {
            self.thread_count = 0;
            return error.NoWorkers;
        };
        self.thread_count = started;
        return started;
    }

    fn workerLoop(queue: *Queue, tstate: ?*anyopaque) void {
        defer {
            py.PyEval_AcquireThread(tstate);
            py.PyThreadState_Clear(tstate);
            py.PyThreadState_DeleteCurrent();
        }
        while (true) {
            var job = queue.pop();
            job.run(tstate);
            job.deinit(tstate);
        }
    }
};

var ws_pool: WebSocketPool = .{};
var ws_pool_gate: ProcessInitGate = .{};
var ws_pool_interp: ?*anyopaque = null;

const WebSocketRuntimeConfig = struct {
    capacity: WebSocketCapacity,
    queue_message_limit: usize,
    queue_byte_limit: usize,
    write_timeout_ms: usize,
};

fn requestedWebSocketRuntimeConfig() WebSocketRuntimeConfig {
    return .{
        .capacity = webSocketCapacity(),
        .queue_message_limit = readBoundedUsizeEnv("TURBO_WS_QUEUE_MESSAGES", DEFAULT_WS_QUEUE_MESSAGES, 1, MAX_WS_QUEUE_MESSAGES),
        .queue_byte_limit = readBoundedUsizeEnv("TURBO_WS_QUEUE_BYTES", DEFAULT_WS_QUEUE_BYTES, 1, MAX_WS_QUEUE_BYTES),
        .write_timeout_ms = readBoundedUsizeEnv("TURBO_WS_WRITE_TIMEOUT_MS", DEFAULT_WS_WRITE_TIMEOUT_MS, MIN_WS_WRITE_TIMEOUT_MS, MAX_WS_WRITE_TIMEOUT_MS),
    };
}

const WebSocketPoolInitError = error{ NoWorkers, DifferentInterpreter };

/// The dedicated WebSocket runtime is process-global and never shuts down.
/// Its first successful pool initialization freezes the worker/admission/
/// queue/deadline configuration. Later servers reuse the same queue/workers.
fn ensureWebSocketPool(
    requested: WebSocketRuntimeConfig,
    interp: ?*anyopaque,
) WebSocketPoolInitError!WebSocketRuntimeConfig {
    if (!ws_pool_gate.begin()) {
        if (interp == null or interp != ws_pool_interp) return error.DifferentInterpreter;
        return .{
            .capacity = .{
                .worker_count = actual_websocket_workers.load(.acquire),
                .max_active = max_active_websockets.load(.acquire),
            },
            .queue_message_limit = ws_queue_message_limit,
            .queue_byte_limit = ws_queue_byte_limit,
            .write_timeout_ms = ws_write_timeout_ms,
        };
    }
    errdefer ws_pool_gate.abort();

    const started = try ws_pool.init(requested.capacity.worker_count, interp);
    const effective_capacity = try capacityAfterWorkerSpawns(started, requested.capacity.max_active);
    ws_pool_interp = interp;
    ws_queue_message_limit = requested.queue_message_limit;
    ws_queue_byte_limit = requested.queue_byte_limit;
    ws_write_timeout_ms = requested.write_timeout_ms;
    max_active_websockets.store(effective_capacity.max_active, .release);
    actual_websocket_workers.store(effective_capacity.worker_count, .release);
    ws_pool_gate.publish();

    return .{
        .capacity = effective_capacity,
        .queue_message_limit = ws_queue_message_limit,
        .queue_byte_limit = ws_queue_byte_limit,
        .write_timeout_ms = ws_write_timeout_ms,
    };
}

pub fn server_run(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    // Initialize the shared Io runtime (no extra async threads — our ConnectionPool
    // manages workers via std.Thread.spawn to hook per-worker PyThreadState lifecycle).
    runtime.ensureInitialized(std.heap.c_allocator, .{
        .async_limit = .nothing,
    });

    const ip_addr = std.Io.net.IpAddress.parse(server_host, server_port) catch {
        py.setError("Invalid address: {s}:{d}", .{ server_host, server_port });
        return null;
    };

    var tcp_server = ip_addr.listen(runtime.io, .{ .reuse_address = true }) catch {
        py.setError("Failed to bind to {s}:{d}", .{ server_host, server_port });
        return null;
    };
    defer tcp_server.deinit(runtime.io);

    // Capture this call's interpreter without publishing it globally. Both
    // process pools bind to the first successful interpreter under their init
    // locks and reject a different interpreter before spawning more workers.
    const current_interp = py.PyInterpreterState_Get();
    if (getTurboRunCoroutineFn() == null and getAsyncioRunFn() == null) c.PyErr_Print();
    if (getTurboRunCoroutineResponseFn() == null) c.PyErr_Print();
    if (getTurboRunCoroutineResponseEagerFn() == null) c.PyErr_Print();

    var thread_count: usize = DEFAULT_POOL_SIZE;
    if (std.c.getenv("TURBO_THREAD_POOL_SIZE")) |_p| {
        const val = std.mem.span(_p);
        thread_count = std.fmt.parseInt(usize, val, 10) catch DEFAULT_POOL_SIZE;
        if (thread_count == 0) thread_count = DEFAULT_POOL_SIZE;
    }

    // Configure both independently bounded pools before either can receive a
    // connection. The WebSocket pool is process-global and exactly-once: the
    // first successful pool initialization freezes its settings. The ordinary
    // HTTP pool is process-global as well.
    const effective_thread_count = @min(thread_count, MAX_POOL_SIZE);
    const ws_config = ensureWebSocketPool(requestedWebSocketRuntimeConfig(), current_interp) catch |err| {
        switch (err) {
            error.NoWorkers => py.setError("WebSocket worker pool could not start any workers", .{}),
            error.DifferentInterpreter => py.setError("WebSocket worker pool belongs to a different Python interpreter", .{}),
        }
        return null;
    };

    // The ordinary pool is process-global for the same reason as the native
    // route tables and runtime. Repeated listeners enqueue into it instead of
    // resetting a queue under existing waiters.
    const http_config = ensureConnectionPool(
        effective_thread_count,
        readBoundedUsizeEnv("TURBO_HTTP_HEADER_TIMEOUT_MS", 30000, 100, 30000),
        current_interp,
    ) catch |err| {
        switch (err) {
            error.NoWorkers => py.setError("HTTP worker pool could not start any workers", .{}),
            error.DifferentInterpreter => py.setError("HTTP worker pool belongs to a different Python interpreter", .{}),
        }
        return null;
    };

    logger.info("TurboNet-Zig server listening on {s}:{d}", .{ server_host, server_port });
    logger.info("Zig HTTP core active – {d}-thread pool (process-global), per-worker tstate!", .{http_config.worker_count});
    logger.info("WebSocket isolation – {d}-thread process pool, max active={d}", .{ ws_config.capacity.worker_count, ws_config.capacity.max_active });

    // Release the GIL — workers acquire it per-request via AcquireThread.
    const save = py.PyEval_SaveThread();

    while (true) {
        const stream = tcp_server.accept(runtime.io) catch continue;
        pool.queue.push(stream);
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

/// The upgrade path must fail closed if header storage cannot be completed;
/// silently dropping a duplicate Authorization, Origin, Host, key, or version
/// header would make edge/core policy interpretation ambiguous.
const WebSocketHeaderParseError = error{ OutOfMemory, Malformed };

fn isHttpTokenChar(byte: u8) bool {
    if (std.ascii.isAlphanumeric(byte)) return true;
    return switch (byte) {
        '!', '#', '$', '%', '&', '\'', '*', '+', '-', '.', '^', '_', '`', '|', '~' => true,
        else => false,
    };
}

fn parseWebSocketHeaders(
    request_data: []const u8,
    first_line_end: usize,
    header_end_pos: usize,
) WebSocketHeaderParseError!HeaderList {
    return parseWebSocketHeadersWithAllocator(allocator, request_data, first_line_end, header_end_pos);
}

fn parseWebSocketHeadersWithAllocator(
    header_allocator: std.mem.Allocator,
    request_data: []const u8,
    first_line_end: usize,
    header_end_pos: usize,
) WebSocketHeaderParseError!HeaderList {
    var headers: HeaderList = .empty;
    errdefer headers.deinit(header_allocator);
    var pos = first_line_end + 2;
    while (pos < header_end_pos) {
        const line_end = std.mem.indexOfPos(u8, request_data, pos, "\r\n") orelse header_end_pos;
        const line = request_data[pos..line_end];
        pos = line_end + 2;
        if (line.len == 0) break;

        // RFC 9110 field names are tokens. Reject obs-fold, whitespace before
        // the colon, and malformed lines so a proxy and the authorization
        // guard cannot interpret the same bytes differently.
        const colon = std.mem.indexOfScalar(u8, line, ':') orelse return error.Malformed;
        const name = line[0..colon];
        if (name.len == 0) return error.Malformed;
        for (name) |byte| if (!isHttpTokenChar(byte)) return error.Malformed;
        const value = std.mem.trim(u8, line[colon + 1 ..], " \t");
        for (value) |byte| {
            if ((byte < 0x20 and byte != '\t') or byte == 0x7f)
                return error.Malformed;
        }
        headers.append(header_allocator, .{ .name = name, .value = value }) catch return error.OutOfMemory;
    }
    return headers;
}

fn allocateTestWebSocketHeaders(header_allocator: std.mem.Allocator) !void {
    const request = "GET /ws HTTP/1.1\r\nHost: example.test\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n";
    const first_line_end = std.mem.indexOf(u8, request, "\r\n").?;
    const header_end = std.mem.indexOf(u8, request, "\r\n\r\n").?;
    var headers = try parseWebSocketHeadersWithAllocator(header_allocator, request, first_line_end, header_end);
    headers.deinit(header_allocator);
}

test "WebSocket header parsing cleans allocation failures" {
    try std.testing.checkAllAllocationFailures(
        std.testing.allocator,
        allocateTestWebSocketHeaders,
        .{},
    );
}

test "WebSocket header parsing rejects ambiguous malformed lines" {
    const request = "GET /ws HTTP/1.1\r\nHost : example.test\r\n Upgrade: websocket\r\n\r\n";
    const first_line_end = std.mem.indexOf(u8, request, "\r\n").?;
    const header_end = std.mem.indexOf(u8, request, "\r\n\r\n").?;
    try std.testing.expectError(
        error.Malformed,
        parseWebSocketHeadersWithAllocator(std.testing.allocator, request, first_line_end, header_end),
    );
}

/// SIMD-accelerated search for the HTTP header-end sentinel "\r\n\r\n".
/// Scans 16 bytes at a time looking for '\r' candidates, then scalar-verifies
/// each hit. Roughly 4× faster than std.mem.indexOf for typical 300-2000 byte
/// headers because most 16-byte windows contain no '\r' at all.
inline fn findHeaderEnd(buf: []const u8) ?usize {
    if (buf.len < 4) return null;
    const vec_len = 16;
    const V = @Vector(vec_len, u8);
    const cr_splat: V = @splat(@as(u8, '\r'));

    var i: usize = 0;
    // Require 3 bytes past the end of each chunk so buf[i+k+3] is always valid.
    while (i + vec_len + 3 <= buf.len) {
        const chunk: V = buf[i..][0..vec_len].*;
        if (@reduce(.Or, chunk == cr_splat)) {
            for (0..vec_len) |k| {
                if (buf[i + k] == '\r' and buf[i + k + 1] == '\n' and
                    buf[i + k + 2] == '\r' and buf[i + k + 3] == '\n')
                {
                    return i + k;
                }
            }
        }
        i += vec_len;
    }
    // Scalar tail for the remaining < vec_len+3 bytes.
    while (i + 3 < buf.len) {
        if (buf[i] == '\r' and buf[i + 1] == '\n' and buf[i + 2] == '\r' and buf[i + 3] == '\n')
            return i;
        i += 1;
    }
    return null;
}

fn handleConnection(stream: std.Io.net.Stream, tstate: ?*anyopaque) void {
    var owns_stream = true;
    defer if (owns_stream) stream.close(runtime.io);

    // Slowloris protection: if client sends nothing for 30s, read() times out
    // and the worker is freed. No kqueue needed — just a socket option.
    const timeout = std.posix.timeval{
        .sec = @intCast(http_header_timeout_ms / 1000),
        .usec = @intCast((http_header_timeout_ms % 1000) * 1000),
    };
    std.posix.setsockopt(stream.socket.handle, std.posix.SOL.SOCKET, std.posix.SO.RCVTIMEO, std.mem.asBytes(&timeout)) catch {};

    while (true) {
        handleOneRequest(stream, tstate) catch |err| switch (err) {
            error.ConnectionTransferred => {
                owns_stream = false;
                return;
            },
            else => return,
        };
    }
}

// ── WebSocket runtime ──────────────────────────────────────────────────────
//
// Connection model: the HTTP worker validates the RFC 6455 upgrade, copies the
// bounded request metadata, writes 101, and transfers socket ownership to the
// dedicated WebSocket pool. Ordinary HTTP capacity is therefore independent
// of long-lived socket count.

const ECHO_PATH = "/ws-echo";

const WebSocketJob = struct {
    stream: std.Io.net.Stream,
    path: []u8,
    query_string: []u8,
    headers: []HeaderPair,
    route_snapshot: ?WebSocketRouteEntry,

    fn init(
        stream: std.Io.net.Stream,
        path: []const u8,
        query_string: []const u8,
        headers: []const HeaderPair,
        route_snapshot: ?WebSocketRouteEntry,
    ) !WebSocketJob {
        return initWithAllocator(allocator, stream, path, query_string, headers, route_snapshot);
    }

    fn initWithAllocator(
        job_allocator: std.mem.Allocator,
        stream: std.Io.net.Stream,
        path: []const u8,
        query_string: []const u8,
        headers: []const HeaderPair,
        route_snapshot: ?WebSocketRouteEntry,
    ) !WebSocketJob {
        const owned_path = try job_allocator.dupe(u8, path);
        errdefer job_allocator.free(owned_path);
        const owned_query = try job_allocator.dupe(u8, query_string);
        errdefer job_allocator.free(owned_query);
        const owned_headers = try job_allocator.alloc(HeaderPair, headers.len);
        var initialized: usize = 0;
        errdefer {
            for (owned_headers[0..initialized]) |header| {
                job_allocator.free(header.name);
                job_allocator.free(header.value);
            }
            job_allocator.free(owned_headers);
        }
        for (headers, 0..) |header, i| {
            const name = try job_allocator.dupe(u8, header.name);
            errdefer job_allocator.free(name);
            const value = try job_allocator.dupe(u8, header.value);
            owned_headers[i] = .{ .name = name, .value = value };
            initialized += 1;
        }
        return .{
            .stream = stream,
            .path = owned_path,
            .query_string = owned_query,
            .headers = owned_headers,
            .route_snapshot = route_snapshot,
        };
    }

    fn deinitMetadata(self: *WebSocketJob) void {
        self.deinitMetadataWithAllocator(allocator);
    }

    fn deinitMetadataWithAllocator(self: *WebSocketJob, job_allocator: std.mem.Allocator) void {
        job_allocator.free(self.path);
        job_allocator.free(self.query_string);
        for (self.headers) |header| {
            job_allocator.free(header.name);
            job_allocator.free(header.value);
        }
        job_allocator.free(self.headers);
    }

    fn run(self: *WebSocketJob, tstate: ?*anyopaque) void {
        runWebSocketConnection(self.stream, self.path, self.query_string, self.headers, self.route_snapshot, tstate) catch |err| {
            logger.warn("[WS] connection ended with error: {}", .{err});
        };
    }

    fn deinit(self: *WebSocketJob, tstate: ?*anyopaque) void {
        self.stream.close(runtime.io);
        self.deinitMetadata();
        if (self.route_snapshot) |route| releaseWebSocketRoute(route, tstate);
        releaseWebSocketSlot();
    }
};

fn allocateTestWebSocketJob(job_allocator: std.mem.Allocator) !void {
    const headers = [_]HeaderPair{
        .{ .name = "authorization", .value = "Bearer allocation-test" },
        .{ .name = "origin", .value = "https://example.test" },
    };
    var job = try WebSocketJob.initWithAllocator(
        job_allocator,
        undefined,
        "/ws",
        "tenant=alpha",
        &headers,
        null,
    );
    job.deinitMetadataWithAllocator(job_allocator);
}

test "WebSocket queued metadata cleans every allocation failure" {
    try std.testing.checkAllAllocationFailures(
        std.testing.allocator,
        allocateTestWebSocketJob,
        .{},
    );
}

const PendingWsFrame = struct {
    bytes: []u8,
    offset: usize,
    budget_bytes: usize,
};

/// Per-connection state for a live WebSocket. Allocated on the stack of
/// `runWebSocketConnection`; Python receives only a short-lived opaque capsule
/// whose name is invalidated before this stack frame ends.
pub const WsConn = struct {
    stream: std.Io.net.Stream,
    /// Read buffer for incoming frames. Sized for typical messages; large
    /// payloads spill to the heap-backed `read_overflow`.
    read_buf: [16 * 1024]u8 = undefined,
    read_len: usize = 0,
    /// Heap buffer used when a single frame's payload exceeds the inline
    /// buffer. Freed at conn teardown.
    read_overflow: ?[]u8 = null,
    /// Reassembly buffer for fragmented messages. Allocated on first
    /// continuation, freed when message completes or connection closes.
    fragment_buf: std.ArrayListUnmanaged(u8) = .empty,
    fragment_opcode: ws.Opcode = .continuation,
    fragment_active: bool = false,
    /// True once either side begins closing. Atomic because a retained
    /// WebSocket object can be used from another free-threaded Python thread.
    closing: std.atomic.Value(bool) = .init(false),
    /// Serialize close-handshake initiation. `closing` gives senders a cheap
    /// atomic fast-fail, while this lock ensures an idempotent second close
    /// cannot observe `closing=true` before the first close frame is ordered.
    close_mutex: std.Io.Mutex = .init,
    /// RFC 6455 frames must never interleave on the wire. This covers data
    /// sends, ping/pong replies, and close frames across all calling threads.
    write_mutex: std.Io.Mutex = .init,
    /// Nonblocking Python handlers retain partially-written frames here. The
    /// fixed ring bounds metadata, while queue bytes are capped independently.
    pending_frames: [MAX_WS_QUEUE_MESSAGES]PendingWsFrame = undefined,
    pending_head: usize = 0,
    pending_tail: usize = 0,
    pending_count: usize = 0,
    pending_bytes: usize = 0,
    frame_allocator: std.mem.Allocator = allocator,
    nonblocking: bool = false,
    peer_close_code: u16 = 1006,
    peer_close_reason: [123]u8 = undefined,
    peer_close_reason_len: usize = 0,
    local_close_code: u16 = 1002,
    local_close_reason: [123]u8 = undefined,
    local_close_reason_len: usize = 0,

    pub const MAX_MESSAGE: usize = 16 * 1024 * 1024;
    const MAX_WIRE_FRAME: usize = MAX_MESSAGE + 14; // 10-byte length + 4-byte mask

    fn deinit(self: *WsConn) void {
        if (self.read_overflow) |o| allocator.free(o);
        self.fragment_buf.deinit(allocator);
        self.discardPendingFrames();
    }

    fn readStorage(self: *WsConn) []u8 {
        return self.read_overflow orelse self.read_buf[0..];
    }

    /// Ensure a socket read can make progress. The parser needs a complete
    /// frame because it unmasks in place, so grow past the inline 16 KiB for
    /// larger frames, bounded by the declared message limit plus wire header.
    fn ensureReadSpace(self: *WsConn) bool {
        const storage = self.readStorage();
        if (self.read_len < storage.len) return true;
        if (storage.len >= MAX_WIRE_FRAME) return false;
        const next_len = @min(MAX_WIRE_FRAME, @max(storage.len * 2, self.read_len + 16 * 1024));
        const next = allocator.alloc(u8, next_len) catch return false;
        @memcpy(next[0..self.read_len], storage[0..self.read_len]);
        if (self.read_overflow) |old| allocator.free(old);
        self.read_overflow = next;
        return true;
    }

    const FillResult = enum { progress, would_block, closed, failed };

    /// Read more bytes into the active buffer, appending.
    fn fillRead(self: *WsConn) FillResult {
        if (!self.ensureReadSpace()) return .failed;
        const storage = self.readStorage();
        const n = posix.read(self.stream.socket.handle, storage[self.read_len..]) catch return .failed;
        if (n == 0) return .closed;
        self.read_len += n;
        return .progress;
    }

    fn fillReadNonblocking(self: *WsConn) FillResult {
        if (!self.ensureReadSpace()) return .failed;
        const storage = self.readStorage();
        const amount = posix.read(self.stream.socket.handle, storage[self.read_len..]) catch |err| switch (err) {
            error.WouldBlock => return .would_block,
            else => return .failed,
        };
        if (amount == 0) return .closed;
        self.read_len += amount;
        return .progress;
    }

    fn consumeRead(self: *WsConn, n: usize) void {
        if (n >= self.read_len) {
            self.read_len = 0;
            return;
        }
        const storage = self.readStorage();
        std.mem.copyForwards(u8, storage[0..], storage[n..self.read_len]);
        self.read_len -= n;
    }

    fn setNonblocking(self: *WsConn) !void {
        const result = posix.system.fcntl(self.stream.socket.handle, posix.F.GETFL, @as(usize, 0));
        if (posix.errno(result) != .SUCCESS) return error.SocketFlags;
        const flags: usize = @intCast(result);
        const nonblocking = flags | (@as(usize, 1) << @bitOffsetOf(posix.O, "NONBLOCK"));
        if (posix.errno(posix.system.fcntl(self.stream.socket.handle, posix.F.SETFL, nonblocking)) != .SUCCESS)
            return error.SocketFlags;
        self.nonblocking = true;
    }

    fn writeSome(self: *WsConn, bytes: []const u8) !usize {
        while (true) {
            const written = write(self.stream.socket.handle, bytes.ptr, bytes.len);
            if (written > 0) return @intCast(written);
            if (written == 0) return error.BrokenPipe;
            switch (posix.errno(written)) {
                .INTR => continue,
                .AGAIN => return error.WouldBlock,
                else => return error.BrokenPipe,
            }
        }
    }

    fn discardPendingFrames(self: *WsConn) void {
        while (self.pending_count > 0) {
            const frame = self.pending_frames[self.pending_head];
            self.frame_allocator.free(frame.bytes);
            self.pending_head = (self.pending_head + 1) % MAX_WS_QUEUE_MESSAGES;
            self.pending_count -= 1;
        }
        self.pending_tail = self.pending_head;
        self.pending_bytes = 0;
    }

    fn hasPendingFrames(self: *WsConn) bool {
        self.write_mutex.lockUncancelable(runtime.io);
        defer self.write_mutex.unlock(runtime.io);
        return self.pending_count > 0;
    }

    fn queueOwnedFrame(self: *WsConn, bytes: []u8, offset: usize, budget_bytes: usize) !void {
        errdefer self.frame_allocator.free(bytes);
        if (self.pending_count >= ws_queue_message_limit or
            budget_bytes > ws_queue_byte_limit or
            self.pending_bytes > ws_queue_byte_limit - budget_bytes)
            return error.Backpressure;
        self.pending_frames[self.pending_tail] = .{
            .bytes = bytes,
            .offset = offset,
            .budget_bytes = budget_bytes,
        };
        self.pending_tail = (self.pending_tail + 1) % MAX_WS_QUEUE_MESSAGES;
        self.pending_count += 1;
        self.pending_bytes += budget_bytes;
    }

    fn encodeOwnedFrame(self: *WsConn, fin: bool, opcode: ws.Opcode, payload: []const u8) ![]u8 {
        const header_len: usize = if (payload.len <= 125) 2 else if (payload.len <= 0xFFFF) 4 else 10;
        const bytes = self.frame_allocator.alloc(u8, payload.len + header_len) catch return error.OutOfMemory;
        errdefer self.frame_allocator.free(bytes);
        _ = try ws.writeServerFrame(bytes, fin, opcode, payload);
        return bytes;
    }

    /// Attempt a nonblocking ordered write. Returns true when bytes remain in
    /// the bounded native queue and the event loop must watch for writability.
    fn writeFrameNonblocking(self: *WsConn, opcode: ws.Opcode, payload: []const u8) !bool {
        // The configured byte budget covers application payloads. RFC control
        // frames are independently capped at 125 bytes and still consume a
        // message slot, so a very small data budget cannot disable close/pong.
        const budget_bytes = if (opcode.isControl()) 0 else payload.len;
        if (budget_bytes > ws_queue_byte_limit) return error.Backpressure;
        self.write_mutex.lockUncancelable(runtime.io);
        defer self.write_mutex.unlock(runtime.io);
        // Once a close handshake starts, nothing may be ordered after the
        // close frame. The close opcode itself is allowed because callers set
        // `closing` atomically before they acquire the write lock.
        if (opcode != .close and self.closing.load(.acquire))
            return error.ConnectionClosed;

        if (self.pending_count > 0) {
            const owned = try self.encodeOwnedFrame(true, opcode, payload);
            try self.queueOwnedFrame(owned, 0, budget_bytes);
            return true;
        }

        if (payload.len <= 8192) {
            var stack: [8192 + 10]u8 = undefined;
            const used = try ws.writeServerFrame(&stack, true, opcode, payload);
            const sent = self.writeSome(stack[0..used]) catch |err| switch (err) {
                error.WouldBlock => 0,
                else => return err,
            };
            if (sent == used) return false;
            const remaining = self.frame_allocator.dupe(u8, stack[sent..used]) catch return error.OutOfMemory;
            try self.queueOwnedFrame(remaining, 0, budget_bytes);
            return true;
        }

        const owned = try self.encodeOwnedFrame(true, opcode, payload);
        const sent = self.writeSome(owned) catch |err| switch (err) {
            error.WouldBlock => 0,
            else => {
                self.frame_allocator.free(owned);
                return err;
            },
        };
        if (sent == owned.len) {
            self.frame_allocator.free(owned);
            return false;
        }
        try self.queueOwnedFrame(owned, sent, budget_bytes);
        return true;
    }

    /// Flush queued bytes without blocking. Returns true once the queue is empty.
    fn flushPendingFrames(self: *WsConn) !bool {
        self.write_mutex.lockUncancelable(runtime.io);
        defer self.write_mutex.unlock(runtime.io);
        while (self.pending_count > 0) {
            var frame = &self.pending_frames[self.pending_head];
            const sent = self.writeSome(frame.bytes[frame.offset..]) catch |err| switch (err) {
                error.WouldBlock => return false,
                else => return err,
            };
            frame.offset += sent;
            if (frame.offset < frame.bytes.len) return false;
            self.pending_bytes -= frame.budget_bytes;
            self.frame_allocator.free(frame.bytes);
            self.pending_head = (self.pending_head + 1) % MAX_WS_QUEUE_MESSAGES;
            self.pending_count -= 1;
        }
        return true;
    }

    fn sendCloseNonblocking(self: *WsConn, code: u16, reason: []const u8, drop_pending: bool) !bool {
        self.close_mutex.lockUncancelable(runtime.io);
        defer self.close_mutex.unlock(runtime.io);
        if (self.closing.swap(true, .acq_rel)) return self.hasPendingFrames();
        self.recordLocalClose(code, reason);
        if (drop_pending) {
            self.write_mutex.lockUncancelable(runtime.io);
            self.discardPendingFrames();
            self.write_mutex.unlock(runtime.io);
        }
        var payload: [125]u8 = undefined;
        std.mem.writeInt(u16, payload[0..2], code, .big);
        @memcpy(payload[2 .. 2 + reason.len], reason);
        return self.writeFrameNonblocking(.close, payload[0 .. 2 + reason.len]);
    }

    fn sendEmptyCloseNonblocking(self: *WsConn, drop_pending: bool) !bool {
        self.close_mutex.lockUncancelable(runtime.io);
        defer self.close_mutex.unlock(runtime.io);
        if (self.closing.swap(true, .acq_rel)) return self.hasPendingFrames();
        if (drop_pending) {
            self.write_mutex.lockUncancelable(runtime.io);
            self.discardPendingFrames();
            self.write_mutex.unlock(runtime.io);
        }
        return self.writeFrameNonblocking(.close, "");
    }

    fn writeFrameLocked(self: *WsConn, fin: bool, opcode: ws.Opcode, payload: []const u8) !void {
        // Common case: small payload, stack buffer.
        if (payload.len <= 8192) {
            var buf: [8192 + 10]u8 = undefined;
            const n = try ws.writeServerFrame(&buf, fin, opcode, payload);
            try streamWriteAll(self.stream, buf[0..n]);
            return;
        }
        // Large payload: allocate exact size.
        const total = payload.len + 10;
        const buf = allocator.alloc(u8, total) catch return error.OutOfMemory;
        defer allocator.free(buf);
        const n = try ws.writeServerFrame(buf, fin, opcode, payload);
        try streamWriteAll(self.stream, buf[0..n]);
    }

    /// Write a complete server-to-client frame to the socket. The mutex keeps
    /// application data and reader-generated control frames from interleaving.
    pub fn writeFrame(self: *WsConn, fin: bool, opcode: ws.Opcode, payload: []const u8) !void {
        self.write_mutex.lockUncancelable(runtime.io);
        defer self.write_mutex.unlock(runtime.io);
        try self.writeFrameLocked(fin, opcode, payload);
    }

    /// Send a close frame with the given code and reason. Marks closing=true.
    /// Caller should typically return shortly after.
    pub fn sendClose(self: *WsConn, code: u16, reason: []const u8) void {
        self.close_mutex.lockUncancelable(runtime.io);
        defer self.close_mutex.unlock(runtime.io);
        if (self.closing.swap(true, .acq_rel)) return;
        self.recordLocalClose(code, reason);
        var payload_buf: [128]u8 = undefined;
        const reason_clamped = if (reason.len > 123) reason[0..123] else reason;
        const payload_len = ws.writeClosePayload(&payload_buf, code, reason_clamped) catch return;
        self.writeFrame(true, .close, payload_buf[0..payload_len]) catch return;
    }

    fn recordLocalClose(self: *WsConn, code: u16, reason: []const u8) void {
        self.local_close_code = code;
        self.local_close_reason_len = @min(reason.len, self.local_close_reason.len);
        @memcpy(self.local_close_reason[0..self.local_close_reason_len], reason[0..self.local_close_reason_len]);
    }

    pub fn sendEmptyClose(self: *WsConn) void {
        self.close_mutex.lockUncancelable(runtime.io);
        defer self.close_mutex.unlock(runtime.io);
        if (self.closing.swap(true, .acq_rel)) return;
        self.writeFrame(true, .close, "") catch return;
    }

    /// Overload teardown must never wait behind a slow socket writer. Send a
    /// close frame only when the write mutex is immediately available, then
    /// shut down both directions so any blocking reader or writer exits.
    pub fn abort(self: *WsConn, code: u16, reason: []const u8) void {
        _ = self.closing.swap(true, .acq_rel);
        if (self.write_mutex.tryLock()) {
            self.discardPendingFrames();
            var payload_buf: [128]u8 = undefined;
            const reason_clamped = if (reason.len > 123) reason[0..123] else reason;
            const payload_len = ws.writeClosePayload(&payload_buf, code, reason_clamped) catch 0;
            var frame_buf: [140]u8 = undefined;
            const frame_len = ws.writeServerFrame(&frame_buf, true, .close, payload_buf[0..payload_len]) catch 0;
            const get_flags = posix.system.fcntl(self.stream.socket.handle, posix.F.GETFL, @as(usize, 0));
            if (posix.errno(get_flags) == .SUCCESS) {
                const flags: usize = @intCast(get_flags);
                const nonblocking = flags | (@as(usize, 1) << @bitOffsetOf(posix.O, "NONBLOCK"));
                if (posix.errno(posix.system.fcntl(self.stream.socket.handle, posix.F.SETFL, nonblocking)) == .SUCCESS) {
                    // One best-effort nonblocking write. The subsequent
                    // shutdown is authoritative if the close frame cannot fit.
                    _ = write(self.stream.socket.handle, frame_buf[0..frame_len].ptr, frame_len);
                }
            }
            self.write_mutex.unlock(runtime.io);
        }
        self.stream.shutdown(runtime.io, .both) catch {};
    }

    pub fn shutdown(self: *WsConn) void {
        self.closing.store(true, .release);
        self.stream.shutdown(runtime.io, .both) catch {};
    }
};

fn allocateTestOutboundFrame(frame_allocator: std.mem.Allocator) !void {
    var conn = WsConn{
        .stream = undefined,
        .frame_allocator = frame_allocator,
    };
    const frame = try conn.encodeOwnedFrame(true, .text, "allocation-test");
    frame_allocator.free(frame);
}

test "WebSocket outbound frame handles allocation failure without leaks" {
    try std.testing.checkAllAllocationFailures(
        std.testing.allocator,
        allocateTestOutboundFrame,
        .{},
    );
}

test "WebSocket backpressure frees rejected frame ownership" {
    var conn = WsConn{
        .stream = undefined,
        .frame_allocator = std.testing.allocator,
        .pending_count = MAX_WS_QUEUE_MESSAGES,
    };
    const owned = try std.testing.allocator.dupe(u8, "rejected-frame");
    try std.testing.expectError(
        error.Backpressure,
        conn.queueOwnedFrame(owned, 0, owned.len),
    );
}

/// Result of WS upgrade attempt.
const WsUpgradeOutcome = enum {
    /// Not a WebSocket request — caller should continue normal HTTP dispatch.
    not_websocket,
    /// Was a WS request and we handled it (whether successfully or with an
    /// error response). Caller should NOT continue normal dispatch.
    handled,
    /// The dedicated WebSocket pool now owns the stream.
    transferred,
};

const HttpRequestLine = struct {
    method: []const u8,
    request_target: []const u8,
    version: []const u8,
};

fn isValidRequestLineField(field: []const u8) bool {
    if (field.len == 0) return false;
    for (field) |byte| {
        if (byte <= ' ' or byte == 0x7f) return false;
    }
    return true;
}

/// Parse the complete HTTP request line as METHOD SP TARGET SP VERSION.
/// RFC request-line separators are single SP bytes; accepting a prefix and
/// ignoring trailing tokens could otherwise let malformed requests reach the
/// WebSocket policy/101 path.
fn parseHttpRequestLine(line: []const u8) error{InvalidRequestLine}!HttpRequestLine {
    const first_space = std.mem.indexOfScalar(u8, line, ' ') orelse return error.InvalidRequestLine;
    if (first_space == 0) return error.InvalidRequestLine;
    const second_space = std.mem.indexOfPosLinear(u8, line, first_space + 1, " ") orelse return error.InvalidRequestLine;
    if (second_space == first_space + 1) return error.InvalidRequestLine;
    if (std.mem.indexOfPosLinear(u8, line, second_space + 1, " ") != null) return error.InvalidRequestLine;

    const parsed = HttpRequestLine{
        .method = line[0..first_space],
        .request_target = line[first_space + 1 .. second_space],
        .version = line[second_space + 1 ..],
    };
    if (!isValidRequestLineField(parsed.method) or
        !isValidRequestLineField(parsed.request_target) or
        !isValidRequestLineField(parsed.version)) return error.InvalidRequestLine;
    return parsed;
}

test "HTTP request line parsing consumes exactly three fields" {
    const parsed = try parseHttpRequestLine("GET /chat?tenant=alpha HTTP/1.1");
    try std.testing.expectEqualStrings("GET", parsed.method);
    try std.testing.expectEqualStrings("/chat?tenant=alpha", parsed.request_target);
    try std.testing.expectEqualStrings("HTTP/1.1", parsed.version);

    const malformed = [_][]const u8{
        "GET /chat",
        "GET  /chat HTTP/1.1",
        "GET /chat  HTTP/1.1",
        "GET /chat HTTP/1.1 extra",
        "GET\t/chat HTTP/1.1",
        "GET /chat\tHTTP/1.1",
    };
    for (malformed) |line| {
        try std.testing.expectError(error.InvalidRequestLine, parseHttpRequestLine(line));
    }
}

/// Case-insensitive header lookup.
fn findHeader(headers: []const HeaderPair, name: []const u8) ?[]const u8 {
    for (headers) |h| {
        if (std.ascii.eqlIgnoreCase(h.name, name)) return h.value;
    }
    return null;
}

fn hasWebSocketUpgradeHeader(
    request_head: []const u8,
    first_line_end: usize,
    header_end_pos: usize,
) bool {
    var pos = first_line_end + 2;
    while (pos < header_end_pos) {
        const line_end = std.mem.indexOfPos(u8, request_head, pos, "\r\n") orelse header_end_pos;
        const line = request_head[pos..line_end];
        pos = line_end + 2;
        const colon = std.mem.indexOfScalar(u8, line, ':') orelse continue;
        const name = std.mem.trim(u8, line[0..colon], " \t");
        if (!std.ascii.eqlIgnoreCase(name, "upgrade")) continue;
        const value = std.mem.trim(u8, line[colon + 1 ..], " \t");
        if (std.ascii.eqlIgnoreCase(value, "websocket")) return true;
    }
    return false;
}

/// Security-sensitive WebSocket headers must be unambiguous. Reject repeated
/// values rather than inheriting first-value/last-value behavior that can differ
/// between the edge, the native core, and an application guard.
fn hasDuplicateWebSocketSecurityHeader(headers: []const HeaderPair) bool {
    var host_seen = false;
    var authorization_seen = false;
    var origin_seen = false;
    var key_seen = false;
    var version_seen = false;

    for (headers) |header| {
        const seen = if (std.ascii.eqlIgnoreCase(header.name, "host"))
            &host_seen
        else if (std.ascii.eqlIgnoreCase(header.name, "authorization"))
            &authorization_seen
        else if (std.ascii.eqlIgnoreCase(header.name, "origin"))
            &origin_seen
        else if (std.ascii.eqlIgnoreCase(header.name, "sec-websocket-key"))
            &key_seen
        else if (std.ascii.eqlIgnoreCase(header.name, "sec-websocket-version"))
            &version_seen
        else
            continue;
        if (seen.*) return true;
        seen.* = true;
    }
    return false;
}

test "WebSocket security header duplicates are case-insensitive" {
    const unique = [_]HeaderPair{
        .{ .name = "Host", .value = "example.test" },
        .{ .name = "Authorization", .value = "Bearer one" },
        .{ .name = "Origin", .value = "https://example.test" },
        .{ .name = "Sec-WebSocket-Key", .value = "key" },
        .{ .name = "Sec-WebSocket-Version", .value = "13" },
    };
    try std.testing.expect(!hasDuplicateWebSocketSecurityHeader(&unique));

    const duplicate = [_]HeaderPair{
        .{ .name = "authorization", .value = "Bearer one" },
        .{ .name = "AUTHORIZATION", .value = "Bearer two" },
    };
    try std.testing.expect(hasDuplicateWebSocketSecurityHeader(&duplicate));

    const duplicate_host = [_]HeaderPair{
        .{ .name = "Host", .value = "first.example" },
        .{ .name = "hOsT", .value = "second.example" },
    };
    try std.testing.expect(hasDuplicateWebSocketSecurityHeader(&duplicate_host));
}

/// RFC 6455 section 4.2.1 requires a standard Base64 value that decodes to
/// exactly 16 bytes. Re-encoding also rejects non-canonical padding/bits, so
/// the value hashed into Sec-WebSocket-Accept has one unambiguous encoding.
fn isValidWebSocketKey(key: []const u8) bool {
    if (key.len != std.base64.standard.Encoder.calcSize(16)) return false;
    const decoded_len = std.base64.standard.Decoder.calcSizeForSlice(key) catch return false;
    if (decoded_len != 16) return false;

    var decoded: [16]u8 = undefined;
    std.base64.standard.Decoder.decode(&decoded, key) catch return false;

    var canonical: [24]u8 = undefined;
    const encoded = std.base64.standard.Encoder.encode(&canonical, &decoded);
    return std.mem.eql(u8, key, encoded);
}

test "WebSocket key is canonical Base64 for exactly 16 decoded bytes" {
    try std.testing.expect(isValidWebSocketKey("dGhlIHNhbXBsZSBub25jZQ=="));
    try std.testing.expect(isValidWebSocketKey("eHh4eHh4eHh4eHh4eHh4eA=="));
    try std.testing.expect(!isValidWebSocketKey("not%%%base64%%%%%%%%%%%"));
    try std.testing.expect(!isValidWebSocketKey("eHh4eHh4eHh4eHh4eHh4"));
    try std.testing.expect(!isValidWebSocketKey("eHh4eHh4eHh4eHh4eHh4eHg="));
    try std.testing.expect(!isValidWebSocketKey("dGhlIHNhbXBsZSBub25jZR=="));
}

/// Case-insensitive substring search in a comma-separated header value.
/// e.g. value = "keep-alive, Upgrade" + needle = "upgrade" → true.
fn headerContainsToken(value: []const u8, token: []const u8) bool {
    var it = std.mem.tokenizeAny(u8, value, ", \t");
    while (it.next()) |tok| {
        if (std.ascii.eqlIgnoreCase(tok, token)) return true;
    }
    return false;
}

/// Allocation-free, case-insensitive header-name probe for the HTTP fast
/// path. A byte substring search would miss mixed-case spellings such as
/// `uPgRaDe` even though HTTP field names are case-insensitive.
fn requestHasHeader(
    request_data: []const u8,
    first_line_end: usize,
    header_end_pos: usize,
    name: []const u8,
) bool {
    var pos = first_line_end + 2;
    while (pos < header_end_pos) {
        const line_end = std.mem.indexOfPos(u8, request_data, pos, "\r\n") orelse header_end_pos;
        const line = request_data[pos..line_end];
        pos = line_end + 2;
        const colon = std.mem.indexOfScalar(u8, line, ':') orelse continue;
        const candidate = std.mem.trim(u8, line[0..colon], " \t");
        if (std.ascii.eqlIgnoreCase(candidate, name)) return true;
    }
    return false;
}

test "WebSocket upgrade hint accepts mixed-case HTTP field names" {
    const request = "GET /ws HTTP/1.1\r\nuPgRaDe: websocket\r\nHost: example.test\r\n\r\n";
    const first_line_end = std.mem.indexOf(u8, request, "\r\n").?;
    const header_end = std.mem.indexOf(u8, request, "\r\n\r\n").?;
    try std.testing.expect(requestHasHeader(request, first_line_end, header_end, "upgrade"));
    try std.testing.expect(!requestHasHeader(request, first_line_end, header_end, "authorization"));
}

/// Send a minimal HTTP error response on the WebSocket-upgrade path. Used for
/// malformed upgrade requests (missing key, bad version, etc.).
fn sendUpgradeError(stream: std.Io.net.Stream, status_code: u16, reason: []const u8) void {
    var buf: [256]u8 = undefined;
    const formatted = std.fmt.bufPrint(&buf, "HTTP/1.1 {d} {s}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n", .{ status_code, reason }) catch return;
    streamWriteAll(stream, formatted) catch {};
}

/// If this looks like a WebSocket upgrade request and the path is registered,
/// complete the handshake and run the connection. Returns whether we handled
/// the request (caller should stop normal HTTP dispatch).
fn tryWebSocketUpgrade(
    stream: std.Io.net.Stream,
    request_head: []const u8,
    first_line_end: usize,
    header_end_pos: usize,
    method: []const u8,
    path: []const u8,
    query_string: []const u8,
    tstate: ?*anyopaque,
) WsUpgradeOutcome {
    if (!std.mem.eql(u8, method, "GET")) return .not_websocket;

    // Avoid allocating a parsed header list for normal GET requests.
    if (!requestHasHeader(request_head, first_line_end, header_end_pos, "upgrade"))
        return .not_websocket;

    var headers = parseWebSocketHeaders(request_head, first_line_end, header_end_pos) catch |err| {
        switch (err) {
            error.Malformed => sendUpgradeError(stream, 400, "Bad Request"),
            error.OutOfMemory => sendUpgradeError(stream, 500, "Internal Server Error"),
        }
        return .handled;
    };
    defer headers.deinit(allocator);

    const upgrade_h = findHeader(headers.items, "upgrade") orelse return .not_websocket;
    if (!std.ascii.eqlIgnoreCase(std.mem.trim(u8, upgrade_h, " \t"), "websocket")) return .not_websocket;

    // Past this point we're confident it's a WS upgrade attempt. Any further
    // failures send 400/426 and consume the connection.

    if (hasDuplicateWebSocketSecurityHeader(headers.items)) {
        sendUpgradeError(stream, 400, "Bad Request");
        return .handled;
    }

    const host_h = findHeader(headers.items, "host") orelse {
        sendUpgradeError(stream, 400, "Bad Request");
        return .handled;
    };
    if (std.mem.trim(u8, host_h, " \t").len == 0) {
        sendUpgradeError(stream, 400, "Bad Request");
        return .handled;
    }

    const conn_h = findHeader(headers.items, "connection") orelse {
        sendUpgradeError(stream, 400, "Bad Request");
        return .handled;
    };
    if (!headerContainsToken(conn_h, "upgrade")) {
        sendUpgradeError(stream, 400, "Bad Request");
        return .handled;
    }

    const version_h = findHeader(headers.items, "sec-websocket-version") orelse {
        sendUpgradeError(stream, 400, "Bad Request");
        return .handled;
    };
    if (!std.mem.eql(u8, std.mem.trim(u8, version_h, " \t"), "13")) {
        // RFC §4.4: must respond with 426 and Sec-WebSocket-Version: 13.
        var buf: [128]u8 = undefined;
        const resp = std.fmt.bufPrint(&buf, "HTTP/1.1 426 Upgrade Required\r\nSec-WebSocket-Version: 13\r\nContent-Length: 0\r\nConnection: close\r\n\r\n", .{}) catch return .handled;
        streamWriteAll(stream, resp) catch {};
        return .handled;
    }

    const key_h = findHeader(headers.items, "sec-websocket-key") orelse {
        sendUpgradeError(stream, 400, "Bad Request");
        return .handled;
    };
    const key = std.mem.trim(u8, key_h, " \t");
    if (!isValidWebSocketKey(key)) {
        sendUpgradeError(stream, 400, "Bad Request");
        return .handled;
    }

    // Route lookup and any application policy must run after the RFC 6455
    // request has been validated, but before capacity admission and the 101.
    // This keeps rejected sockets out of the active-WebSocket budget.
    var route_snapshot: ?WebSocketRouteEntry = null;
    defer {
        if (route_snapshot) |route| releaseWebSocketRoute(route, tstate);
    }
    if (!std.mem.eql(u8, path, ECHO_PATH)) {
        route_snapshot = retainWebSocketRoute(path, tstate) catch {
            sendUpgradeError(stream, 500, "Internal Server Error");
            return .handled;
        };
        const route = route_snapshot orelse {
            sendUpgradeError(stream, 404, "Not Found");
            return .handled;
        };
        if (route.guard) |guard| {
            const rejection = runWebSocketUpgradeGuard(guard, path, query_string, headers.items, tstate);
            if (rejection != 0) {
                sendWebSocketGuardRejection(stream, rejection);
                return .handled;
            }
        }
    }

    // Admission and all metadata allocation happen before the 101 response.
    // Once 101 is visible the dedicated pool must be able to own the stream.
    if (!tryAcquireWebSocketSlot()) {
        sendUpgradeError(stream, 503, "Service Unavailable");
        return .handled;
    }
    var slot_transferred = false;
    defer if (!slot_transferred) releaseWebSocketSlot();

    var job = WebSocketJob.init(stream, path, query_string, headers.items, route_snapshot) catch {
        sendUpgradeError(stream, 503, "Service Unavailable");
        return .handled;
    };
    var job_transferred = false;
    defer if (!job_transferred) job.deinitMetadata();

    // Handshake.
    var accept_buf: [ws.ACCEPT_LEN]u8 = undefined;
    _ = ws.computeAcceptKey(key, &accept_buf) catch {
        sendUpgradeError(stream, 500, "Internal Server Error");
        return .handled;
    };
    var resp_buf: [256]u8 = undefined;
    const resp_len = ws.writeHandshakeResponse(&resp_buf, &accept_buf) catch {
        sendUpgradeError(stream, 500, "Internal Server Error");
        return .handled;
    };
    streamWriteAll(stream, resp_buf[0..resp_len]) catch return .handled;

    // The 30-second receive timeout protects only the HTTP header phase. A
    // valid WebSocket may remain idle indefinitely, so clear it before the
    // dedicated pool takes ownership.
    const no_timeout = std.posix.timeval{ .sec = 0, .usec = 0 };
    std.posix.setsockopt(stream.socket.handle, std.posix.SOL.SOCKET, std.posix.SO.RCVTIMEO, std.mem.asBytes(&no_timeout)) catch {};
    const write_timeout = std.posix.timeval{
        .sec = @intCast(ws_write_timeout_ms / 1000),
        .usec = @intCast((ws_write_timeout_ms % 1000) * 1000),
    };
    std.posix.setsockopt(stream.socket.handle, std.posix.SOL.SOCKET, std.posix.SO.SNDTIMEO, std.mem.asBytes(&write_timeout)) catch {};

    if (!ws_pool_gate.isReady() or !ws_pool.queue.push(job)) {
        // Readiness is permanent once published and admission bounds queue
        // occupancy below capacity, so this is only a defensive fail-closed
        // path. The HTTP worker still owns and closes the upgraded socket.
        return .handled;
    }
    // The queued job now owns the retained Python route references. They stay
    // alive across route replacement until this connection's worker exits.
    route_snapshot = null;
    job_transferred = true;
    slot_transferred = true;
    return .transferred;
}

const WebSocketRouteEntry = struct {
    handler: *c.PyObject,
    guard: ?*c.PyObject = null,
};

var ws_routes_map: ?std.StringHashMap(WebSocketRouteEntry) = null;
var ws_routes_lock: std.atomic.Mutex = .unlocked;

fn lockWebSocketRoutes() void {
    while (!ws_routes_lock.tryLock()) std.atomic.spinLoopHint();
}

fn unlockWebSocketRoutes() void {
    ws_routes_lock.unlock();
}

/// The caller must hold ws_routes_lock.
fn getWebSocketRoutes() *std.StringHashMap(WebSocketRouteEntry) {
    if (ws_routes_map == null) {
        ws_routes_map = std.StringHashMap(WebSocketRouteEntry).init(allocator);
    }
    return &ws_routes_map.?;
}

/// Take an owned route snapshot while both the Python thread state and route
/// lock are held. The lock is released before any guard/handler callback.
fn retainWebSocketRoute(path: []const u8, tstate: ?*anyopaque) error{PythonThreadUnavailable}!?WebSocketRouteEntry {
    const thread_state = tstate orelse return error.PythonThreadUnavailable;
    py.PyEval_AcquireThread(thread_state);
    defer py.PyEval_ReleaseThread(thread_state);

    lockWebSocketRoutes();
    defer unlockWebSocketRoutes();
    const route = getWebSocketRoutes().get(path) orelse return null;
    c.Py_IncRef(route.handler);
    if (route.guard) |guard| c.Py_IncRef(guard);
    return route;
}

/// Release a snapshot outside the route lock with an attached Python thread
/// state so finalizers cannot run while native route-map state is locked.
fn releaseWebSocketRoute(route: WebSocketRouteEntry, tstate: ?*anyopaque) void {
    const thread_state = tstate orelse return;
    py.PyEval_AcquireThread(thread_state);
    defer py.PyEval_ReleaseThread(thread_state);
    c.Py_DecRef(route.handler);
    if (route.guard) |guard| c.Py_DecRef(guard);
}

/// Drive a live WebSocket connection. Reads frames, dispatches by opcode,
/// auto-replies to ping with pong, echoes text/binary for /ws-echo, and
/// completes the close handshake when requested.
///
/// Outcome of reading the next user-visible WS message. Control frames
/// (ping/pong/close) are handled internally and never surface as a Message.
const NextMessage = union(enum) {
    text: []const u8, // borrow from conn.read_buf / fragment_buf
    binary: []const u8,
    closed,
    protocol_error,
};

const NextNonblockingMessage = union(enum) {
    text: []const u8,
    binary: []const u8,
    would_block,
    closed,
    protocol_error,
};

const PeerCloseValidation = enum { valid, invalid_code, invalid_utf8 };

fn recordPeerClose(conn: *WsConn, payload: []const u8) PeerCloseValidation {
    if (payload.len == 0) {
        conn.peer_close_code = 1005;
        conn.peer_close_reason_len = 0;
        return .valid;
    }
    if (payload.len == 1) return .invalid_code;
    const code = std.mem.readInt(u16, payload[0..2], .big);
    if (!isValidWebSocketCloseCode(@intCast(code))) return .invalid_code;
    const reason = payload[2..];
    if (!std.unicode.utf8ValidateSlice(reason)) return .invalid_utf8;
    conn.peer_close_code = code;
    conn.peer_close_reason_len = reason.len;
    @memcpy(conn.peer_close_reason[0..reason.len], reason);
    return .valid;
}

fn validateTextMessage(conn: *WsConn, payload: []const u8) bool {
    if (std.unicode.utf8ValidateSlice(payload)) return true;
    conn.sendClose(1007, "invalid utf-8");
    return false;
}

fn canAppendWebSocketFragment(current_len: usize, incoming_len: usize) bool {
    return current_len <= WsConn.MAX_MESSAGE and incoming_len <= WsConn.MAX_MESSAGE - current_len;
}

/// Read frames until we have a complete user message (text or binary), the
/// peer closes, or a protocol error occurs. Pings are auto-replied with
/// pongs; pongs are dropped; close frames trigger close handshake.
///
/// On success the returned slice points into the conn's read_buf (for
/// single-frame messages) or fragment_buf (for reassembled messages). The
/// caller MUST consume the message before the next call (the buffers are
/// reused).
fn wsReadNextMessage(conn: *WsConn) NextMessage {
    while (!conn.closing.load(.acquire)) {
        if (conn.read_len < 2) {
            switch (conn.fillRead()) {
                .progress => continue,
                .closed => return .closed,
                .failed, .would_block => {
                    conn.sendClose(1011, "read failure");
                    return .protocol_error;
                },
            }
        }

        const frame = ws.parseServerFrame(conn.readStorage()[0..conn.read_len], WsConn.MAX_MESSAGE) catch |err| switch (err) {
            ws.ParseError.Incomplete => {
                switch (conn.fillRead()) {
                    .progress => continue,
                    .closed => return .closed,
                    .failed, .would_block => {
                        conn.sendClose(1011, "read failure");
                        return .protocol_error;
                    },
                }
            },
            ws.ParseError.PayloadTooLarge => {
                conn.sendClose(1009, "message too big");
                return .protocol_error;
            },
            else => {
                conn.sendClose(1002, "protocol error");
                return .protocol_error;
            },
        };

        switch (frame.opcode) {
            .ping => {
                conn.writeFrame(true, .pong, frame.payload) catch return .closed;
                conn.consumeRead(frame.consumed);
            },
            .pong => {
                conn.consumeRead(frame.consumed);
            },
            .close => {
                switch (recordPeerClose(conn, frame.payload)) {
                    .valid => {},
                    .invalid_code => {
                        conn.sendClose(1002, "invalid close code");
                        return .protocol_error;
                    },
                    .invalid_utf8 => {
                        conn.sendClose(1007, "invalid utf-8");
                        return .protocol_error;
                    },
                }
                if (conn.peer_close_code == 1005)
                    conn.sendEmptyClose()
                else
                    conn.sendClose(conn.peer_close_code, conn.peer_close_reason[0..conn.peer_close_reason_len]);
                conn.consumeRead(frame.consumed);
                return .closed;
            },
            .text, .binary => {
                if (conn.fragment_active) {
                    conn.sendClose(1002, "fragment sequence error");
                    return .protocol_error;
                }
                if (!frame.fin) {
                    conn.fragment_buf.clearRetainingCapacity();
                    if (!canAppendWebSocketFragment(conn.fragment_buf.items.len, frame.payload.len)) {
                        conn.sendClose(1009, "message too big");
                        return .protocol_error;
                    }
                    conn.fragment_opcode = frame.opcode;
                    conn.fragment_active = true;
                    conn.fragment_buf.appendSlice(allocator, frame.payload) catch {
                        conn.sendClose(1011, "out of memory");
                        return .protocol_error;
                    };
                    conn.consumeRead(frame.consumed);
                } else {
                    const op = frame.opcode;
                    const payload = frame.payload;
                    const consumed = frame.consumed;
                    // We need to return a stable slice. Copy into fragment_buf
                    // so the slice survives the upcoming consumeRead().
                    conn.fragment_buf.clearRetainingCapacity();
                    conn.fragment_buf.appendSlice(allocator, payload) catch {
                        conn.sendClose(1011, "out of memory");
                        return .protocol_error;
                    };
                    conn.consumeRead(consumed);
                    return switch (op) {
                        .text => if (validateTextMessage(conn, conn.fragment_buf.items)) .{ .text = conn.fragment_buf.items } else .protocol_error,
                        .binary => .{ .binary = conn.fragment_buf.items },
                        else => unreachable,
                    };
                }
            },
            .continuation => {
                if (!conn.fragment_active) {
                    conn.sendClose(1002, "unexpected continuation");
                    return .protocol_error;
                }
                if (!canAppendWebSocketFragment(conn.fragment_buf.items.len, frame.payload.len)) {
                    conn.sendClose(1009, "message too big");
                    return .protocol_error;
                }
                conn.fragment_buf.appendSlice(allocator, frame.payload) catch {
                    conn.sendClose(1011, "out of memory");
                    return .protocol_error;
                };
                const op = conn.fragment_opcode;
                const finalize = frame.fin;
                conn.consumeRead(frame.consumed);
                if (finalize) {
                    conn.fragment_active = false;
                    return switch (op) {
                        .text => if (validateTextMessage(conn, conn.fragment_buf.items)) .{ .text = conn.fragment_buf.items } else .protocol_error,
                        .binary => .{ .binary = conn.fragment_buf.items },
                        else => .protocol_error,
                    };
                }
            },
            else => {
                conn.sendClose(1002, "unsupported opcode");
                return .protocol_error;
            },
        }
    }
    return .closed;
}

fn closeNonblocking(conn: *WsConn, code: u16, reason: []const u8) NextNonblockingMessage {
    _ = conn.sendCloseNonblocking(code, reason, true) catch {};
    return .protocol_error;
}

/// Read all currently available bytes without ever blocking the Python event
/// loop. A caller waits for fd readability and retries on `would_block`.
fn wsReadNextMessageNonblocking(conn: *WsConn) NextNonblockingMessage {
    while (!conn.closing.load(.acquire)) {
        if (conn.read_len < 2) {
            switch (conn.fillReadNonblocking()) {
                .progress => continue,
                .would_block => return .would_block,
                .closed => return .closed,
                .failed => return closeNonblocking(conn, 1011, "read failure"),
            }
        }

        const frame = ws.parseServerFrame(conn.readStorage()[0..conn.read_len], WsConn.MAX_MESSAGE) catch |err| switch (err) {
            ws.ParseError.Incomplete => switch (conn.fillReadNonblocking()) {
                .progress => continue,
                .would_block => return .would_block,
                .closed => return .closed,
                .failed => return closeNonblocking(conn, 1011, "read failure"),
            },
            ws.ParseError.PayloadTooLarge => return closeNonblocking(conn, 1009, "message too big"),
            else => return closeNonblocking(conn, 1002, "protocol error"),
        };

        switch (frame.opcode) {
            .ping => {
                _ = conn.writeFrameNonblocking(.pong, frame.payload) catch
                    return closeNonblocking(conn, 1013, "control backpressure");
                conn.consumeRead(frame.consumed);
            },
            .pong => conn.consumeRead(frame.consumed),
            .close => {
                switch (recordPeerClose(conn, frame.payload)) {
                    .valid => {},
                    .invalid_code => return closeNonblocking(conn, 1002, "invalid close code"),
                    .invalid_utf8 => return closeNonblocking(conn, 1007, "invalid utf-8"),
                }
                if (conn.peer_close_code == 1005)
                    _ = conn.sendEmptyCloseNonblocking(true) catch {}
                else
                    _ = conn.sendCloseNonblocking(conn.peer_close_code, conn.peer_close_reason[0..conn.peer_close_reason_len], true) catch {};
                conn.consumeRead(frame.consumed);
                return .closed;
            },
            .text, .binary => {
                if (conn.fragment_active)
                    return closeNonblocking(conn, 1002, "fragment sequence error");
                if (!frame.fin) {
                    conn.fragment_buf.clearRetainingCapacity();
                    if (!canAppendWebSocketFragment(0, frame.payload.len))
                        return closeNonblocking(conn, 1009, "message too big");
                    conn.fragment_opcode = frame.opcode;
                    conn.fragment_active = true;
                    conn.fragment_buf.appendSlice(allocator, frame.payload) catch
                        return closeNonblocking(conn, 1011, "out of memory");
                    conn.consumeRead(frame.consumed);
                } else {
                    const op = frame.opcode;
                    conn.fragment_buf.clearRetainingCapacity();
                    conn.fragment_buf.appendSlice(allocator, frame.payload) catch
                        return closeNonblocking(conn, 1011, "out of memory");
                    conn.consumeRead(frame.consumed);
                    if (op == .text and !std.unicode.utf8ValidateSlice(conn.fragment_buf.items))
                        return closeNonblocking(conn, 1007, "invalid utf-8");
                    return if (op == .text)
                        .{ .text = conn.fragment_buf.items }
                    else
                        .{ .binary = conn.fragment_buf.items };
                }
            },
            .continuation => {
                if (!conn.fragment_active)
                    return closeNonblocking(conn, 1002, "unexpected continuation");
                if (!canAppendWebSocketFragment(conn.fragment_buf.items.len, frame.payload.len))
                    return closeNonblocking(conn, 1009, "message too big");
                conn.fragment_buf.appendSlice(allocator, frame.payload) catch
                    return closeNonblocking(conn, 1011, "out of memory");
                const op = conn.fragment_opcode;
                const finalize = frame.fin;
                conn.consumeRead(frame.consumed);
                if (finalize) {
                    conn.fragment_active = false;
                    if (op == .text and !std.unicode.utf8ValidateSlice(conn.fragment_buf.items))
                        return closeNonblocking(conn, 1007, "invalid utf-8");
                    return if (op == .text)
                        .{ .text = conn.fragment_buf.items }
                    else
                        .{ .binary = conn.fragment_buf.items };
                }
            },
            else => return closeNonblocking(conn, 1002, "unsupported opcode"),
        }
    }
    return .closed;
}

/// Drive a live WebSocket connection. Dispatches to either the in-Zig echo
/// loop (for /ws-echo) or the Python handler invoke path.
fn runWebSocketConnection(
    stream: std.Io.net.Stream,
    path: []const u8,
    query_string: []const u8,
    headers: []const HeaderPair,
    route_snapshot: ?WebSocketRouteEntry,
    tstate: ?*anyopaque,
) !void {
    var conn = WsConn{ .stream = stream };
    defer conn.deinit();

    if (std.mem.eql(u8, path, ECHO_PATH)) {
        runEchoLoop(&conn);
        return;
    }

    const route = route_snapshot orelse {
        conn.sendClose(1011, "no handler");
        return;
    };

    runPythonHandler(&conn, route.handler, path, query_string, headers, tstate);
}

fn runEchoLoop(conn: *WsConn) void {
    while (!conn.closing.load(.acquire)) {
        const msg = wsReadNextMessage(conn);
        switch (msg) {
            .text => |t| conn.writeFrame(true, .text, t) catch return,
            .binary => |b| conn.writeFrame(true, .binary, b) catch return,
            .closed, .protocol_error => return,
        }
    }
}

/// Invoke a Python WS handler. The handler signature is `async def f(ws)`.
/// We construct a WebSocket Python object wrapping a PyCapsule that holds
/// the *WsConn pointer, then call into the Python bootstrap helper
/// `_ws_invoke_handler` which runs the coroutine.
fn runPythonHandler(
    conn: *WsConn,
    handler: *c.PyObject,
    path: []const u8,
    query_string: []const u8,
    headers: []const HeaderPair,
    tstate: ?*anyopaque,
) void {
    // handleOneRequest runs without GIL by default; each Python-calling helper
    // acquires it. Do the same here, then drop it again when the handler
    // returns so subsequent FFI calls (which release+reacquire) can interleave
    // properly during the connection's lifetime.
    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    // Make a capsule from the conn pointer. Python side passes it back into
    // ws_recv/ws_send/ws_close.
    const capsule_name: [*:0]const u8 = "turbonet.WsConn";
    const capsule = c.PyCapsule_New(@ptrCast(conn), capsule_name, null) orelse {
        c.PyErr_Print();
        conn.sendClose(1011, "internal error");
        return;
    };
    defer c.Py_DecRef(capsule);
    defer _ = c.PyCapsule_SetName(capsule, "turbonet.WsConn.closed");

    // Find the bootstrap-installed helper on the turbonet module:
    // `_ws_invoke_handler(handler, capsule, path, query_string, headers, path_params)`.
    const turbonet_mod = c.PyImport_ImportModule("turboapi.turbonet") orelse blk: {
        c.PyErr_Clear();
        break :blk c.PyImport_ImportModule("turbonet") orelse {
            c.PyErr_Print();
            conn.sendClose(1011, "internal error");
            return;
        };
    };
    defer c.Py_DecRef(turbonet_mod);
    invokeHelper(turbonet_mod, handler, capsule, path, query_string, headers);

    // Handler returned (or raised). If it didn't close the connection itself,
    // send a clean close now.
    if (!conn.closing.load(.acquire)) {
        _ = conn.sendCloseNonblocking(1000, "", false) catch {};
        _ = conn.flushPendingFrames() catch false;
    }
}

fn websocketHeadersToPyList(headers: []const HeaderPair) ?*c.PyObject {
    const list = c.PyList_New(0) orelse return null;
    for (headers) |header| {
        const name = py.newBytes(header.name) orelse {
            c.Py_DecRef(list);
            return null;
        };
        const value = py.newBytes(header.value) orelse {
            c.Py_DecRef(name);
            c.Py_DecRef(list);
            return null;
        };
        const pair = c.PyTuple_Pack(2, name, value);
        c.Py_DecRef(name);
        c.Py_DecRef(value);
        if (pair == null) {
            c.Py_DecRef(list);
            return null;
        }
        if (c.PyList_Append(list, pair) != 0) {
            c.Py_DecRef(pair);
            c.Py_DecRef(list);
            return null;
        }
        c.Py_DecRef(pair);
    }
    return list;
}

fn normalizeWebSocketGuardStatus(raw_status: c_long) u16 {
    return switch (raw_status) {
        0 => 0,
        400, 401, 403, 404, 429, 500, 503 => @intCast(raw_status),
        else => 403,
    };
}

/// Invoke a synchronous Python policy before sending the WebSocket 101.
/// Every failure is reduced to a status-only 403 and Python exception text is
/// deliberately cleared, never printed, because it can contain credentials.
fn runWebSocketUpgradeGuard(
    guard: *c.PyObject,
    path: []const u8,
    query_string: []const u8,
    headers: []const HeaderPair,
    tstate: ?*anyopaque,
) u16 {
    const thread_state = tstate orelse return 403;
    py.PyEval_AcquireThread(thread_state);
    defer py.PyEval_ReleaseThread(thread_state);

    const turbonet_mod = c.PyImport_ImportModule("turboapi.turbonet") orelse blk: {
        c.PyErr_Clear();
        break :blk c.PyImport_ImportModule("turbonet") orelse {
            c.PyErr_Clear();
            return 403;
        };
    };
    defer c.Py_DecRef(turbonet_mod);

    const helper = c.PyObject_GetAttrString(turbonet_mod, "_ws_invoke_guard") orelse {
        c.PyErr_Clear();
        return 403;
    };
    defer c.Py_DecRef(helper);

    const py_path = py.newString(path) orelse {
        c.PyErr_Clear();
        return 403;
    };
    defer c.Py_DecRef(py_path);
    const py_query_string = py.newBytes(query_string) orelse {
        c.PyErr_Clear();
        return 403;
    };
    defer c.Py_DecRef(py_query_string);
    const py_headers = websocketHeadersToPyList(headers) orelse {
        c.PyErr_Clear();
        return 403;
    };
    defer c.Py_DecRef(py_headers);

    const args = c.PyTuple_Pack(4, guard, py_path, py_query_string, py_headers) orelse {
        c.PyErr_Clear();
        return 403;
    };
    defer c.Py_DecRef(args);

    const result = c.PyObject_Call(helper, args, null) orelse {
        c.PyErr_Clear();
        return 403;
    };
    defer c.Py_DecRef(result);

    const raw_status = c.PyLong_AsLong(result);
    if (c.PyErr_Occurred() != null) {
        c.PyErr_Clear();
        return 403;
    }
    return normalizeWebSocketGuardStatus(raw_status);
}

/// Send a bounded, status-only denial. The lack of an application body and
/// fixed headers prevents authorization/request metadata from being reflected.
fn sendWebSocketGuardRejection(stream: std.Io.net.Stream, raw_status: u16) void {
    const normalized = normalizeWebSocketGuardStatus(raw_status);
    const status = if (normalized == 0) @as(u16, 403) else normalized;
    const known_reason = statusText(status);
    const reason = if (std.mem.eql(u8, known_reason, "Unknown")) "Rejected" else known_reason;
    var buf: [320]u8 = undefined;
    const auth_header = if (status == 401) "WWW-Authenticate: Bearer\r\n" else "";
    const response = std.fmt.bufPrint(
        &buf,
        "HTTP/1.1 {d} {s}\r\n{s}Cache-Control: no-store\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        .{ status, reason, auth_header },
    ) catch return;
    streamWriteAll(stream, response) catch {};
}

test "WebSocket guard statuses are fail-closed and bounded" {
    try std.testing.expectEqual(@as(u16, 0), normalizeWebSocketGuardStatus(0));
    try std.testing.expectEqual(@as(u16, 401), normalizeWebSocketGuardStatus(401));
    try std.testing.expectEqual(@as(u16, 403), normalizeWebSocketGuardStatus(403));
    try std.testing.expectEqual(@as(u16, 404), normalizeWebSocketGuardStatus(404));
    try std.testing.expectEqual(@as(u16, 429), normalizeWebSocketGuardStatus(429));
    try std.testing.expectEqual(@as(u16, 500), normalizeWebSocketGuardStatus(500));
    try std.testing.expectEqual(@as(u16, 503), normalizeWebSocketGuardStatus(503));
    try std.testing.expectEqual(@as(u16, 403), normalizeWebSocketGuardStatus(-1));
    try std.testing.expectEqual(@as(u16, 403), normalizeWebSocketGuardStatus(200));
    try std.testing.expectEqual(@as(u16, 403), normalizeWebSocketGuardStatus(418));
    try std.testing.expectEqual(@as(u16, 403), normalizeWebSocketGuardStatus(600));
}

fn invokeHelper(
    mod: *c.PyObject,
    handler: *c.PyObject,
    capsule: *c.PyObject,
    path: []const u8,
    query_string: []const u8,
    headers: []const HeaderPair,
) void {
    const helper = c.PyObject_GetAttrString(mod, "_ws_invoke_handler") orelse {
        c.PyErr_Print();
        return;
    };
    defer c.Py_DecRef(helper);

    const py_path = py.newString(path) orelse {
        c.PyErr_Print();
        return;
    };
    defer c.Py_DecRef(py_path);

    const py_query_string = py.newBytes(query_string) orelse {
        c.PyErr_Print();
        return;
    };
    defer c.Py_DecRef(py_query_string);

    const py_headers = websocketHeadersToPyList(headers) orelse {
        c.PyErr_Print();
        return;
    };
    defer c.Py_DecRef(py_headers);

    // WebSocket routes are exact-match in the current native runtime, so no
    // path parameters are resolved yet. Keep the ASGI field explicit so the
    // bridge can pass real values without another public API change when
    // parameterized WebSocket routing lands.
    const py_path_params = c.PyDict_New() orelse {
        c.PyErr_Print();
        return;
    };
    defer c.Py_DecRef(py_path_params);

    const args = c.PyTuple_Pack(6, handler, capsule, py_path, py_query_string, py_headers, py_path_params) orelse {
        c.PyErr_Print();
        return;
    };
    defer c.Py_DecRef(args);

    const result = c.PyObject_Call(helper, args, null);
    if (result) |r| {
        c.Py_DecRef(r);
    } else {
        c.PyErr_Print();
    }
}

// ── WebSocket FFI ──────────────────────────────────────────────────────────
//
// Python-facing primitives, exposed via main.zig method table:
//   _server_add_websocket_route(path, handler)
//   _ws_recv(capsule) -> (type_str, data, write_pending) | None
//   _ws_recv_blocking(capsule) -> (type_str, data)
//   _ws_send_text(capsule, str)
//   _ws_send_bytes(capsule, bytes)
//   _ws_close(capsule, code, reason)
//   _ws_abort(capsule, code, reason)
//   _ws_shutdown(capsule)
//
// Each FFI call extracts the WsConn pointer from the capsule. Blocking calls
// detach the current Python thread state around I/O; readiness calls return
// immediately on would-block.

const WS_CAPSULE_NAME: [*:0]const u8 = "turbonet.WsConn";

fn isValidWebSocketCloseCode(code: c_int) bool {
    return switch (code) {
        1000, 1001, 1002, 1003, 1007, 1008, 1009, 1010, 1011, 1012, 1013, 1014 => true,
        3000...4999 => true,
        else => false,
    };
}

inline fn capsuleToConn(capsule_obj: ?*c.PyObject) ?*WsConn {
    if (capsule_obj == null) return null;
    const raw = c.PyCapsule_GetPointer(capsule_obj, WS_CAPSULE_NAME) orelse return null;
    return @ptrCast(@alignCast(raw));
}

pub fn server_add_websocket_route(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var path: [*c]const u8 = null;
    var handler: ?*c.PyObject = null;
    var guard: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "sO|O", &path, &handler, &guard) == 0) return null;
    if (c.PyCallable_Check(handler) == 0) {
        py.setError("WebSocket handler must be callable", .{});
        return null;
    }
    const guard_obj = if (guard) |value| if (py.isNone(value)) null else value else null;
    if (guard_obj) |value| {
        if (c.PyCallable_Check(value) == 0) {
            py.setError("WebSocket guard must be callable", .{});
            return null;
        }
    }
    const path_s = std.mem.span(path);
    const path_owned = allocator.dupe(u8, path_s) catch {
        py.setError("ws route alloc failed", .{});
        return null;
    };
    c.Py_IncRef(handler.?);
    if (guard_obj) |value| c.Py_IncRef(value);
    const entry = WebSocketRouteEntry{ .handler = handler.?, .guard = guard_obj };

    lockWebSocketRoutes();
    var ws_routes = getWebSocketRoutes();
    const route_slot = ws_routes.getOrPut(path_owned) catch {
        unlockWebSocketRoutes();
        allocator.free(path_owned);
        c.Py_DecRef(entry.handler);
        if (entry.guard) |value| c.Py_DecRef(value);
        py.setError("WebSocket route registration failed", .{});
        return null;
    };
    var replaced_entry: ?WebSocketRouteEntry = null;
    var duplicate_path: ?[]u8 = null;
    if (route_slot.found_existing) {
        // Swap atomically while retaining the map's existing owned key.
        duplicate_path = path_owned;
        replaced_entry = route_slot.value_ptr.*;
        route_slot.value_ptr.* = entry;
    } else {
        // The allocation has succeeded and assigning the value cannot fail.
        route_slot.value_ptr.* = entry;
    }
    unlockWebSocketRoutes();

    // Free/decref only after unlocking: Py_DecRef can run arbitrary Python
    // finalizers, and allocator work should not extend the critical section.
    if (duplicate_path) |owned_path| allocator.free(owned_path);
    if (replaced_entry) |old_entry| {
        c.Py_DecRef(old_entry.handler);
        if (old_entry.guard) |old_guard| c.Py_DecRef(old_guard);
    }
    return py.pyNone();
}

/// Poll the next user-visible WS message without blocking. The third tuple
/// item tells Python that a control reply left bytes queued for the fd writer.
pub fn ws_recv(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var capsule_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "O", &capsule_obj) == 0) return null;
    const conn = capsuleToConn(capsule_obj) orelse {
        py.setError("invalid ws capsule", .{});
        return null;
    };

    const msg = wsReadNextMessageNonblocking(conn);
    const has_pending = conn.hasPendingFrames();
    const pending_obj = c.PyBool_FromLong(if (has_pending) 1 else 0) orelse return null;
    defer c.Py_DecRef(pending_obj);

    switch (msg) {
        .text => |t| {
            const type_str = py.newString("text") orelse return null;
            defer c.Py_DecRef(type_str);
            const data = py.newString(t) orelse {
                return null;
            };
            defer c.Py_DecRef(data);
            return c.PyTuple_Pack(3, type_str, data, pending_obj);
        },
        .binary => |b| {
            const type_str = py.newString("bytes") orelse return null;
            defer c.Py_DecRef(type_str);
            const data = py.newBytes(b) orelse {
                return null;
            };
            defer c.Py_DecRef(data);
            return c.PyTuple_Pack(3, type_str, data, pending_obj);
        },
        .closed => {
            const type_str = py.newString("disconnect") orelse return null;
            defer c.Py_DecRef(type_str);
            const code = c.PyLong_FromLong(conn.peer_close_code) orelse return null;
            defer c.Py_DecRef(code);
            const reason = py.newString(conn.peer_close_reason[0..conn.peer_close_reason_len]) orelse return null;
            defer c.Py_DecRef(reason);
            const close_data = c.PyTuple_Pack(2, code, reason) orelse return null;
            defer c.Py_DecRef(close_data);
            return c.PyTuple_Pack(3, type_str, close_data, pending_obj);
        },
        .protocol_error => {
            const type_str = py.newString("disconnect") orelse return null;
            defer c.Py_DecRef(type_str);
            const code = c.PyLong_FromLong(conn.local_close_code) orelse return null;
            defer c.Py_DecRef(code);
            const reason = py.newString(conn.local_close_reason[0..conn.local_close_reason_len]) orelse return null;
            defer c.Py_DecRef(reason);
            const close_data = c.PyTuple_Pack(2, code, reason) orelse return null;
            defer c.Py_DecRef(close_data);
            return c.PyTuple_Pack(3, type_str, close_data, pending_obj);
        },
        .would_block => {
            // A ping may have queued a partial pong before the parser reached
            // would-block. Surface that control-only progress so Python starts
            // its fd writer; returning None here would leave the pong stranded
            // until another inbound frame happened to arrive.
            if (!has_pending) return py.pyNone();
            const type_str = py.newString("control") orelse return null;
            defer c.Py_DecRef(type_str);
            const none = py.pyNone();
            defer c.Py_DecRef(none);
            return c.PyTuple_Pack(3, type_str, none, pending_obj);
        },
    }
}

/// Direct sequential-handler hot path. This detaches the worker's Python
/// thread state while the native socket waits for a complete user message.
pub fn ws_recv_blocking(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var capsule_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "O", &capsule_obj) == 0) return null;
    const conn = capsuleToConn(capsule_obj) orelse {
        py.setError("invalid ws capsule", .{});
        return null;
    };
    if (conn.nonblocking) {
        c.PyErr_SetString(c.PyExc_RuntimeError, "blocking receive after nonblocking activation");
        return null;
    }

    const save = py.PyEval_SaveThread();
    const msg = wsReadNextMessage(conn);
    py.PyEval_RestoreThread(save);
    switch (msg) {
        .text => |text| {
            const kind = py.newString("text") orelse return null;
            defer c.Py_DecRef(kind);
            const data = py.newString(text) orelse return null;
            defer c.Py_DecRef(data);
            return c.PyTuple_Pack(2, kind, data);
        },
        .binary => |bytes| {
            const kind = py.newString("bytes") orelse return null;
            defer c.Py_DecRef(kind);
            const data = py.newBytes(bytes) orelse return null;
            defer c.Py_DecRef(data);
            return c.PyTuple_Pack(2, kind, data);
        },
        .closed => {
            const kind = py.newString("disconnect") orelse return null;
            defer c.Py_DecRef(kind);
            const code = c.PyLong_FromLong(conn.peer_close_code) orelse return null;
            defer c.Py_DecRef(code);
            const reason = py.newString(conn.peer_close_reason[0..conn.peer_close_reason_len]) orelse return null;
            defer c.Py_DecRef(reason);
            const close_data = c.PyTuple_Pack(2, code, reason) orelse return null;
            defer c.Py_DecRef(close_data);
            return c.PyTuple_Pack(2, kind, close_data);
        },
        .protocol_error => {
            const kind = py.newString("disconnect") orelse return null;
            defer c.Py_DecRef(kind);
            const code = c.PyLong_FromLong(conn.local_close_code) orelse return null;
            defer c.Py_DecRef(code);
            const reason = py.newString(conn.local_close_reason[0..conn.local_close_reason_len]) orelse return null;
            defer c.Py_DecRef(reason);
            const close_data = c.PyTuple_Pack(2, code, reason) orelse return null;
            defer c.Py_DecRef(close_data);
            return c.PyTuple_Pack(2, kind, close_data);
        },
    }
}

pub fn ws_send_text(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var capsule_obj: ?*c.PyObject = null;
    var text: [*c]const u8 = null;
    var text_len: c.Py_ssize_t = 0;
    if (c.PyArg_ParseTuple(args, "Os#", &capsule_obj, &text, &text_len) == 0) return null;
    const conn = capsuleToConn(capsule_obj) orelse {
        py.setError("invalid ws capsule", .{});
        return null;
    };

    const slice = if (text_len > 0) text[0..@intCast(text_len)] else "";
    const save = if (!conn.nonblocking) py.PyEval_SaveThread() else null;
    const write_result = conn.writeFrameNonblocking(.text, slice);
    if (save) |state| py.PyEval_RestoreThread(state);
    const pending = write_result catch |err| {
        if (err == error.Backpressure)
            c.PyErr_SetString(c.PyExc_BufferError, "websocket outbound queue full")
        else
            c.PyErr_SetString(c.PyExc_RuntimeError, "ws write failed");
        return null;
    };
    return if (pending) c.PyBool_FromLong(1) else py.pyNone();
}

pub fn ws_send_bytes(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var capsule_obj: ?*c.PyObject = null;
    var data: [*c]const u8 = null;
    var data_len: c.Py_ssize_t = 0;
    if (c.PyArg_ParseTuple(args, "Oy#", &capsule_obj, &data, &data_len) == 0) return null;
    const conn = capsuleToConn(capsule_obj) orelse {
        py.setError("invalid ws capsule", .{});
        return null;
    };

    const slice = if (data_len > 0) data[0..@intCast(data_len)] else "";
    const save = if (!conn.nonblocking) py.PyEval_SaveThread() else null;
    const write_result = conn.writeFrameNonblocking(.binary, slice);
    if (save) |state| py.PyEval_RestoreThread(state);
    const pending = write_result catch |err| {
        if (err == error.Backpressure)
            c.PyErr_SetString(c.PyExc_BufferError, "websocket outbound queue full")
        else
            c.PyErr_SetString(c.PyExc_RuntimeError, "ws write failed");
        return null;
    };
    return if (pending) c.PyBool_FromLong(1) else py.pyNone();
}

pub fn ws_close(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var capsule_obj: ?*c.PyObject = null;
    var code: c_int = 1000;
    var reason: [*c]const u8 = null;
    var reason_len: c.Py_ssize_t = 0;
    if (c.PyArg_ParseTuple(args, "Oi|s#", &capsule_obj, &code, &reason, &reason_len) == 0) return null;
    if (!isValidWebSocketCloseCode(code)) {
        c.PyErr_SetString(c.PyExc_ValueError, "invalid WebSocket close code");
        return null;
    }
    if (reason_len > 123) {
        c.PyErr_SetString(c.PyExc_ValueError, "WebSocket close reason exceeds 123 UTF-8 bytes");
        return null;
    }
    const conn = capsuleToConn(capsule_obj) orelse {
        py.setError("invalid ws capsule", .{});
        return null;
    };

    const reason_slice = if (reason_len > 0 and reason != null) reason[0..@intCast(reason_len)] else "";
    const save = if (!conn.nonblocking) py.PyEval_SaveThread() else null;
    const write_result = conn.sendCloseNonblocking(@intCast(code), reason_slice, false);
    if (save) |state| py.PyEval_RestoreThread(state);
    const pending = write_result catch |err| {
        if (err == error.Backpressure)
            c.PyErr_SetString(c.PyExc_BufferError, "websocket outbound queue full")
        else
            c.PyErr_SetString(c.PyExc_RuntimeError, "ws close failed");
        return null;
    };
    return c.PyBool_FromLong(if (pending) 1 else 0);
}

pub fn ws_fileno(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var capsule_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "O", &capsule_obj) == 0) return null;
    const conn = capsuleToConn(capsule_obj) orelse {
        py.setError("invalid ws capsule", .{});
        return null;
    };
    return c.PyLong_FromLong(conn.stream.socket.handle);
}

pub fn ws_set_nonblocking(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var capsule_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "O", &capsule_obj) == 0) return null;
    const conn = capsuleToConn(capsule_obj) orelse {
        py.setError("invalid ws capsule", .{});
        return null;
    };
    conn.setNonblocking() catch {
        c.PyErr_SetString(c.PyExc_RuntimeError, "failed to enable nonblocking websocket I/O");
        return null;
    };
    return py.pyNone();
}

pub fn ws_flush(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var capsule_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "O", &capsule_obj) == 0) return null;
    const conn = capsuleToConn(capsule_obj) orelse {
        py.setError("invalid ws capsule", .{});
        return null;
    };
    const empty = conn.flushPendingFrames() catch {
        c.PyErr_SetString(c.PyExc_RuntimeError, "ws flush failed");
        return null;
    };
    return c.PyBool_FromLong(if (empty) 1 else 0);
}

fn wsMetricPut(dict: *c.PyObject, name: [*:0]const u8, value: usize) bool {
    const number = c.PyLong_FromSize_t(value) orelse return false;
    defer c.Py_DecRef(number);
    return c.PyDict_SetItemString(dict, name, number) == 0;
}

pub fn ws_metrics(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var capsule_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "O", &capsule_obj) == 0) return null;
    const conn = capsuleToConn(capsule_obj) orelse {
        py.setError("invalid ws capsule", .{});
        return null;
    };
    conn.write_mutex.lockUncancelable(runtime.io);
    const outbound_messages = conn.pending_count;
    const outbound_bytes = conn.pending_bytes;
    conn.write_mutex.unlock(runtime.io);

    const result = c.PyDict_New() orelse return null;
    if (!wsMetricPut(result, "inbound_messages", 0) or
        !wsMetricPut(result, "inbound_bytes", conn.read_len + conn.fragment_buf.items.len) or
        !wsMetricPut(result, "outbound_messages", outbound_messages) or
        !wsMetricPut(result, "outbound_bytes", outbound_bytes) or
        !wsMetricPut(result, "message_limit", ws_queue_message_limit) or
        !wsMetricPut(result, "byte_limit", ws_queue_byte_limit) or
        !wsMetricPut(result, "write_timeout_ms", ws_write_timeout_ms) or
        !wsMetricPut(result, "worker_count", actual_websocket_workers.load(.acquire)) or
        !wsMetricPut(result, "max_active", max_active_websockets.load(.acquire)))
    {
        c.Py_DecRef(result);
        return null;
    }
    return result;
}

pub fn ws_abort(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var capsule_obj: ?*c.PyObject = null;
    var code: c_int = 1013;
    var reason: [*c]const u8 = null;
    var reason_len: c.Py_ssize_t = 0;
    if (c.PyArg_ParseTuple(args, "Oi|s#", &capsule_obj, &code, &reason, &reason_len) == 0) return null;
    if (!isValidWebSocketCloseCode(code)) {
        c.PyErr_SetString(c.PyExc_ValueError, "invalid WebSocket close code");
        return null;
    }
    if (reason_len > 123) {
        c.PyErr_SetString(c.PyExc_ValueError, "WebSocket close reason exceeds 123 UTF-8 bytes");
        return null;
    }
    const conn = capsuleToConn(capsule_obj) orelse {
        py.setError("invalid ws capsule", .{});
        return null;
    };
    const reason_slice = if (reason_len > 0 and reason != null) reason[0..@intCast(reason_len)] else "";
    const save = py.PyEval_SaveThread();
    conn.abort(@intCast(code), reason_slice);
    py.PyEval_RestoreThread(save);
    return py.pyNone();
}

pub fn ws_shutdown(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var capsule_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "O", &capsule_obj) == 0) return null;
    const conn = capsuleToConn(capsule_obj) orelse {
        py.setError("invalid ws capsule", .{});
        return null;
    };
    const save = py.PyEval_SaveThread();
    conn.shutdown();
    py.PyEval_RestoreThread(save);
    return py.pyNone();
}

fn handleOneRequest(stream: std.Io.net.Stream, tstate: ?*anyopaque) !void {
    // Phase 1: Read headers into a fixed buffer (headers are typically < 8KB)
    var header_buf: [8192]u8 = undefined;
    var total_read: usize = 0;
    var header_end_pos: ?usize = null;

    // Read until we find \r\n\r\n (end of headers) or fill the header buffer
    while (total_read < header_buf.len) {
        const n = posix.read(stream.socket.handle, header_buf[total_read..]) catch return error.ReadError;
        if (n == 0) return error.ConnectionClosed;
        total_read += n;

        // Check if we've received the full headers
        if (findHeaderEnd(header_buf[0..total_read])) |pos| {
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

    // Phase 2: Parse the complete request line (cheap — no allocs). Never let
    // a valid prefix hide a missing version or trailing request-line tokens.
    const first_line_end = std.mem.indexOf(u8, request_head, "\r\n") orelse {
        sendUpgradeError(stream, 400, "Bad Request");
        return error.ConnectionClosed;
    };
    const first_line = request_head[0..first_line_end];
    const request_line = parseHttpRequestLine(first_line) catch {
        sendUpgradeError(stream, 400, "Bad Request");
        return error.ConnectionClosed;
    };
    const method = request_line.method;
    const raw_path = request_line.request_target;

    const q_idx = std.mem.indexOf(u8, raw_path, "?");
    const path = if (q_idx) |i| raw_path[0..i] else raw_path;
    const query_string = if (q_idx) |i| raw_path[i + 1 ..] else "";

    // ── WebSocket upgrade short-circuit ─────────────────────────────────
    // Catches GET requests with Upgrade: websocket BEFORE the normal router
    // lookup. WS routes are stored in a separate map (getWebSocketRoutes())
    // populated by the Python `@app.websocket(...)` decorator, plus the
    // hardcoded /ws-echo demo route.
    if (std.mem.eql(u8, request_line.version, "HTTP/1.1")) {
        switch (tryWebSocketUpgrade(stream, request_head, first_line_end, he, method, path, query_string, tstate)) {
            // Every handled non-transfer outcome is a bounded HTTP rejection
            // with `Connection: close`. Stop the keep-alive loop immediately
            // so a client cannot retain an HTTP worker after a failed upgrade.
            .handled => return error.ConnectionClosed,
            .transferred => return error.ConnectionTransferred,
            .not_websocket => {},
        }
    } else if (hasWebSocketUpgradeHeader(request_head, first_line_end, he)) {
        // RFC 6455 upgrades use HTTP/1.1. Preserve ordinary HTTP compatibility
        // for other parsed versions, but fail a would-be upgrade closed before
        // route lookup, application guard, capacity admission, or 101.
        sendUpgradeError(stream, 400, "Bad Request");
        return error.ConnectionClosed;
    }

    // Phase 3: Route match EARLY — before header parsing, so fast handlers
    // can skip the expensive parseHeaders + body read entirely.
    const rt = getRouter();
    var match = rt.findRoute(method, path) orelse {
        logger.debug("[ZIG] 404 for {s} {s}", .{ method, path });
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
        streamWriteAll(stream, static_entry.response_bytes) catch return;
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
                    const n = posix.read(stream.socket.handle, full[br..db_cl]) catch return;
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
    const entry_ptr = r.getPtr(match.handler_key) orelse {
        logger.warn("[ZIG] handler entry missing for key: {s}", .{match.handler_key});
        sendResponse(stream, 500, "application/json", "{\"error\": \"Internal Server Error\"}");
        return;
    };
    const entry = entry_ptr.*;

    // ── Ultra-fast path: simple handlers that don't need headers or body ──
    switch (entry.handler_tag) {
        .simple_sync_noargs => {
            if (cache_noargs_responses) {
                if (getCachedEntryBody(entry_ptr)) |cached| {
                    sendCachedJsonBody(stream, cached);
                    return;
                }
                callPythonNoArgsEntryCaching(tstate, entry_ptr, stream);
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
                if (getCachedResponse(cache_key)) |cached| {
                    sendCachedJsonBody(stream, cached);
                    return;
                }
                callPythonVectorcallCaching(tstate, entry, query_string, &match.params, stream, cache_key);
            } else {
                callPythonVectorcall(tstate, entry, query_string, &match.params, stream);
            }
            return;
        },
        .simple_async, .simple_async_eager => {
            const eager = entry.handler_tag == .simple_async_eager;
            if (cache_noargs_responses) {
                if (entry.param_count == 0) {
                    if (getCachedEntryBody(entry_ptr)) |cached| {
                        sendCachedJsonBody(stream, cached);
                        return;
                    }
                    callPythonAsyncNoArgs(tstate, entry, stream, entry_ptr, eager);
                } else {
                    var cache_key_buf: [512]u8 = undefined;
                    const cache_key = if (query_string.len > 0)
                        std.fmt.bufPrint(&cache_key_buf, "{s} {s}?{s}", .{ method, path, query_string }) catch path
                    else
                        std.fmt.bufPrint(&cache_key_buf, "{s} {s}", .{ method, path }) catch path;
                    if (getCachedResponse(cache_key)) |cached| {
                        sendCachedJsonBody(stream, cached);
                        return;
                    }
                    callPythonAsyncVectorcall(tstate, entry, query_string, &match.params, stream, cache_key, eager);
                }
            } else if (entry.param_count == 0) {
                callPythonAsyncNoArgs(tstate, entry, stream, null, eager);
            } else {
                callPythonAsyncVectorcall(tstate, entry, query_string, &match.params, stream, null, eager);
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
            const n = posix.read(stream.socket.handle, full_body[body_read..content_length]) catch |err| {
                logger.err("[ZIG] body read error: {}", .{err});
                return;
            };
            if (n == 0) break;
            body_read += n;
        }
        body = full_body[0..body_read];
    }

    // DHI validation for model_sync — single parse, retain tree
    // Skip for form/file routes (body is multipart/urlencoded, not JSON)
    var cached_parse: ?std.json.Parsed(std.json.Value) = null;
    defer if (cached_parse) |*cp| cp.deinit();

    if (body.len > 0 and entry.handler_tag != .form_sync and entry.handler_tag != .file_sync) {
        const ms = getModelSchemas();
        if (ms.get(match.handler_key)) |schema| {
            const vr = dhi.validateJsonRetainParsed(body, &schema);
            switch (vr) {
                .ok => |parsed| {
                    cached_parse = parsed;
                },
                .err => |ve| {
                    defer ve.deinit();
                    logger.warn("[DHI] validation failed for {s}", .{match.handler_key});
                    sendResponse(stream, ve.status_code, "application/json", ve.body);
                    return;
                },
            }
        }
    }

    // Dispatch remaining handler types
    switch (entry.handler_tag) {
        .simple_sync_noargs, .simple_sync, .simple_async, .simple_async_eager => unreachable, // handled above
        .model_sync => {
            if (body.len > 0) {
                if (cached_parse) |cp| {
                    callPythonModelHandlerParsed(tstate, entry, cp.value, &match.params, stream);
                } else {
                    callPythonModelHandlerDirect(tstate, entry, body, &match.params, stream);
                }
                return;
            }
            callPythonHandlerDirect(tstate, entry, query_string, body, headers.items, &match.params, stream);
        },
        .body_sync => {
            callPythonHandlerDirect(tstate, entry, query_string, body, headers.items, &match.params, stream);
        },
        .body_async, .body_async_eager => {
            callPythonAsyncHandlerDirect(tstate, entry, query_string, body, headers.items, &match.params, stream);
        },
        .form_sync, .file_sync => {
            const resp = callPythonHandler(tstate, entry, method, path, query_string, body, headers.items, &match.params);
            defer resp.deinit();
            sendResponse(stream, resp.status_code, resp.content_type, resp.body);
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

fn sendTupleResponse(stream: std.Io.net.Stream, result: *c.PyObject) void {
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

fn sendTupleResponseAndCache(stream: std.Io.net.Stream, result: *c.PyObject, cache_key: []const u8) void {
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

    const body_dupe = allocator.dupe(u8, body_slice) catch return;
    cacheResponse(cache_key, body_dupe);
}

fn sendTupleResponseAndCacheEntry(stream: std.Io.net.Stream, result: *c.PyObject, entry: *HandlerEntry) void {
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

    const body_dupe = allocator.dupe(u8, body_slice) catch return;
    cacheEntryBody(entry, body_dupe);
}

// ── simple_sync_noargs: PyObject_CallNoArgs — no tuple/dict construction ─────

fn callPythonNoArgs(tstate: ?*anyopaque, entry: HandlerEntry, stream: std.Io.net.Stream) void {
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

fn callPythonNoArgsEntryCaching(tstate: ?*anyopaque, entry: *HandlerEntry, stream: std.Io.net.Stream) void {
    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    const result = py.PyObject_CallNoArgs(entry.handler) orelse {
        c.PyErr_Print();
        sendResponse(stream, 500, "application/json", "{\"error\":\"handler failed\"}");
        return;
    };
    defer c.Py_DecRef(result);

    sendTupleResponseAndCacheEntry(stream, result, entry);
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
    stream: std.Io.net.Stream,
) void {
    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    const argc = entry.param_count;
    var argv: [MAX_PARAMS]?*c.PyObject = undefined;
    // Track created objects for Py_DecRef after the call.
    var created: [MAX_PARAMS]?*c.PyObject = @splat(null);
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

fn callPythonAsyncNoArgs(tstate: ?*anyopaque, entry: HandlerEntry, stream: std.Io.net.Stream, cache_entry: ?*HandlerEntry, eager: bool) void {
    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    const result = py.PyObject_CallNoArgs(entry.handler) orelse {
        c.PyErr_Print();
        sendResponse(stream, 500, "application/json", "{\"error\":\"handler failed\"}");
        return;
    };
    defer c.Py_DecRef(result);

    const response_tuple = (if (eager) awaitPythonCoroutineResponseEager(result) else awaitPythonCoroutineResponse(result)) orelse {
        c.PyErr_Print();
        sendResponse(stream, 500, "application/json", "{\"error\":\"handler failed\"}");
        return;
    };
    defer c.Py_DecRef(response_tuple);
    if (cache_entry) |target| {
        sendTupleResponseAndCacheEntry(stream, response_tuple, target);
    } else {
        sendTupleResponse(stream, response_tuple);
    }
}

fn callPythonAsyncVectorcall(
    tstate: ?*anyopaque,
    entry: HandlerEntry,
    query_string: []const u8,
    params: *const router_mod.RouteParams,
    stream: std.Io.net.Stream,
    cache_key: ?[]const u8,
    eager: bool,
) void {
    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    const argc = entry.param_count;
    var argv: [MAX_PARAMS]?*c.PyObject = undefined;
    var created: [MAX_PARAMS]?*c.PyObject = @splat(null);
    defer for (created[0..argc]) |obj| {
        if (obj) |o| c.Py_DecRef(o);
    };

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
                    const f = std.fmt.parseFloat(f64, vs) catch 0.0;
                    break :blk c.PyFloat_FromDouble(f);
                },
                .bool_val => blk: {
                    const b: c_long = if (std.mem.eql(u8, vs, "true") or std.mem.eql(u8, vs, "1")) 1 else 0;
                    break :blk c.PyBool_FromLong(b);
                },
                .str => blk: {
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
            argv[i] = @ptrCast(&c._Py_NoneStruct);
            if (!pm.has_default) last_filled = i + 1;
        }
    }

    const result = py.PyObject_Vectorcall(
        entry.handler,
        @as([*]const ?*c.PyObject, @ptrCast(&argv)),
        last_filled,
        null,
    ) orelse {
        c.PyErr_Print();
        sendResponse(stream, 500, "application/json", "{\"error\":\"handler failed\"}");
        return;
    };
    defer c.Py_DecRef(result);

    const response_tuple = (if (eager) awaitPythonCoroutineResponseEager(result) else awaitPythonCoroutineResponse(result)) orelse {
        c.PyErr_Print();
        sendResponse(stream, 500, "application/json", "{\"error\":\"handler failed\"}");
        return;
    };
    defer c.Py_DecRef(response_tuple);
    if (cache_key) |key| {
        sendTupleResponseAndCache(stream, response_tuple, key);
    } else {
        sendTupleResponse(stream, response_tuple);
    }
}

/// Like callPythonVectorcall but caches the pre-rendered response keyed by full path.
fn callPythonVectorcallCaching(
    tstate: ?*anyopaque,
    entry: HandlerEntry,
    query_string: []const u8,
    params: *const router_mod.RouteParams,
    stream: std.Io.net.Stream,
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

fn setPathParamsKwarg(kwargs: *c.PyObject, params: *const router_mod.RouteParams) bool {
    if (params.len == 0) return true;

    const py_path_params = c.PyDict_New() orelse return false;
    defer c.Py_DecRef(py_path_params);

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

    return c.PyDict_SetItemString(kwargs, "path_params", py_path_params) == 0;
}

fn callPythonHandlerDirect(tstate: ?*anyopaque, entry: HandlerEntry, query_string: []const u8, body: []const u8, headers: []const HeaderPair, params: *const router_mod.RouteParams, stream: std.Io.net.Stream) void {
    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    const kwargs = c.PyDict_New() orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
    defer c.Py_DecRef(kwargs);

    if (!setPathParamsKwarg(kwargs, params)) {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    }

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

    const py_headers = c.PyDict_New() orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
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

fn callPythonAsyncHandlerDirect(tstate: ?*anyopaque, entry: HandlerEntry, query_string: []const u8, body: []const u8, headers: []const HeaderPair, params: *const router_mod.RouteParams, stream: std.Io.net.Stream) void {
    py.PyEval_AcquireThread(tstate);
    defer py.PyEval_ReleaseThread(tstate);

    const kwargs = c.PyDict_New() orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
    defer c.Py_DecRef(kwargs);

    if (!setPathParamsKwarg(kwargs, params)) {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    }

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

    const py_headers = c.PyDict_New() orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
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

    if (c.PyCoro_CheckExact(result) == 0) {
        sendTupleResponse(stream, result);
        return;
    }

    const awaited = awaitPythonCoroutine(result) orelse {
        c.PyErr_Print();
        sendResponse(stream, 500, "application/json", "{\"error\":\"handler failed\"}");
        return;
    };
    defer c.Py_DecRef(awaited);
    sendTupleResponse(stream, awaited);
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

fn callPythonModelHandlerDirect(tstate: ?*anyopaque, entry: HandlerEntry, body: []const u8, params: *const router_mod.RouteParams, stream: std.Io.net.Stream) void {
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

    if (!setPathParamsKwarg(kwargs, params)) {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
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

    sendTupleResponse(stream, result);
}

/// Single-parse variant: takes a pre-parsed std.json.Value from validateJsonRetainParsed.
/// Eliminates the second JSON parse that callPythonModelHandlerDirect does.
fn callPythonModelHandlerParsed(tstate: ?*anyopaque, entry: HandlerEntry, json_value: std.json.Value, params: *const router_mod.RouteParams, stream: std.Io.net.Stream) void {
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

    if (!setPathParamsKwarg(kwargs, params)) {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
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

    // ── Multipart / urlencoded form parsing ──
    var content_type_lower: [256]u8 = undefined;
    var ct_len: usize = 0;
    for (headers) |h| {
        if (std.ascii.eqlIgnoreCase(h.name, "content-type")) {
            ct_len = @min(h.value.len, content_type_lower.len);
            for (h.value[0..ct_len], 0..) |ch, i| {
                content_type_lower[i] = std.ascii.toLower(ch);
            }
            break;
        }
    }
    const req_ct_slice = content_type_lower[0..ct_len];

    if (std.mem.startsWith(u8, req_ct_slice, "multipart/form-data")) {
        if (multipart_mod.extractBoundary(req_ct_slice)) |boundary| {
            if (body.len > 0) {
                const mp_opt = multipart_mod.parseMultipart(allocator, body, boundary) catch null;
                if (mp_opt) |mp| {
                    defer mp.deinit(allocator);

                    // form_fields dict: {name: value, ...}
                    const py_form_fields = c.PyDict_New() orelse return errorResponse(err_ct, err_body);
                    defer c.Py_DecRef(py_form_fields);
                    for (mp.fields) |f| {
                        const fk = py.newString(f.name) orelse continue;
                        const fv = py.newString(f.value) orelse {
                            c.Py_DecRef(fk);
                            continue;
                        };
                        _ = c.PyDict_SetItem(py_form_fields, fk, fv);
                        c.Py_DecRef(fk);
                        c.Py_DecRef(fv);
                    }
                    _ = c.PyDict_SetItemString(kwargs, "form_fields", py_form_fields);

                    // file_fields list: [{name, filename, content_type, body}, ...]
                    const py_file_list = c.PyList_New(@intCast(mp.files.len)) orelse return errorResponse(err_ct, err_body);
                    defer c.Py_DecRef(py_file_list);
                    for (mp.files, 0..) |f, i| {
                        const file_dict = c.PyDict_New() orelse continue;
                        if (py.newString(f.name)) |v| {
                            _ = c.PyDict_SetItemString(file_dict, "name", v);
                            c.Py_DecRef(v);
                        }
                        if (py.newString(f.filename)) |v| {
                            _ = c.PyDict_SetItemString(file_dict, "filename", v);
                            c.Py_DecRef(v);
                        }
                        if (py.newString(f.content_type)) |v| {
                            _ = c.PyDict_SetItemString(file_dict, "content_type", v);
                            c.Py_DecRef(v);
                        }
                        const file_bytes = c.PyBytes_FromStringAndSize(@ptrCast(f.body.ptr), @intCast(f.body.len));
                        if (file_bytes) |fb| {
                            _ = c.PyDict_SetItemString(file_dict, "body", fb);
                            c.Py_DecRef(fb);
                        }
                        _ = c.PyList_SetItem(py_file_list, @intCast(i), file_dict);
                    }
                    _ = c.PyDict_SetItemString(kwargs, "file_fields", py_file_list);
                }
            }
        }
    } else if (std.mem.startsWith(u8, req_ct_slice, "application/x-www-form-urlencoded")) {
        if (body.len > 0) {
            const ue_opt = multipart_mod.parseUrlencoded(allocator, body) catch null;
            if (ue_opt) |ue| {
                defer ue.deinit(allocator);

                const py_form_fields = c.PyDict_New() orelse return errorResponse(err_ct, err_body);
                defer c.Py_DecRef(py_form_fields);
                for (ue.fields) |f| {
                    const fk = py.newString(f.name) orelse continue;
                    const fv = py.newString(f.value) orelse {
                        c.Py_DecRef(fk);
                        continue;
                    };
                    _ = c.PyDict_SetItem(py_form_fields, fk, fv);
                    c.Py_DecRef(fk);
                    c.Py_DecRef(fv);
                }
                _ = c.PyDict_SetItemString(kwargs, "form_fields", py_form_fields);
            }
        }
    }

    // ── Call handler with PyObject_Call(handler, empty_tuple, kwargs) ──
    const empty_tuple = c.PyTuple_New(0) orelse return errorResponse(err_ct, err_body);
    defer c.Py_DecRef(empty_tuple);

    var result = c.PyObject_Call(entry.handler, empty_tuple, kwargs) orelse {
        c.PyErr_Print();
        return errorResponse(err_ct, err_body);
    };
    defer c.Py_DecRef(result);

    // ── Async handler support: await coroutine on the worker's reusable event loop ──
    if (c.PyCoro_CheckExact(result) != 0) {
        const awaited = awaitPythonCoroutine(result) orelse {
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

    // content — json.dumps() if not already a string or raw bytes
    var body_slice: []const u8 = "null";
    if (c.PyDict_GetItemString(result, "content")) |content_obj| {
        if (c.PyUnicode_Check(content_obj) != 0) {
            // Already a string, use directly
            if (c.PyUnicode_AsUTF8(content_obj)) |cs| {
                body_slice = std.mem.span(cs);
            }
        } else if (c.PyBytes_Check(content_obj) != 0) {
            var size: c.Py_ssize_t = 0;
            var buf: [*c]u8 = undefined;
            if (c.PyBytes_AsStringAndSize(content_obj, @ptrCast(&buf), &size) == 0) {
                body_slice = buf[0..@intCast(size)];
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
pub fn sendResponse(stream: std.Io.net.Stream, status: u16, content_type: []const u8, body: []const u8) void {
    // TFB requires Server + Date headers
    const date_str = currentHttpDate();
    const cors = cors_headers; // "" when disabled — zero overhead

    if (status == 200 and cors.len == 0 and std.mem.eql(u8, content_type, "application/json")) {
        var header_buf: [256]u8 = undefined;
        const header = std.fmt.bufPrint(
            &header_buf,
            "HTTP/1.1 200 OK\r\nServer: TurboAPI\r\nDate: {s}\r\nContent-Type: application/json\r\nContent-Length: {d}\r\nConnection: keep-alive\r\n\r\n",
            .{ date_str, body.len },
        ) catch return;

        const total = header.len + body.len;
        if (total <= 4096) {
            var resp_buf: [4096]u8 = undefined;
            @memcpy(resp_buf[0..header.len], header);
            @memcpy(resp_buf[header.len..total], body);
            streamWriteAll(stream, resp_buf[0..total]) catch return;
        } else {
            streamWriteAll(stream, header) catch return;
            if (body.len > 0) streamWriteAll(stream, body) catch return;
        }
        return;
    }

    var header_buf: [512]u8 = undefined;
    const header = std.fmt.bufPrint(
        &header_buf,
        "HTTP/1.1 {d} {s}\r\nServer: TurboAPI\r\nDate: {s}\r\nContent-Type: {s}\r\nContent-Length: {d}\r\nConnection: keep-alive",
        .{ status, statusText(status), date_str, content_type, body.len },
    ) catch return;

    // Assemble: header + cors_headers (pre-rendered, "" if disabled) + \r\n\r\n + body
    const trailer = "\r\n\r\n";
    const total = header.len + cors.len + trailer.len + body.len;
    if (total <= 4096) {
        var resp_buf: [4096]u8 = undefined;
        var pos: usize = 0;
        @memcpy(resp_buf[pos .. pos + header.len], header);
        pos += header.len;
        if (cors.len > 0) {
            @memcpy(resp_buf[pos .. pos + cors.len], cors);
            pos += cors.len;
        }
        @memcpy(resp_buf[pos .. pos + trailer.len], trailer);
        pos += trailer.len;
        @memcpy(resp_buf[pos .. pos + body.len], body);
        pos += body.len;
        streamWriteAll(stream, resp_buf[0..pos]) catch return;
    } else {
        streamWriteAll(stream, header) catch return;
        if (cors.len > 0) streamWriteAll(stream, cors) catch return;
        streamWriteAll(stream, trailer) catch return;
        if (body.len > 0) streamWriteAll(stream, body) catch return;
    }
}

// ── configure_rate_limiting(enabled, requests_per_minute) ──

pub fn configure_rate_limiting(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    // No-op for now – will implement later
    return py.pyNone();
}

const CacheThreadCtx = struct {
    key: []const u8,
    body: []const u8,
    iterations: usize,
};

fn cacheThreadWorker(ctx: *const CacheThreadCtx) void {
    for (0..ctx.iterations) |_| {
        const rendered = allocator.dupe(u8, ctx.body) catch return;
        cacheResponse(ctx.key, rendered);
        const cached = getCachedResponse(ctx.key) orelse continue;
        std.debug.assert(std.mem.eql(u8, cached, ctx.body));
    }
}

test "websocket capacity is bounded by its isolated worker pool" {
    const ordinary = clampWebSocketCapacity(24, 1000);
    try std.testing.expectEqual(@as(usize, 24), ordinary.worker_count);
    try std.testing.expectEqual(@as(usize, 24), ordinary.max_active);

    const smaller_limit = clampWebSocketCapacity(24, 4);
    try std.testing.expectEqual(@as(usize, 24), smaller_limit.worker_count);
    try std.testing.expectEqual(@as(usize, 4), smaller_limit.max_active);

    const no_workers = clampWebSocketCapacity(0, 99);
    try std.testing.expectEqual(@as(usize, 0), no_workers.worker_count);
    try std.testing.expectEqual(@as(usize, 0), no_workers.max_active);
}

test "websocket close code validation excludes reserved and out-of-range values" {
    try std.testing.expect(isValidWebSocketCloseCode(1000));
    try std.testing.expect(isValidWebSocketCloseCode(1013));
    try std.testing.expect(isValidWebSocketCloseCode(3000));
    try std.testing.expect(isValidWebSocketCloseCode(4999));
    try std.testing.expect(!isValidWebSocketCloseCode(-1));
    try std.testing.expect(!isValidWebSocketCloseCode(999));
    try std.testing.expect(!isValidWebSocketCloseCode(1005));
    try std.testing.expect(!isValidWebSocketCloseCode(1015));
    try std.testing.expect(!isValidWebSocketCloseCode(5000));
}

test "response cache is safe under concurrent access" {
    // std.Io.Mutex requires an initialized runtime.io — set up a minimal threaded runtime.
    runtime.initForTest(std.heap.c_allocator, .{ .async_limit = .nothing });
    defer runtime.deinitForTest();

    response_cache = null;
    response_cache_count = 0;
    response_cache_lock = .init;

    var threads: [8]std.Thread = undefined;
    var ctxs: [8]CacheThreadCtx = undefined;

    for (&ctxs, 0..) |*ctx, i| {
        const key = if ((i % 2) == 0) "GET /items/1" else "GET /items/2";
        const body = if ((i % 2) == 0) "{\"item_id\":1}" else "{\"item_id\":2}";
        ctx.* = .{ .key = key, .body = body, .iterations = 500 };
        threads[i] = try std.Thread.spawn(.{}, cacheThreadWorker, .{ctx});
    }

    for (threads) |thread| thread.join();

    try std.testing.expectEqual(@as(usize, 2), response_cache_count);
    try std.testing.expectEqualStrings("{\"item_id\":1}", getCachedResponse("GET /items/1").?);
    try std.testing.expectEqualStrings("{\"item_id\":2}", getCachedResponse("GET /items/2").?);
}

test "websocket read buffer grows past inline capacity without losing bytes" {
    var conn = WsConn{ .stream = undefined };
    defer conn.deinit();
    @memset(&conn.read_buf, 0xA5);
    conn.read_len = conn.read_buf.len;

    try std.testing.expect(conn.ensureReadSpace());
    try std.testing.expect(conn.read_overflow != null);
    try std.testing.expect(conn.readStorage().len > conn.read_buf.len);
    try std.testing.expectEqualSlices(u8, &conn.read_buf, conn.readStorage()[0..conn.read_buf.len]);
}

test "websocket fragmented message aggregate is bounded" {
    try std.testing.expect(canAppendWebSocketFragment(0, WsConn.MAX_MESSAGE));
    try std.testing.expect(canAppendWebSocketFragment(WsConn.MAX_MESSAGE - 1, 1));
    try std.testing.expect(!canAppendWebSocketFragment(WsConn.MAX_MESSAGE, 1));
    try std.testing.expect(!canAppendWebSocketFragment(WsConn.MAX_MESSAGE + 1, 0));
}

// ── Fuzz tests ───────────────────────────────────────────────────────────────
// Run: zig build fuzz-http  (then execute the binary with --fuzz)
//
// These tests exercise the parsing functions used by handleOneRequest.
// The invariants are: no panics, no out-of-bounds access, bounded output.

fn fuzz_percentDecode(_: void, smith: *std.testing.Smith) anyerror!void {
    const input = smith.in orelse return;
    var buf: [4096]u8 = undefined;
    const out = percentDecode(input, &buf);
    // Decoded output is never longer than percent-encoded input
    try std.testing.expect(out.len <= input.len);
    // Output must fit in buffer
    try std.testing.expect(out.len <= buf.len);
    // Output must be a subslice of buf
    const buf_start = @intFromPtr(&buf);
    const buf_end = buf_start + buf.len;
    const out_start = @intFromPtr(out.ptr);
    try std.testing.expect(out_start >= buf_start and out_start <= buf_end);
}

test "fuzz: percentDecode — output bounded, no OOB" {
    try std.testing.fuzz({}, fuzz_percentDecode, .{
        .corpus = &.{
            "%00", // null byte
            "%GG", // invalid hex digits
            "%", // bare percent at end of input
            "%2", // truncated percent sequence
            "hello+world", // plus → space
            "a%20b%20c", // spaces
            "%FF%FE%FD", // high bytes
            &@as([200]u8, @splat('%')), // 200 bare percents
            "%2F%2F..%2F..%2Fetc%2Fpasswd", // path traversal
            "%00%00%00", // three null bytes
        },
    });
}

fn fuzz_queryStringGet(_: void, smith: *std.testing.Smith) anyerror!void {
    const input = smith.in orelse return;
    // Split: first 16 bytes = key, remainder = query string
    const split = @min(input.len, 16);
    const key = input[0..split];
    const qs = if (split < input.len) input[split..] else "";

    const result = queryStringGet(qs, key);
    if (result) |v| {
        // Returned slice must be within the query string buffer
        const qs_start = @intFromPtr(qs.ptr);
        const qs_end = qs_start + qs.len;
        const v_start = @intFromPtr(v.ptr);
        try std.testing.expect(v_start >= qs_start and v_start <= qs_end);
    }
}

test "fuzz: queryStringGet — result is within input, no panic" {
    try std.testing.fuzz({}, fuzz_queryStringGet, .{
        .corpus = &.{
            "key" ++ "key=value",
            "x" ++ "x=1&y=2&z=3",
            "a" ++ "a=&b=c",
            "k" ++ "k",
            "" ++ "=value",
            "foo" ++ "foo=bar&foo=baz", // duplicate key
            "q" ++ "q=" ++ @as([2000]u8, @splat('A')), // very long value
            "k" ++ "k=\x00\xFF", // binary values
            "k" ++ "&&&&&", // no values, only separators
        },
    });
}

fn fuzz_requestLineParsing(_: void, smith: *std.testing.Smith) anyerror!void {
    const input = smith.in orelse return;
    if (input.len == 0) return;

    // The parser searches for \r\n\r\n to delimit headers from body.
    // If absent → server returns 431 and stops. We mirror that.
    const he = std.mem.indexOf(u8, input, "\r\n\r\n") orelse return;

    // Parse the first line (request line).
    const first_line_end = std.mem.indexOf(u8, input[0..he], "\r\n") orelse return;
    const first_line = input[0..first_line_end];

    var parts = std.mem.splitScalar(u8, first_line, ' ');
    const method = parts.next() orelse return;
    const raw_path = parts.next() orelse return;
    _ = method;

    // Split path from query string at '?'
    const q_idx = std.mem.indexOf(u8, raw_path, "?");
    const path = if (q_idx) |i| raw_path[0..i] else raw_path;
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
    try std.testing.fuzz({}, fuzz_requestLineParsing, .{
        .corpus = &.{
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
            "GET /" ++ @as([7000]u8, @splat('a')) ++ " HTTP/1.1\r\n\r\n",
            // Very long header value
            "GET / HTTP/1.1\r\nX-Custom: " ++ @as([7000]u8, @splat('B')) ++ "\r\n\r\n",
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
        },
    });
}
