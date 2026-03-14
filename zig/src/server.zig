// TurboServer – Zig HTTP server core.
// Placeholder that registers routes and runs an event loop.
// The actual HTTP serving uses Zig's std.net / std.http.

const std = @import("std");
const py = @import("py.zig");
const c = py.c;
const router_mod = @import("router.zig");
const dhi = @import("dhi_validator.zig");

const allocator = std.heap.c_allocator;

// ── Route storage ───────────────────────────────────────────────────────────

const HandlerEntry = struct {
    handler: *c.PyObject,
    handler_type: []const u8,
    param_types_json: []const u8,
    original_handler: ?*c.PyObject,
    model_param_name: ?[]const u8,
    model_class: ?*c.PyObject,
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

var routes: ?std.StringHashMap(HandlerEntry) = null;
var native_routes: ?std.StringHashMap(NativeHandlerEntry) = null;
var model_schemas: ?std.StringHashMap(dhi.ModelSchema) = null;
var router: ?router_mod.Router = null;
var server_host: []const u8 = "127.0.0.1";
var server_port: u16 = 8000;

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

fn getModelSchemas() *std.StringHashMap(dhi.ModelSchema) {
    if (model_schemas == null) {
        model_schemas = std.StringHashMap(dhi.ModelSchema).init(allocator);
    }
    return &model_schemas.?;
}

fn getRouter() *router_mod.Router {
    if (router == null) {
        router = router_mod.Router.init(allocator);
    }
    return &router.?;
}

// ── server_new(host, port) -> state dict ────────────────────────────────────

pub fn server_new(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var host: [*c]const u8 = "127.0.0.1";
    var port: c_int = 8000;

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
                    port = @intCast(c.PyLong_AsLong(item));
                }
            }
        }
    }

    server_host = std.mem.span(host);
    server_port = @intCast(port);

    // Return a state dict
    const d = c.PyDict_New() orelse return null;
    const h_obj = c.PyUnicode_FromString(host) orelse return null;
    _ = c.PyDict_SetItemString(d, "host", h_obj);
    c.Py_DecRef(h_obj);
    const p_obj = c.PyLong_FromLong(port) orelse return null;
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
    const key = std.fmt.allocPrint(allocator, "{s} {s}", .{ method_s, path_s }) catch return null;
    getRoutes().put(key, .{
        .handler = handler.?,
        .handler_type = std.mem.span(ht),
        .param_types_json = std.mem.span(ptj),
        .original_handler = orig,
        .model_param_name = null,
        .model_class = null,
    }) catch return null;
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

// ── add_middleware(middleware_obj) – currently a no-op ──

pub fn server_add_middleware(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    return py.pyNone();
}

// ── run() – start the HTTP server ──

// ── Thread pool for connection handling ─────────────────────────────────────

