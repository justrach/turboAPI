// Python C extension for Zig HTTP client.
// Exposes: request(method, url, headers_list, body) -> (status, headers_str, body_bytes)
//
// Uses nanobrew pattern: persistent std.http.Client for connection reuse.

const std = @import("std");
const http_client = @import("http_client.zig");
const http = std.http;

const c = @cImport({
    @cDefine("PY_SSIZE_T_CLEAN", {});
    @cDefine("Py_GIL_DISABLED", "1");
    @cInclude("Python.h");
});

const module_base = c.PyModuleDef_Base{
    .ob_base = .{
        .ob_tid = 0,
        .ob_flags = c._Py_STATICALLY_ALLOCATED_FLAG,
        .ob_mutex = std.mem.zeroes(c.PyMutex),
        .ob_gc_bits = 0,
        .ob_ref_local = c._Py_IMMORTAL_REFCNT_LOCAL,
        .ob_ref_shared = 0,
        .ob_type = null,
    },
    .m_init = null,
    .m_index = 0,
    .m_copy = null,
};

// ── Persistent client (connection pooling across calls) ─────────────────────

var persistent_client: ?http.Client = null;
var client_lock: std.Thread.Mutex = .{};

fn getClient() *http.Client {
    client_lock.lock();
    defer client_lock.unlock();
    if (persistent_client == null) {
        persistent_client = http.Client{ .allocator = std.heap.c_allocator };
    }
    return &persistent_client.?;
}

fn py_reset_client(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    client_lock.lock();
    defer client_lock.unlock();
    if (persistent_client) |*cl| {
        cl.deinit();
        persistent_client = null;
    }
    return c.Py_BuildValue("");
}

// ── Parse Python args into Zig types ────────────────────────────────────────

const ParsedArgs = struct {
    method: http.Method,
    url: []const u8,
    headers: std.ArrayList(http.Header),
    body: ?[]const u8,
    body_buffer: ?c.Py_buffer = null, // held open until request completes

    fn releaseBody(self: *ParsedArgs) void {
        if (self.body_buffer) |*buf| {
            c.PyBuffer_Release(buf);
            self.body_buffer = null;
        }
    }
};

fn parseArgs(args: ?*c.PyObject) ?ParsedArgs {
    var method_ptr: [*c]const u8 = null;
    var url_ptr: [*c]const u8 = null;
    var headers_obj: ?*c.PyObject = null;
    var body_obj: ?*c.PyObject = null;

    // Accept method, url, headers_list, body (any bytes-like or None)
    if (c.PyArg_ParseTuple(args, "ssOO", &method_ptr, &url_ptr, &headers_obj, &body_obj) == 0)
        return null;

    const method_str = std.mem.span(method_ptr);
    const method: http.Method = if (std.mem.eql(u8, method_str, "GET"))
        .GET
    else if (std.mem.eql(u8, method_str, "PUT"))
        .PUT
    else if (std.mem.eql(u8, method_str, "POST"))
        .POST
    else if (std.mem.eql(u8, method_str, "DELETE"))
        .DELETE
    else if (std.mem.eql(u8, method_str, "HEAD"))
        .HEAD
    else
        .GET;

    const allocator = std.heap.c_allocator;
    var headers: std.ArrayList(http.Header) = .empty;

    if (headers_obj) |hdr_list| {
        const n = c.PyList_Size(hdr_list);
        if (n < 0) return null;
        var i: c.Py_ssize_t = 0;
        while (i < n) : (i += 1) {
            const item = c.PyList_GetItem(hdr_list, i) orelse return null;
            var k_ptr: [*c]const u8 = null;
            var v_ptr: [*c]const u8 = null;
            if (c.PyArg_ParseTuple(item, "ss", &k_ptr, &v_ptr) == 0) return null;
            headers.append(allocator, .{ .name = std.mem.span(k_ptr), .value = std.mem.span(v_ptr) }) catch {
                c.PyErr_SetString(c.PyExc_MemoryError, "header alloc failed");
                return null;
            };
        }
    }

    // Zero-copy body via buffer protocol (bytes, bytearray, memoryview, mmap)
    var body: ?[]const u8 = null;
    var body_buffer: ?c.Py_buffer = null;
    if (body_obj) |obj| {
        // Check for None using Py_IsNone
        if (c.Py_IsNone(obj) == 0) {
            var buf: c.Py_buffer = std.mem.zeroes(c.Py_buffer);
            if (c.PyObject_GetBuffer(obj, &buf, c.PyBUF_SIMPLE) == 0) {
                if (buf.len > 0 and buf.buf != null) {
                    body = @as([*]const u8, @ptrCast(buf.buf))[0..@intCast(buf.len)];
                }
                // Keep buffer open — caller releases via releaseBody() after request
                body_buffer = buf;
            } else {
                // Not a buffer object — try PyBytes_AsStringAndSize fallback
                c.PyErr_Clear();
                var fallback_ptr: [*c]const u8 = null;
                var fallback_len: c.Py_ssize_t = 0;
                if (c.PyBytes_AsStringAndSize(obj, @ptrCast(&fallback_ptr), &fallback_len) == 0) {
                    if (fallback_len > 0 and fallback_ptr != null) {
                        body = fallback_ptr[0..@intCast(fallback_len)];
                    }
                } else {
                    c.PyErr_Clear();
                }
            }
        }
    }

    return .{
        .method = method,
        .url = std.mem.span(url_ptr),
        .headers = headers,
        .body = body,
        .body_buffer = body_buffer,
    };
}

