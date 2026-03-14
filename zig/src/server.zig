// TurboServer – Zig HTTP server core.
// Placeholder that registers routes and runs an event loop.
// The actual HTTP serving uses Zig's std.net / std.http.

const std = @import("std");
const py = @import("py.zig");
const c = py.c;
const router_mod = @import("router.zig");

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

var routes: ?std.StringHashMap(HandlerEntry) = null;
var router: ?router_mod.Router = null;
var server_host: []const u8 = "127.0.0.1";
var server_port: u16 = 8000;

fn getRoutes() *std.StringHashMap(HandlerEntry) {
    if (routes == null) {
        routes = std.StringHashMap(HandlerEntry).init(allocator);
    }
    return &routes.?;
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

// ── add_route_async_fast(method, path, handler, handler_type, param_types_json, original) ──

pub fn server_add_route_async_fast(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    // Same signature as add_route_fast
    return server_add_route_fast(null, args);
}

// ── add_middleware(middleware_obj) – currently a no-op ──

pub fn server_add_middleware(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    return py.pyNone();
}

// ── run() – start the HTTP server ──

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

    std.debug.print("🚀 TurboNet-Zig server listening on {s}:{d}\n", .{ server_host, server_port });
    std.debug.print("🎯 Zig HTTP core active – zero overhead!\n", .{});

    // Release the GIL before entering the accept loop so spawned threads
    // can acquire it to call Python handlers.
    const save = py.PyEval_SaveThread();

    while (true) {
        const conn = tcp_server.accept() catch continue;
        const thread = std.Thread.spawn(.{}, handleConnection, .{conn.stream}) catch continue;
        thread.detach();
    }

    // Restore GIL (unreachable in practice, but correct)
    py.PyEval_RestoreThread(save);
    return py.pyNone();
}

fn handleConnection(stream: std.net.Stream) void {
    defer stream.close();

    var buf: [8192]u8 = undefined;
    const n = stream.read(&buf) catch |err| {
        std.debug.print("[ZIG] read error: {}\n", .{err});
        return;
    };
    if (n == 0) return;

    const request_data = buf[0..n];
    std.debug.print("[ZIG] received {d} bytes\n", .{n});

    // Parse the first line to get method + path
    const first_line_end = std.mem.indexOf(u8, request_data, "\r\n") orelse return;
    const first_line = request_data[0..first_line_end];

    // "GET /path HTTP/1.1"
    var parts = std.mem.splitScalar(u8, first_line, ' ');
    const method = parts.next() orelse return;
    const raw_path = parts.next() orelse return;

    std.debug.print("[ZIG] {s} {s}\n", .{ method, raw_path });

    // Split path from query string
    const q_idx = std.mem.indexOf(u8, raw_path, "?");
    const path = if (q_idx) |i| raw_path[0..i] else raw_path;
    const query_string = if (q_idx) |i| raw_path[i + 1 ..] else "";

    // Extract body (after \r\n\r\n)
    const header_end = std.mem.indexOf(u8, request_data, "\r\n\r\n");
    const body = if (header_end) |he| request_data[he + 4 .. n] else "";

    // Match route via radix trie
    const rt = getRouter();
    var match = rt.findRoute(method, path) orelse {
        std.debug.print("[ZIG] 404 for {s} {s}\n", .{ method, path });
        sendResponse(stream, 404, "application/json", "{\"error\": \"Not Found\"}");
        return;
    };
    defer match.deinit();

    const r = getRoutes();
    const entry = r.get(match.handler_key) orelse {
        std.debug.print("[ZIG] handler entry missing for key: {s}\n", .{match.handler_key});
        sendResponse(stream, 500, "application/json", "{\"error\": \"Internal Server Error\"}");
        return;
    };

    const response_body = callPythonHandler(entry, method, path, query_string, body, &match.params);
    std.debug.print("[ZIG] handler returned: {s}\n", .{response_body});
    sendResponse(stream, 200, "application/json", response_body);
}

