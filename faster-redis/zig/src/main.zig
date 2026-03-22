// Python C extension for faster-redis.
// The ENTIRE hot path runs in Zig: pack → TCP send → TCP recv → parse → return.
// Python only calls execute() with args, gets back a Python value.

const std = @import("std");
const net = std.net;
const resp = @import("resp.zig");
const Allocator = std.mem.Allocator;

const c = @cImport({ @cDefine("PY_SSIZE_T_CLEAN", {}); @cInclude("Python.h"); });

// ── Persistent Zig TCP connection ───────────────────────────────────────────

var zig_stream: ?net.Stream = null;
var conn_lock: std.Thread.Mutex = .{};
var read_buf: [65536]u8 = undefined;
var read_pos: usize = 0;
var read_len: usize = 0;

fn ensureConnected(host: []const u8, port: u16) !void {
    if (zig_stream != null) return;
    const addr = try net.Address.resolveIp(host, port);
    zig_stream = try net.tcpConnectToAddress(addr);
    // TCP_NODELAY
    if (zig_stream) |s| {
        std.posix.setsockopt(s.handle, std.posix.IPPROTO.TCP, std.posix.TCP.NODELAY, &std.mem.toBytes(@as(c_int, 1))) catch {};
    }
    read_pos = 0;
    read_len = 0;
}

fn zigSend(data: []const u8) !void {
    const s = zig_stream orelse return error.NotConnected;
    var sent: usize = 0;
    while (sent < data.len) {
        sent += s.write(data[sent..]) catch return error.BrokenPipe;
    }
}

fn zigRecvResponse(allocator: Allocator) !resp.RespValue {
    const s = zig_stream orelse return error.NotConnected;
    while (true) {
        if (read_len > read_pos) {
            const buf = read_buf[read_pos..read_len];
            if (resp.parse(allocator, buf)) |result| {
                read_pos += result.consumed;
                if (read_pos > read_buf.len / 2) {
                    const rem = read_len - read_pos;
                    if (rem > 0) std.mem.copyForwards(u8, &read_buf, read_buf[read_pos..read_len]);
                    read_len = rem;
                    read_pos = 0;
                }
                return result.value;
            } else |err| {
                if (err != resp.ParseError.Incomplete) return err;
            }
        }
        if (read_len >= read_buf.len) {
            const rem = read_len - read_pos;
            if (rem > 0) std.mem.copyForwards(u8, &read_buf, read_buf[read_pos..read_len]);
            read_len = rem;
            read_pos = 0;
        }
        const n = s.read(read_buf[read_len..]) catch return error.BrokenPipe;
        if (n == 0) return error.EndOfStream;
        read_len += n;
    }
}

// ── Python API ──────────────────────────────────────────────────────────────

// connect(host, port)
fn py_connect(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var host_ptr: [*c]const u8 = null;
    var port: c_int = 6379;
    if (c.PyArg_ParseTuple(args, "si", &host_ptr, &port) == 0) return null;

    conn_lock.lock();
    defer conn_lock.unlock();

    if (zig_stream) |s| { s.close(); zig_stream = null; }
    ensureConnected(std.mem.span(host_ptr), @intCast(port)) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "failed to connect");
        return null;
    };
    return c.Py_BuildValue("");
}

// execute(args_list) -> value — THE HOT PATH. One call does everything in Zig.
fn py_execute(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var list_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "O", &list_obj) == 0) return null;
    const py_list = list_obj orelse return null;
    const n: usize = @intCast(c.PyList_Size(py_list));
    if (n == 0) return c.Py_BuildValue("");
    const allocator = std.heap.c_allocator;

    // Extract string args from Python list
    const cmd_args = allocator.alloc([]const u8, n) catch return null;
    defer allocator.free(cmd_args);
    for (0..n) |i| {
        const item = c.PyList_GetItem(py_list, @intCast(i)) orelse return null;
        var len: c.Py_ssize_t = 0;
        const ptr = c.PyUnicode_AsUTF8AndSize(item, &len) orelse return null;
        cmd_args[i] = ptr[0..@intCast(len)];
    }

    conn_lock.lock();
    defer conn_lock.unlock();

    // Pack command in Zig
    const cmd_buf = resp.packCommand(allocator, cmd_args) catch {
        c.PyErr_SetString(c.PyExc_MemoryError, "pack failed");
        return null;
    };
    defer allocator.free(cmd_buf);

    // Send via Zig TCP
    zigSend(cmd_buf) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "send failed");
        return null;
    };

    // Recv + parse via Zig
    const val = zigRecvResponse(allocator) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "recv/parse failed");
        return null;
    };

    return respToPy(val);
}

// execute_pipeline(list_of_arg_lists) -> list of values — batch in one Zig call
fn py_execute_pipeline(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var list_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "O", &list_obj) == 0) return null;
    const py_list = list_obj orelse return null;
    const num_cmds: usize = @intCast(c.PyList_Size(py_list));
    const allocator = std.heap.c_allocator;

    // Pack ALL commands into one buffer
    var total_buf: std.ArrayList(u8) = .empty;
    defer total_buf.deinit(allocator);

    for (0..num_cmds) |ci| {
        const cmd_list = c.PyList_GetItem(py_list, @intCast(ci)) orelse return null;
        const nargs: usize = @intCast(c.PyList_Size(cmd_list));
        const cmd_args = allocator.alloc([]const u8, nargs) catch return null;
        defer allocator.free(cmd_args);
        for (0..nargs) |i| {
            const item = c.PyList_GetItem(cmd_list, @intCast(i)) orelse return null;
            var len: c.Py_ssize_t = 0;
            const ptr = c.PyUnicode_AsUTF8AndSize(item, &len) orelse return null;
            cmd_args[i] = ptr[0..@intCast(len)];
        }
        const cmd_packed = resp.packCommand(allocator, cmd_args) catch return null;
        defer allocator.free(cmd_packed);
        total_buf.appendSlice(allocator, cmd_packed) catch return null;
    }

    conn_lock.lock();
    defer conn_lock.unlock();

    // One TCP send for all commands
    zigSend(total_buf.items) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "pipeline send failed");
        return null;
    };

    // Read all responses
    const py_result = c.PyList_New(@intCast(num_cmds)) orelse return null;
    for (0..num_cmds) |i| {
        const val = zigRecvResponse(allocator) catch {
            c.PyErr_SetString(c.PyExc_ConnectionError, "pipeline recv failed");
            return null;
        };
        const py_val = respToPy(val) orelse return null;
        _ = c.PyList_SetItem(py_result, @intCast(i), py_val);
    }
    return py_result;
}