// ── request() — uses persistent client for connection reuse ─────────────────

fn py_http_request(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var parsed = parseArgs(args) orelse return null;
    defer parsed.headers.deinit(std.heap.c_allocator);
    defer parsed.releaseBody();

    const client_ptr = getClient();

    var resp = http_client.doRequest(
        std.heap.c_allocator,
        client_ptr,
        parsed.method,
        parsed.url,
        parsed.headers.items,
        parsed.body,
    ) catch |err| {
        const msg = switch (err) {
            http_client.HttpError.ConnectionFailed => "connection failed",
            http_client.HttpError.RequestFailed => "request failed",
            http_client.HttpError.InvalidUrl => "invalid URL",
            http_client.HttpError.OutOfMemory => "out of memory",
            http_client.HttpError.ReadFailed => "read failed",
        };
        c.PyErr_SetString(c.PyExc_ConnectionError, msg);
        return null;
    };
    defer resp.deinit();

    return c.Py_BuildValue(
        "(iy#y#)",
        @as(c_int, @intCast(resp.status)),
        resp.headers_buf.ptr,
        @as(c.Py_ssize_t, @intCast(resp.headers_buf.len)),
        resp.body.ptr,
        @as(c.Py_ssize_t, @intCast(resp.body.len)),
    );
}

// ── request_oneshot() — fresh client per call (no connection reuse) ─────────

fn py_http_request_oneshot(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var parsed = parseArgs(args) orelse return null;
    defer parsed.headers.deinit(std.heap.c_allocator);
    defer parsed.releaseBody();

    const allocator = std.heap.c_allocator;
    var headers_pairs: std.ArrayList([2][]const u8) = .empty;
    defer headers_pairs.deinit(allocator);
    for (parsed.headers.items) |h| {
        headers_pairs.append(allocator, .{ h.name, h.value }) catch {
            c.PyErr_SetString(c.PyExc_MemoryError, "alloc failed");
            return null;
        };
    }

    var resp = http_client.request(allocator, @tagName(parsed.method), parsed.url, headers_pairs.items, parsed.body) catch |err| {
        const msg = switch (err) {
            http_client.HttpError.ConnectionFailed => "connection failed",
            http_client.HttpError.RequestFailed => "request failed",
            http_client.HttpError.InvalidUrl => "invalid URL",
            http_client.HttpError.OutOfMemory => "out of memory",
            http_client.HttpError.ReadFailed => "read failed",
        };
        c.PyErr_SetString(c.PyExc_ConnectionError, msg);
        return null;
    };
    defer resp.deinit();

    return c.Py_BuildValue(
        "(iy#y#)",
        @as(c_int, @intCast(resp.status)),
        resp.headers_buf.ptr,
        @as(c.Py_ssize_t, @intCast(resp.headers_buf.len)),
        resp.body.ptr,
        @as(c.Py_ssize_t, @intCast(resp.body.len)),
    );
}

// ── request_batch() — parallel Zig threads, one call from Python ────────────
// Input:  list of (method, url, headers_list, body)
// Output: list of (status, headers_str, body_bytes) or (0, b"", error_msg)