fn callPythonHandler(entry: HandlerEntry, method: []const u8, path: []const u8, query_string: []const u8, body: []const u8, params: *const std.StringHashMap([]const u8)) []const u8 {

    // Use the enhanced handler (already wrapped by Python side)
    const handler = entry.handler;

    // Call Python with GIL
    const state = c.PyGILState_Ensure();
    defer c.PyGILState_Release(state);

    // Build request dict
    const req_dict = c.PyDict_New() orelse return "{\"error\": \"internal error\"}";
    defer c.Py_DecRef(req_dict);

    // Set method, path, body etc
    if (py.newString(path)) |p| {
        _ = c.PyDict_SetItemString(req_dict, "path", p);
        c.Py_DecRef(p);
    }
    if (py.newString(body)) |b| {
        _ = c.PyDict_SetItemString(req_dict, "body", b);
        c.Py_DecRef(b);
    }

    // Build path_params dict from extracted route parameters
    const py_path_params = c.PyDict_New() orelse return "{\"error\": \"internal error\"}";
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

    // Call handler(method, path, headers, body, query_string, path_params)
    const py_method = py.newString(method) orelse return "{\"error\": \"internal error\"}";
    defer c.Py_DecRef(py_method);
    const py_path = py.newString(path) orelse return "{\"error\": \"internal error\"}";
    defer c.Py_DecRef(py_path);
    const py_headers = c.PyDict_New() orelse return "{\"error\": \"internal error\"}";
    defer c.Py_DecRef(py_headers);
    const py_body = c.PyBytes_FromStringAndSize(@ptrCast(body.ptr), @intCast(body.len)) orelse return "{\"error\": \"internal error\"}";
    defer c.Py_DecRef(py_body);
    const py_qs = py.newString(query_string) orelse return "{\"error\": \"internal error\"}";
    defer c.Py_DecRef(py_qs);

    const call_args = c.PyTuple_Pack(6, py_method, py_path, py_headers, py_body, py_qs, py_path_params) orelse return "{\"error\": \"internal error\"}";
    defer c.Py_DecRef(call_args);

    const result = c.PyObject_CallObject(handler, call_args);
    if (result) |res| {
        defer c.Py_DecRef(res);
        // Try to serialize to JSON
        const json_mod = c.PyImport_ImportModule("json") orelse return "{\"error\": \"json import failed\"}";
        defer c.Py_DecRef(json_mod);
        const dumps = c.PyObject_GetAttrString(json_mod, "dumps") orelse return "{\"error\": \"json.dumps failed\"}";
        defer c.Py_DecRef(dumps);
        const dump_args = c.PyTuple_Pack(1, res) orelse return "{\"error\": \"pack failed\"}";
        defer c.Py_DecRef(dump_args);
        const json_result = c.PyObject_CallObject(dumps, dump_args);
        if (json_result) |jr| {
            defer c.Py_DecRef(jr);
            const cstr = c.PyUnicode_AsUTF8(jr);
            if (cstr) |cs| {
                // Copy to owned memory
                const s = std.mem.span(cs);
                const owned = allocator.alloc(u8, s.len) catch return "{\"error\": \"alloc failed\"}";
                @memcpy(owned, s);
                return owned;
            }
        }
    } else {
        c.PyErr_Print();
    }
    return "{\"error\": \"handler failed\"}";
}

fn sendResponse(stream: std.net.Stream, status: u16, content_type: []const u8, body: []const u8) void {
    const status_text = switch (status) {
        200 => "OK",
        404 => "Not Found",
        500 => "Internal Server Error",
        else => "Unknown",
    };

    var header_buf: [512]u8 = undefined;
    const header = std.fmt.bufPrint(&header_buf, "HTTP/1.1 {d} {s}\r\nContent-Type: {s}\r\nContent-Length: {d}\r\nConnection: close\r\n\r\n", .{ status, status_text, content_type, body.len }) catch return;

    stream.writeAll(header) catch |err| {
        std.debug.print("[ZIG] write header error: {}\n", .{err});
        return;
    };
    stream.writeAll(body) catch |err| {
        std.debug.print("[ZIG] write body error: {}\n", .{err});
        return;
    };
    std.debug.print("[ZIG] response sent ({d} bytes)\n", .{header.len + body.len});
}

// ── configure_rate_limiting(enabled, requests_per_minute) ──

pub fn configure_rate_limiting(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    // No-op for now – will implement later
    return py.pyNone();
}