const POOL_SIZE = 8;

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
                // Queue full — drop connection
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

    fn workerLoop(queue: *Queue) void {
        while (true) {
            const stream = queue.pop();
            handleConnection(stream);
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

    // Start thread pool
    pool.init();

    std.debug.print("🚀 TurboNet-Zig server listening on {s}:{d}\n", .{ server_host, server_port });
    std.debug.print("🎯 Zig HTTP core active – {d}-thread pool!\n", .{POOL_SIZE});

    // Release the GIL before entering the accept loop so spawned threads
    // can acquire it to call Python handlers.
    const save = py.PyEval_SaveThread();

    while (true) {
        const conn = tcp_server.accept() catch continue;
        pool.queue.push(conn.stream);
    }

    // Restore GIL (unreachable in practice, but correct)
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

fn handleConnection(stream: std.net.Stream) void {
    defer stream.close();

    // Keep-alive loop — handle multiple requests on the same connection
    while (true) {
        handleOneRequest(stream) catch return;
    }
}

fn handleOneRequest(stream: std.net.Stream) !void {
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
        // No \r\n\r\n found — malformed or headers too large
        sendResponse(stream, 431, "text/plain", "Request Header Fields Too Large");
        return error.HeadersTooLarge;
    };

    const request_head = header_buf[0..total_read];

    // Parse the first line to get method + path
    const first_line_end = std.mem.indexOf(u8, request_head, "\r\n") orelse return;
    const first_line = request_head[0..first_line_end];

    // "GET /path HTTP/1.1"
    var parts = std.mem.splitScalar(u8, first_line, ' ');
    const method = parts.next() orelse return;
    const raw_path = parts.next() orelse return;

    // std.debug.print("[ZIG] {s} {s}\n", .{ method, raw_path });

    // Split path from query string
    const q_idx = std.mem.indexOf(u8, raw_path, "?");
    const path = if (q_idx) |i| raw_path[0..i] else raw_path;
    const query_string = if (q_idx) |i| raw_path[i + 1 ..] else "";

    // Parse HTTP headers
    var headers = parseHeaders(request_head, first_line_end, he);
    defer headers.deinit(allocator);

    // Phase 2: Read body using Content-Length
    const body_start = he + 4; // past \r\n\r\n
    const already_read_body = request_head[body_start..total_read];

    // Find Content-Length header
    var content_length: usize = 0;
    for (headers.items) |h| {
        if (std.ascii.eqlIgnoreCase(h.name, "content-length")) {
            content_length = std.fmt.parseInt(usize, h.value, 10) catch 0;
            break;
        }
    }

    // Cap at 16 MB to prevent abuse
    const max_body: usize = 16 * 1024 * 1024;
    if (content_length > max_body) {
        sendResponse(stream, 413, "application/json", "{\"error\": \"Payload Too Large\"}");
        return;
    }

    var body: []const u8 = "";
    var body_owned: ?[]u8 = null;
    defer if (body_owned) |b| allocator.free(b);

    if (content_length == 0) {
        // No body expected — use whatever we already have (typically empty)
        body = already_read_body;
    } else if (already_read_body.len >= content_length) {
        // We already read the entire body in the header read
        body = already_read_body[0..content_length];
    } else {
        // Need to read more body data from the stream
        const full_body = allocator.alloc(u8, content_length) catch {
            sendResponse(stream, 500, "application/json", "{\"error\": \"Out of memory\"}");
            return;
        };
        body_owned = full_body;

        // Copy the portion we already have
        @memcpy(full_body[0..already_read_body.len], already_read_body);
        var body_read: usize = already_read_body.len;

        // Read the rest
        while (body_read < content_length) {
            const n = stream.read(full_body[body_read..content_length]) catch |err| {
                std.debug.print("[ZIG] body read error: {}\n", .{err});
                return;
            };
            if (n == 0) break; // client disconnected
            body_read += n;
        }
        body = full_body[0..body_read];
    }

    // std.debug.print("[ZIG] received {d} header bytes + {d} body bytes\n", .{ he + 4, body.len });

    // Match route via radix trie
    const rt = getRouter();
    var match = rt.findRoute(method, path) orelse {
        std.debug.print("[ZIG] 404 for {s} {s}\n", .{ method, path });
        sendResponse(stream, 404, "application/json", "{\"error\": \"Not Found\"}");
        return;
    };
    defer match.deinit();

    // Check native (FFI) routes first — no GIL, no Python, zero overhead
    const nr = getNativeRoutes();
    if (nr.get(match.handler_key)) |native_entry| {
        std.debug.print("[FFI] native handler for {s}\n", .{match.handler_key});
        const ffi_resp = callNativeHandler(native_entry, method, path, query_string, body, headers.items, &match.params);
        const resp_ct = ffi_resp.content_type[0..ffi_resp.content_type_len];
        const resp_body = ffi_resp.body[0..ffi_resp.body_len];
        sendResponse(stream, ffi_resp.status_code, resp_ct, resp_body);
        return;
    }

    // Fall through to Python handler
    const r = getRoutes();
    const entry = r.get(match.handler_key) orelse {
        std.debug.print("[ZIG] handler entry missing for key: {s}\n", .{match.handler_key});
        sendResponse(stream, 500, "application/json", "{\"error\": \"Internal Server Error\"}");
        return;
    };

    // Zig-native dhi validation for model_sync routes — reject invalid bodies
    // before touching the GIL, saving a full Python round-trip on bad input.
    if (body.len > 0) {
        const ms = getModelSchemas();
        if (ms.get(match.handler_key)) |schema| {
            const vr = dhi.validateJson(body, &schema);
            switch (vr) {
                .ok => {}, // validation passed, continue to Python handler
                .err => |ve| {
                    defer ve.deinit();
                    std.debug.print("[DHI] validation failed for {s}\n", .{match.handler_key});
                    sendResponse(stream, ve.status_code, "application/json", ve.body);
                    return;
                },
            }
        }
    }

    // Use fast dispatch for simple_sync/body_sync/model_sync handlers —
    // writes response directly to stream while holding the GIL (zero-copy)
    const ht = entry.handler_type;
    if (std.mem.eql(u8, ht, "model_sync") and body.len > 0) {
        callPythonModelHandlerDirect(entry, body, &match.params, stream);
        return;
    }
    if (std.mem.eql(u8, ht, "simple_sync") or std.mem.eql(u8, ht, "body_sync") or std.mem.eql(u8, ht, "model_sync")) {
        callPythonHandlerDirect(entry, query_string, body, &match.params, stream);
        return;
    }

    const resp = callPythonHandler(entry, method, path, query_string, body, headers.items, &match.params);
    defer resp.deinit();
    sendResponse(stream, resp.status_code, resp.content_type, resp.body);
}

// ── FFI native handler dispatch (no GIL, no Python) ─────────────────────────

fn callNativeHandler(
    entry: NativeHandlerEntry,
    method: []const u8,
    path: []const u8,
    query_string: []const u8,
    body: []const u8,
    headers: []const HeaderPair,
    params: *const std.StringHashMap([]const u8),
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

    var pit = params.iterator();
    while (pit.next()) |pe| {
        p_names_list.append(allocator, pe.key_ptr.*.ptr) catch continue;
        p_name_lens_list.append(allocator, pe.key_ptr.*.len) catch continue;
        p_values_list.append(allocator, pe.value_ptr.*.ptr) catch continue;
        p_value_lens_list.append(allocator, pe.value_ptr.*.len) catch continue;
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

// ── Fast Python handler dispatch (simple_sync/body_sync) ────────────────────
// Zero-copy: calls Python, reads response string, writes to stream — all while
// holding the GIL. No heap allocations for the response.

fn callPythonHandlerDirect(entry: HandlerEntry, query_string: []const u8, body: []const u8, params: *const std.StringHashMap([]const u8), stream: std.net.Stream) void {
    const state = c.PyGILState_Ensure();
    defer c.PyGILState_Release(state);

    const kwargs = c.PyDict_New() orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
    defer c.Py_DecRef(kwargs);

    // Only pass what fast handlers need: path_params, query_string, body
    const py_path_params = c.PyDict_New() orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
    defer c.Py_DecRef(py_path_params);
    {
        var pit = params.iterator();
        while (pit.next()) |pe| {
            const pk = py.newString(pe.key_ptr.*) orelse continue;
            const pv = py.newString(pe.value_ptr.*) orelse {
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

    // Call handler
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

    // Extract status_code
    var status_code: u16 = 200;
    if (c.PyDict_GetItemString(result, "status_code")) |sc| {
        const code = c.PyLong_AsLong(sc);
        if (code >= 100 and code <= 599) {
            status_code = @intCast(code);
        }
    }

    // Content-type — check if handler returned a custom content_type
    var content_type: []const u8 = "application/json";
    if (c.PyDict_GetItemString(result, "content_type")) |ct_obj| {
        if (c.PyUnicode_Check(ct_obj) != 0) {
            if (c.PyUnicode_AsUTF8(ct_obj)) |cs| {
                content_type = std.mem.span(cs);
            }
        }
    }

    // Content — read pre-serialized string or bytes directly from Python object
    // and write to stream without copying (zero-copy)
    var body_slice: []const u8 = "null";
    if (c.PyDict_GetItemString(result, "content")) |content_obj| {
        if (c.PyUnicode_Check(content_obj) != 0) {
            if (c.PyUnicode_AsUTF8(content_obj)) |cs| {
                body_slice = std.mem.span(cs);
            }
        } else if (c.PyBytes_Check(content_obj) != 0) {
            // Binary content (e.g. audio/wav, image/png)
            var size: c.Py_ssize_t = 0;
            var buf: [*c]u8 = undefined;
            if (c.PyBytes_AsStringAndSize(content_obj, @ptrCast(&buf), &size) == 0) {
                body_slice = buf[0..@intCast(size)];
            }
        }
    }

    // Write response directly — body_slice points into the Python object,
    // which is alive because we hold `result` ref until after the write.
    sendResponse(stream, status_code, content_type, body_slice);
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

fn callPythonModelHandlerDirect(entry: HandlerEntry, body: []const u8, params: *const std.StringHashMap([]const u8), stream: std.net.Stream) void {
    // Parse JSON in Zig — no Python json.loads needed
    const parsed = std.json.parseFromSlice(std.json.Value, allocator, body, .{}) catch {
        sendResponse(stream, 400, "application/json", "{\"error\":\"Invalid JSON\"}");
        return;
    };
    defer parsed.deinit();

    const state = c.PyGILState_Ensure();
    defer c.PyGILState_Release(state);

    // Convert parsed JSON to Python dict
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

    // Pass body_dict instead of raw body bytes
    _ = c.PyDict_SetItemString(kwargs, "body_dict", py_body_dict);

    // path_params
    const py_path_params = c.PyDict_New() orelse {
        sendResponse(stream, 500, "application/json", "{\"error\":\"Internal Server Error\"}");
        return;
    };
    defer c.Py_DecRef(py_path_params);
    {
        var pit = params.iterator();
        while (pit.next()) |pe| {
            const pk = py.newString(pe.key_ptr.*) orelse continue;
            const pv = py.newString(pe.value_ptr.*) orelse {
                c.Py_DecRef(pk);
                continue;
            };
            _ = c.PyDict_SetItem(py_path_params, pk, pv);
            c.Py_DecRef(pk);
            c.Py_DecRef(pv);
        }
    }
    _ = c.PyDict_SetItemString(kwargs, "path_params", py_path_params);

    // Call handler
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

    // Extract status_code
    var status_code: u16 = 200;
    if (c.PyDict_GetItemString(result, "status_code")) |sc| {
        const code = c.PyLong_AsLong(sc);
        if (code >= 100 and code <= 599) {
            status_code = @intCast(code);
        }
    }

    // Content — read pre-serialized string directly
    var body_slice: []const u8 = "null";
    if (c.PyDict_GetItemString(result, "content")) |content_obj| {
        if (c.PyUnicode_Check(content_obj) != 0) {
            if (c.PyUnicode_AsUTF8(content_obj)) |cs| {
                body_slice = std.mem.span(cs);
            }
        }
    }

    sendResponse(stream, status_code, "application/json", body_slice);
}

// ── Python handler dispatch (full kwargs — enhanced/model handlers) ──────────

fn callPythonHandler(entry: HandlerEntry, method: []const u8, path: []const u8, query_string: []const u8, body: []const u8, headers: []const HeaderPair, params: *const std.StringHashMap([]const u8)) PythonResponse {
    const err_body = "{\"error\": \"Internal Server Error\"}";
    const err_ct = "application/json";

    const state = c.PyGILState_Ensure();
    defer c.PyGILState_Release(state);

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
        var pit = params.iterator();
        while (pit.next()) |pe| {
            const pk = py.newString(pe.key_ptr.*) orelse continue;
            const pv = py.newString(pe.value_ptr.*) orelse {
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

fn sendResponse(stream: std.net.Stream, status: u16, content_type: []const u8, body: []const u8) void {
    const status_text = switch (status) {
        200 => "OK",
        201 => "Created",
        204 => "No Content",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        405 => "Method Not Allowed",
        422 => "Unprocessable Entity",
        429 => "Too Many Requests",
        500 => "Internal Server Error",
        502 => "Bad Gateway",
        503 => "Service Unavailable",
        else => "Unknown",
    };

    var header_buf: [512]u8 = undefined;
    const header = std.fmt.bufPrint(&header_buf, "HTTP/1.1 {d} {s}\r\nContent-Type: {s}\r\nContent-Length: {d}\r\nConnection: keep-alive\r\n\r\n", .{ status, status_text, content_type, body.len }) catch return;

    stream.writeAll(header) catch |err| {
        std.debug.print("[ZIG] write header error: {}\n", .{err});
        return;
    };
    stream.writeAll(body) catch |err| {
        std.debug.print("[ZIG] write body error: {}\n", .{err});
        return;
    };
    // std.debug.print("[ZIG] response sent ({d} bytes)\n", .{header.len + body.len});
}

// ── configure_rate_limiting(enabled, requests_per_minute) ──

pub fn configure_rate_limiting(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    // No-op for now – will implement later
    return py.pyNone();
}