fn py_http_request_batch(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var list_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "O", &list_obj) == 0) return null;

    const py_list = list_obj orelse return null;
    const n_raw = c.PyList_Size(py_list);
    if (n_raw < 0) return null;
    const n: usize = @intCast(n_raw);

    const allocator = std.heap.c_allocator;

    // Parse all Python request tuples into Zig BatchRequest structs
    const batch_reqs = allocator.alloc(http_client.BatchRequest, n) catch {
        c.PyErr_SetString(c.PyExc_MemoryError, "batch alloc failed");
        return null;
    };
    defer allocator.free(batch_reqs);

    // Keep header lists alive until batch completes
    const header_lists = allocator.alloc(std.ArrayList(http.Header), n) catch {
        c.PyErr_SetString(c.PyExc_MemoryError, "batch alloc failed");
        return null;
    };
    defer {
        for (header_lists) |*hl| hl.deinit(allocator);
        allocator.free(header_lists);
    }

    for (0..n) |i| {
        const item = c.PyList_GetItem(py_list, @intCast(i)) orelse return null;

        var method_ptr: [*c]const u8 = null;
        var url_ptr: [*c]const u8 = null;
        var headers_obj: ?*c.PyObject = null;
        var body_ptr: [*c]const u8 = null;
        var body_len: c.Py_ssize_t = 0;

        if (c.PyArg_ParseTuple(item, "ssOz#", &method_ptr, &url_ptr, &headers_obj, &body_ptr, &body_len) == 0)
            return null;

        const method_str = std.mem.span(method_ptr);
        const method: http.Method = if (std.mem.eql(u8, method_str, "GET"))
            .GET
        else if (std.mem.eql(u8, method_str, "PUT"))
            .PUT
        else if (std.mem.eql(u8, method_str, "POST"))
            .POST
        else if (std.mem.eql(u8, method_str, "DELETE"))
            .DELETE
        else if (std.mem.eql(u8, method_str, "HEAD"))
            .HEAD
        else
            .GET;

        // Parse headers
        header_lists[i] = .empty;
        if (headers_obj) |hdr_list| {
            const hn = c.PyList_Size(hdr_list);
            if (hn >= 0) {
                var j: c.Py_ssize_t = 0;
                while (j < hn) : (j += 1) {
                    const hitem = c.PyList_GetItem(hdr_list, j) orelse return null;
                    var k_ptr: [*c]const u8 = null;
                    var v_ptr: [*c]const u8 = null;
                    if (c.PyArg_ParseTuple(hitem, "ss", &k_ptr, &v_ptr) == 0) return null;
                    header_lists[i].append(allocator, .{ .name = std.mem.span(k_ptr), .value = std.mem.span(v_ptr) }) catch {
                        c.PyErr_SetString(c.PyExc_MemoryError, "header alloc failed");
                        return null;
                    };
                }
            }
        }

        batch_reqs[i] = .{
            .method = method,
            .url = std.mem.span(url_ptr),
            .headers = header_lists[i].items,
            .body = if (body_ptr != null and body_len > 0) body_ptr[0..@intCast(body_len)] else null,
        };
    }

    // Execute batch in parallel Zig threads
    const results = http_client.requestBatch(allocator, batch_reqs) catch {
        c.PyErr_SetString(c.PyExc_RuntimeError, "batch execution failed");
        return null;
    };
    defer {
        for (results) |*r| {
            if (r.response) |*resp| resp.deinit();
        }
        allocator.free(results);
    }

    // Convert results to Python list of tuples
    const py_result = c.PyList_New(@intCast(n)) orelse return null;

    for (results, 0..) |*r, i| {
        const tuple = if (r.response) |resp|
            c.Py_BuildValue(
                "(iy#y#)",
                @as(c_int, @intCast(resp.status)),
                resp.headers_buf.ptr,
                @as(c.Py_ssize_t, @intCast(resp.headers_buf.len)),
                resp.body.ptr,
                @as(c.Py_ssize_t, @intCast(resp.body.len)),
            )
        else blk: {
            const err_msg = r.err_msg orelse "unknown error";
            break :blk c.Py_BuildValue(
                "(iy#y#)",
                @as(c_int, 0),
                @as([*c]const u8, ""),
                @as(c.Py_ssize_t, 0),
                @as([*c]const u8, err_msg.ptr),
                @as(c.Py_ssize_t, @intCast(err_msg.len)),
            );
        };

        if (tuple == null) return null;
        _ = c.PyList_SetItem(py_result, @intCast(i), tuple);
    }

    return py_result;
}
// ── request_fd() — upload body from file descriptor (zero Python copy) ───────