// close()
fn py_close(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    conn_lock.lock();
    defer conn_lock.unlock();
    if (zig_stream) |s| { s.close(); zig_stream = null; }
    read_pos = 0;
    read_len = 0;
    return c.Py_BuildValue("");
}

// parse_resp + pack_command kept for benchmarking
fn py_parse_resp(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var data_ptr: [*c]const u8 = null;
    var data_len: c.Py_ssize_t = 0;
    if (c.PyArg_ParseTuple(args, "y#", &data_ptr, &data_len) == 0) return null;
    const result = resp.parse(std.heap.c_allocator, data_ptr[0..@intCast(data_len)]) catch {
        c.PyErr_SetString(c.PyExc_ValueError, "RESP parse error");
        return null;
    };
    return respToPy(result.value);
}

fn py_pack_command(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var list_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "O", &list_obj) == 0) return null;
    const py_list = list_obj orelse return null;
    const n: usize = @intCast(c.PyList_Size(py_list));
    const allocator = std.heap.c_allocator;
    const cmd_args = allocator.alloc([]const u8, n) catch return null;
    defer allocator.free(cmd_args);
    for (0..n) |i| {
        const item = c.PyList_GetItem(py_list, @intCast(i)) orelse return null;
        var len: c.Py_ssize_t = 0;
        const ptr = c.PyUnicode_AsUTF8AndSize(item, &len) orelse return null;
        cmd_args[i] = ptr[0..@intCast(len)];
    }
    const buf = resp.packCommand(allocator, cmd_args) catch return null;
    defer allocator.free(buf);
    return c.PyBytes_FromStringAndSize(@ptrCast(buf.ptr), @intCast(buf.len));
}

// ── RespValue -> PyObject ───────────────────────────────────────────────────

fn respToPy(val: resp.RespValue) ?*c.PyObject {
    return switch (val.type) {
        .simple_string, .bulk_string => c.PyUnicode_FromStringAndSize(@ptrCast(val.str_val.ptr), @intCast(val.str_val.len)),
        .error_string => c.PyUnicode_FromStringAndSize(@ptrCast(val.str_val.ptr), @intCast(val.str_val.len)),
        .integer => c.PyLong_FromLongLong(val.int_val),
        .boolean => c.PyBool_FromLong(if (val.bool_val) 1 else 0),
        .null_value => c.Py_BuildValue(""),
        .array => blk: {
            const py_list = c.PyList_New(@intCast(val.array_val.len)) orelse break :blk null;
            for (val.array_val, 0..) |item, i| {
                const py_item = respToPy(item) orelse break :blk null;
                _ = c.PyList_SetItem(py_list, @intCast(i), py_item);
            }
            break :blk py_list;
        },
    };
}

// ── Module ──────────────────────────────────────────────────────────────────

var methods = [_]c.PyMethodDef{
    .{ .ml_name = "connect", .ml_meth = @ptrCast(&py_connect), .ml_flags = c.METH_VARARGS, .ml_doc = "Connect to Redis (Zig TCP)" },
    .{ .ml_name = "execute", .ml_meth = @ptrCast(&py_execute), .ml_flags = c.METH_VARARGS, .ml_doc = "Execute command (full Zig hot path)" },
    .{ .ml_name = "execute_pipeline", .ml_meth = @ptrCast(&py_execute_pipeline), .ml_flags = c.METH_VARARGS, .ml_doc = "Pipeline execute (one TCP write, N reads)" },
    .{ .ml_name = "close", .ml_meth = @ptrCast(&py_close), .ml_flags = c.METH_NOARGS, .ml_doc = "Close connection" },
    .{ .ml_name = "parse_resp", .ml_meth = @ptrCast(&py_parse_resp), .ml_flags = c.METH_VARARGS, .ml_doc = "Parse RESP bytes" },
    .{ .ml_name = "pack_command", .ml_meth = @ptrCast(&py_pack_command), .ml_flags = c.METH_VARARGS, .ml_doc = "Pack command to RESP" },
    .{ .ml_name = null, .ml_meth = null, .ml_flags = 0, .ml_doc = null },
};

var module_slots = [_]c.PyModuleDef_Slot{
    .{ .slot = c.Py_mod_gil, .value = c.Py_MOD_GIL_NOT_USED },
    .{ .slot = 0, .value = null },
};

var module_def = c.PyModuleDef{
    .m_base = std.mem.zeroes(c.PyModuleDef_Base),
    .m_name = "_redis_accel",
    .m_doc = "Zig Redis client - full hot path in native code",
    .m_size = 0,
    .m_methods = &methods,
    .m_slots = &module_slots,
    .m_traverse = null,
    .m_clear = null,
    .m_free = null,
};

pub export fn PyInit__redis_accel() ?*c.PyObject {
    return c.PyModuleDef_Init(&module_def);
}