fn py_http_request_fd(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var method_ptr: [*c]const u8 = null;
    var url_ptr: [*c]const u8 = null;
    var headers_obj: ?*c.PyObject = null;
    var fd: c_int = -1;
    var offset: c_longlong = 0;
    var length: c_longlong = 0;

    if (c.PyArg_ParseTuple(args, "ssOiLL", &method_ptr, &url_ptr, &headers_obj, &fd, &offset, &length) == 0)
        return null;

    if (fd < 0 or length <= 0) {
        c.PyErr_SetString(c.PyExc_ValueError, "invalid fd or length");
        return null;
    }

    const allocator = std.heap.c_allocator;

    // Parse method
    const method_str = std.mem.span(method_ptr);
    const method: http.Method = if (std.mem.eql(u8, method_str, "PUT"))
        .PUT
    else if (std.mem.eql(u8, method_str, "POST"))
        .POST
    else
        .PUT;

    // Parse headers
    var headers: std.ArrayList(http.Header) = .empty;
    defer headers.deinit(allocator);
    if (headers_obj) |hdr_list| {
        const n = c.PyList_Size(hdr_list);
        if (n < 0) return null;
        var i: c.Py_ssize_t = 0;
        while (i < n) : (i += 1) {
            const item = c.PyList_GetItem(hdr_list, i) orelse return null;
            var k_ptr: [*c]const u8 = null;
            var v_ptr: [*c]const u8 = null;
            if (c.PyArg_ParseTuple(item, "ss", &k_ptr, &v_ptr) == 0) return null;
            headers.append(allocator, .{ .name = std.mem.span(k_ptr), .value = std.mem.span(v_ptr) }) catch {
                c.PyErr_SetString(c.PyExc_MemoryError, "header alloc failed");
                return null;
            };
        }
    }

    const file_fd: std.posix.fd_t = @intCast(fd);
    const off: u64 = @intCast(offset);
    const len: usize = @intCast(length);

    const client_ptr = getClient();

    var resp = http_client.doRequestFromFd(
        allocator,
        client_ptr,
        method,
        std.mem.span(url_ptr),
        headers.items,
        file_fd,
        off,
        len,
    ) catch |err| {
        const msg = switch (err) {
            http_client.HttpError.ConnectionFailed => "connection failed",
            http_client.HttpError.RequestFailed => "request failed",
            http_client.HttpError.InvalidUrl => "invalid URL",
            http_client.HttpError.OutOfMemory => "out of memory",
            http_client.HttpError.ReadFailed => "read failed",
        };
        c.PyErr_SetString(c.PyExc_ConnectionError, msg);
        return null;
    };
    defer resp.deinit();

    return c.Py_BuildValue(
        "(iy#y#)",
        @as(c_int, @intCast(resp.status)),
        resp.headers_buf.ptr,
        @as(c.Py_ssize_t, @intCast(resp.headers_buf.len)),
        resp.body.ptr,
        @as(c.Py_ssize_t, @intCast(resp.body.len)),
    );
}

var methods = [_]c.PyMethodDef{
    .{ .ml_name = "request", .ml_meth = @ptrCast(&py_http_request), .ml_flags = c.METH_VARARGS, .ml_doc = "HTTP request with connection pooling" },
    .{ .ml_name = "request_oneshot", .ml_meth = @ptrCast(&py_http_request_oneshot), .ml_flags = c.METH_VARARGS, .ml_doc = "HTTP request without connection reuse" },
    .{ .ml_name = "request_batch", .ml_meth = @ptrCast(&py_http_request_batch), .ml_flags = c.METH_VARARGS, .ml_doc = "Parallel batch HTTP requests via Zig threads" },
    .{ .ml_name = "request_fd", .ml_meth = @ptrCast(&py_http_request_fd), .ml_flags = c.METH_VARARGS, .ml_doc = "HTTP request with body from file descriptor (fd, offset, length)" },
    .{ .ml_name = "reset", .ml_meth = @ptrCast(&py_reset_client), .ml_flags = c.METH_NOARGS, .ml_doc = "Reset persistent HTTP client" },
    .{ .ml_name = null, .ml_meth = null, .ml_flags = 0, .ml_doc = null },
};
var module_def = c.PyModuleDef{
    .m_base = module_base,
    .m_name = "_http_accel",
    .m_doc = "Zig-accelerated HTTP client for faster-boto3 (nanobrew pattern)",
    .m_size = -1,
    .m_methods = &methods,
    .m_slots = null,
    .m_traverse = null,
    .m_clear = null,
    .m_free = null,
};

pub export fn PyInit__http_accel() ?*c.PyObject {
    const module = c.PyModule_Create(&module_def);
    if (module == null) return null;
    if (@hasDecl(c, "PyUnstable_Module_SetGIL")) {
        if (c.PyUnstable_Module_SetGIL(module, c.Py_MOD_GIL_USED) < 0) {
            c.Py_DecRef(module);
            return null;
        }
    }
    return module;
}
