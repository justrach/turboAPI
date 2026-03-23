// Python C extension for faster-redis.
// The ENTIRE hot path runs in Zig: pack -> TCP send -> TCP recv -> parse -> return.
// Python holds a native connection handle per Redis instance.

const std = @import("std");
const net = std.net;
const resp = @import("resp.zig");
const Allocator = std.mem.Allocator;

const c = @cImport({
    @cDefine("PY_SSIZE_T_CLEAN", {});
    @cInclude("Python.h");
});

const capsule_name = "faster_redis.Connection";
const pool_capsule_name = "faster_redis.ConnectionPool";

const ConnectionState = struct {
    host: []u8,
    port: u16,
    stream: ?net.Stream = null,
    lock: std.Thread.Mutex = .{},
    read_buf: [65536]u8 = undefined,
    read_pos: usize = 0,
    read_len: usize = 0,
    write_buf: std.ArrayList(u8) = .empty,
};

const PoolState = struct {
    connections: []ConnectionState,
    next_index: std.atomic.Value(usize) = std.atomic.Value(usize).init(0),
};

fn closeStream(state: *ConnectionState) void {
    if (state.stream) |s| {
        s.close();
        state.stream = null;
    }
    state.read_pos = 0;
    state.read_len = 0;
}

fn deinitConnection(state: *ConnectionState) void {
    closeStream(state);
    state.write_buf.deinit(std.heap.c_allocator);
    std.heap.c_allocator.free(state.host);
}

fn destroyConnection(state: *ConnectionState) void {
    deinitConnection(state);
    std.heap.c_allocator.destroy(state);
}

fn destroyPool(pool: *PoolState) void {
    for (pool.connections) |*connection| {
        deinitConnection(connection);
    }
    std.heap.c_allocator.free(pool.connections);
    std.heap.c_allocator.destroy(pool);
}

fn capsuleDestructor(capsule: ?*c.PyObject) callconv(.c) void {
    const raw = c.PyCapsule_GetPointer(capsule, capsule_name) orelse {
        c.PyErr_Clear();
        return;
    };
    const state: *ConnectionState = @ptrCast(@alignCast(raw));
    destroyConnection(state);
}

fn poolCapsuleDestructor(capsule: ?*c.PyObject) callconv(.c) void {
    const raw = c.PyCapsule_GetPointer(capsule, pool_capsule_name) orelse {
        c.PyErr_Clear();
        return;
    };
    const pool: *PoolState = @ptrCast(@alignCast(raw));
    destroyPool(pool);
}

fn connectionFromCapsule(obj: ?*c.PyObject) ?*ConnectionState {
    const raw = c.PyCapsule_GetPointer(obj, capsule_name) orelse return null;
    return @ptrCast(@alignCast(raw));
}

fn poolFromCapsule(obj: ?*c.PyObject) ?*PoolState {
    const raw = c.PyCapsule_GetPointer(obj, pool_capsule_name) orelse return null;
    return @ptrCast(@alignCast(raw));
}

fn selectPoolConnection(pool: *PoolState) *ConnectionState {
    const idx = pool.next_index.fetchAdd(1, .monotonic);
    return &pool.connections[idx % pool.connections.len];
}

fn selectPoolConnectionForSlot(pool: *PoolState, slot: usize) *ConnectionState {
    return &pool.connections[slot % pool.connections.len];
}

fn initConnection(state: *ConnectionState, host: []const u8, port: u16) !void {
    state.* = .{
        .host = try std.heap.c_allocator.dupe(u8, host),
        .port = port,
    };
    errdefer std.heap.c_allocator.free(state.host);
    errdefer state.write_buf.deinit(std.heap.c_allocator);
    try state.write_buf.ensureTotalCapacity(std.heap.c_allocator, 4096);
    try ensureConnected(state);
}

fn ensureConnected(state: *ConnectionState) !void {
    if (state.stream != null) return;
    const addr = try net.Address.resolveIp(state.host, state.port);
    state.stream = try net.tcpConnectToAddress(addr);
    if (state.stream) |s| {
        std.posix.setsockopt(
            s.handle,
            std.posix.IPPROTO.TCP,
            std.posix.TCP.NODELAY,
            &std.mem.toBytes(@as(c_int, 1)),
        ) catch {};
    }
    state.read_pos = 0;
    state.read_len = 0;
}

fn zigSend(state: *ConnectionState, data: []const u8) !void {
    const s = state.stream orelse return error.NotConnected;
    var sent: usize = 0;
    while (sent < data.len) {
        sent += s.write(data[sent..]) catch return error.BrokenPipe;
    }
}

fn zigRecvResponse(state: *ConnectionState, allocator: Allocator) !resp.RespValue {
    const s = state.stream orelse return error.NotConnected;
    while (true) {
        if (state.read_len > state.read_pos) {
            const buf = state.read_buf[state.read_pos..state.read_len];
            if (resp.parse(allocator, buf)) |result| {
                state.read_pos += result.consumed;
                if (state.read_pos > state.read_buf.len / 2) {
                    const rem = state.read_len - state.read_pos;
                    if (rem > 0) {
                        std.mem.copyForwards(u8, &state.read_buf, state.read_buf[state.read_pos..state.read_len]);
                    }
                    state.read_len = rem;
                    state.read_pos = 0;
                }
                return result.value;
            } else |err| {
                if (err != resp.ParseError.Incomplete) return err;
            }
        }
        if (state.read_len >= state.read_buf.len) {
            const rem = state.read_len - state.read_pos;
            if (rem > 0) {
                std.mem.copyForwards(u8, &state.read_buf, state.read_buf[state.read_pos..state.read_len]);
            }
            state.read_len = rem;
            state.read_pos = 0;
        }
        const n = s.read(state.read_buf[state.read_len..]) catch return error.BrokenPipe;
        if (n == 0) return error.EndOfStream;
        state.read_len += n;
    }
}

fn freeRespValue(allocator: Allocator, val: resp.RespValue) void {
    switch (val.type) {
        .array => {
            for (val.array_val) |item| {
                freeRespValue(allocator, item);
            }
            allocator.free(val.array_val);
        },
        else => {},
    }
}

fn pyArgSlice(item: ?*c.PyObject) ?[]const u8 {
    const obj = item orelse return null;

    var ptr: [*c]u8 = null;
    var len: c.Py_ssize_t = 0;
    if (c.PyBytes_AsStringAndSize(obj, &ptr, &len) == 0) {
        return @as([*]const u8, @ptrCast(ptr))[0..@intCast(len)];
    }
    c.PyErr_Clear();

    const unicode_ptr = c.PyUnicode_AsUTF8AndSize(obj, &len) orelse return null;
    return unicode_ptr[0..@intCast(len)];
}

fn py_connect(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var host_ptr: [*c]const u8 = null;
    var port: c_int = 6379;
    if (c.PyArg_ParseTuple(args, "si", &host_ptr, &port) == 0) return null;

    const allocator = std.heap.c_allocator;
    const state = allocator.create(ConnectionState) catch {
        c.PyErr_SetString(c.PyExc_MemoryError, "failed to allocate connection state");
        return null;
    };
    errdefer allocator.destroy(state);

    initConnection(state, std.mem.span(host_ptr), @intCast(port)) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "failed to connect");
        return null;
    };

    return c.PyCapsule_New(state, capsule_name, @ptrCast(&capsuleDestructor));
}

fn py_connect_pool(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var host_ptr: [*c]const u8 = null;
    var port: c_int = 6379;
    var size: c_int = 4;
    if (c.PyArg_ParseTuple(args, "sii", &host_ptr, &port, &size) == 0) return null;
    if (size <= 0) {
        c.PyErr_SetString(c.PyExc_ValueError, "pool size must be positive");
        return null;
    }

    const allocator = std.heap.c_allocator;
    const pool = allocator.create(PoolState) catch {
        c.PyErr_SetString(c.PyExc_MemoryError, "failed to allocate pool state");
        return null;
    };
    errdefer allocator.destroy(pool);

    pool.connections = allocator.alloc(ConnectionState, @intCast(size)) catch {
        c.PyErr_SetString(c.PyExc_MemoryError, "failed to allocate pool connections");
        return null;
    };
    errdefer allocator.free(pool.connections);
    pool.next_index = std.atomic.Value(usize).init(0);

    for (pool.connections, 0..) |*connection, i| {
        initConnection(connection, std.mem.span(host_ptr), @intCast(port)) catch {
            for (pool.connections[0..i]) |*initialized| {
                deinitConnection(initialized);
            }
            c.PyErr_SetString(c.PyExc_ConnectionError, "failed to connect pool");
            return null;
        };
    }

    return c.PyCapsule_New(pool, pool_capsule_name, @ptrCast(&poolCapsuleDestructor));
}

fn py_execute(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var capsule_obj: ?*c.PyObject = null;
    var list_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "OO", &capsule_obj, &list_obj) == 0) return null;

    const state = connectionFromCapsule(capsule_obj) orelse return null;
    const py_list = list_obj orelse return null;
    const n: usize = @intCast(c.PyList_Size(py_list));
    if (n == 0) return c.Py_BuildValue("");
    const allocator = std.heap.c_allocator;

    const cmd_args = allocator.alloc([]const u8, n) catch return null;
    defer allocator.free(cmd_args);
    for (0..n) |i| {
        const item = c.PyList_GetItem(py_list, @intCast(i)) orelse return null;
        cmd_args[i] = pyArgSlice(item) orelse return null;
    }

    state.lock.lock();
    defer state.lock.unlock();

    ensureConnected(state) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "failed to connect");
        return null;
    };

    const cmd_buf = resp.packCommandInto(allocator, &state.write_buf, cmd_args) catch {
        c.PyErr_SetString(c.PyExc_MemoryError, "pack failed");
        return null;
    };

    zigSend(state, cmd_buf) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "send failed");
        return null;
    };

    const val = zigRecvResponse(state, allocator) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "recv/parse failed");
        return null;
    };
    defer freeRespValue(allocator, val);

    return respToPy(val);
}

fn py_execute_pooled(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var pool_obj: ?*c.PyObject = null;
    var list_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "OO", &pool_obj, &list_obj) == 0) return null;

    const pool = poolFromCapsule(pool_obj) orelse return null;
    const state = selectPoolConnection(pool);
    const py_list = list_obj orelse return null;
    const n: usize = @intCast(c.PyList_Size(py_list));
    if (n == 0) return c.Py_BuildValue("");
    const allocator = std.heap.c_allocator;

    const cmd_args = allocator.alloc([]const u8, n) catch return null;
    defer allocator.free(cmd_args);
    for (0..n) |i| {
        const item = c.PyList_GetItem(py_list, @intCast(i)) orelse return null;
        cmd_args[i] = pyArgSlice(item) orelse return null;
    }

    state.lock.lock();
    defer state.lock.unlock();

    ensureConnected(state) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "failed to connect");
        return null;
    };

    const cmd_buf = resp.packCommandInto(allocator, &state.write_buf, cmd_args) catch {
        c.PyErr_SetString(c.PyExc_MemoryError, "pack failed");
        return null;
    };

    zigSend(state, cmd_buf) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "send failed");
        return null;
    };

    const val = zigRecvResponse(state, allocator) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "recv/parse failed");
        return null;
    };
    defer freeRespValue(allocator, val);

    return respToPy(val);
}

fn py_execute_pooled_slot(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var pool_obj: ?*c.PyObject = null;
    var slot_value: c.Py_ssize_t = 0;
    var list_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "OnO", &pool_obj, &slot_value, &list_obj) == 0) return null;

    const pool = poolFromCapsule(pool_obj) orelse return null;
    const state = selectPoolConnectionForSlot(pool, @intCast(slot_value));
    const py_list = list_obj orelse return null;
    const n: usize = @intCast(c.PyList_Size(py_list));
    if (n == 0) return c.Py_BuildValue("");
    const allocator = std.heap.c_allocator;

    const cmd_args = allocator.alloc([]const u8, n) catch return null;
    defer allocator.free(cmd_args);
    for (0..n) |i| {
        const item = c.PyList_GetItem(py_list, @intCast(i)) orelse return null;
        cmd_args[i] = pyArgSlice(item) orelse return null;
    }

    state.lock.lock();
    defer state.lock.unlock();

    ensureConnected(state) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "failed to connect");
        return null;
    };

    const cmd_buf = resp.packCommandInto(allocator, &state.write_buf, cmd_args) catch {
        c.PyErr_SetString(c.PyExc_MemoryError, "pack failed");
        return null;
    };

    zigSend(state, cmd_buf) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "send failed");
        return null;
    };

    const val = zigRecvResponse(state, allocator) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "recv/parse failed");
        return null;
    };
    defer freeRespValue(allocator, val);

    return respToPy(val);
}

fn py_execute_pipeline(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var capsule_obj: ?*c.PyObject = null;
    var list_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "OO", &capsule_obj, &list_obj) == 0) return null;

    const state = connectionFromCapsule(capsule_obj) orelse return null;
    const py_list = list_obj orelse return null;
    const num_cmds: usize = @intCast(c.PyList_Size(py_list));
    const allocator = std.heap.c_allocator;

    state.lock.lock();
    defer state.lock.unlock();

    ensureConnected(state) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "failed to connect");
        return null;
    };

    const cmd_lists = allocator.alloc([]const []const u8, num_cmds) catch return null;
    defer allocator.free(cmd_lists);
    for (0..num_cmds) |ci| {
        const cmd_list = c.PyList_GetItem(py_list, @intCast(ci)) orelse return null;
        const nargs: usize = @intCast(c.PyList_Size(cmd_list));
        const cmd_args = allocator.alloc([]const u8, nargs) catch return null;
        errdefer allocator.free(cmd_args);
        for (0..nargs) |i| {
            const item = c.PyList_GetItem(cmd_list, @intCast(i)) orelse return null;
            cmd_args[i] = pyArgSlice(item) orelse return null;
        }
        cmd_lists[ci] = cmd_args;
    }
    defer {
        for (cmd_lists) |cmd_args| {
            allocator.free(cmd_args);
        }
    }

    const pipeline_buf = resp.packPipelineInto(allocator, &state.write_buf, cmd_lists) catch {
        c.PyErr_SetString(c.PyExc_MemoryError, "pipeline pack failed");
        return null;
    };

    zigSend(state, pipeline_buf) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "pipeline send failed");
        return null;
    };

    const py_result = c.PyList_New(@intCast(num_cmds)) orelse return null;
    for (0..num_cmds) |i| {
        const val = zigRecvResponse(state, allocator) catch {
            c.PyErr_SetString(c.PyExc_ConnectionError, "pipeline recv failed");
            return null;
        };
        defer freeRespValue(allocator, val);
        const py_val = respToPy(val) orelse return null;
        _ = c.PyList_SetItem(py_result, @intCast(i), py_val);
    }
    return py_result;
}

fn py_execute_pipeline_pooled(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var pool_obj: ?*c.PyObject = null;
    var list_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "OO", &pool_obj, &list_obj) == 0) return null;

    const pool = poolFromCapsule(pool_obj) orelse return null;
    const state = selectPoolConnection(pool);
    const py_list = list_obj orelse return null;
    const num_cmds: usize = @intCast(c.PyList_Size(py_list));
    const allocator = std.heap.c_allocator;

    const cmd_lists = allocator.alloc([]const []const u8, num_cmds) catch return null;
    defer allocator.free(cmd_lists);
    for (0..num_cmds) |ci| {
        const cmd_list = c.PyList_GetItem(py_list, @intCast(ci)) orelse return null;
        const nargs: usize = @intCast(c.PyList_Size(cmd_list));
        const cmd_args = allocator.alloc([]const u8, nargs) catch return null;
        errdefer allocator.free(cmd_args);
        for (0..nargs) |i| {
            const item = c.PyList_GetItem(cmd_list, @intCast(i)) orelse return null;
            cmd_args[i] = pyArgSlice(item) orelse return null;
        }
        cmd_lists[ci] = cmd_args;
    }
    defer {
        for (cmd_lists) |cmd_args| {
            allocator.free(cmd_args);
        }
    }

    state.lock.lock();
    defer state.lock.unlock();

    ensureConnected(state) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "failed to connect");
        return null;
    };

    const pipeline_buf = resp.packPipelineInto(allocator, &state.write_buf, cmd_lists) catch {
        c.PyErr_SetString(c.PyExc_MemoryError, "pipeline pack failed");
        return null;
    };

    zigSend(state, pipeline_buf) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "pipeline send failed");
        return null;
    };

    const py_result = c.PyList_New(@intCast(num_cmds)) orelse return null;
    for (0..num_cmds) |i| {
        const val = zigRecvResponse(state, allocator) catch {
            c.PyErr_SetString(c.PyExc_ConnectionError, "pipeline recv failed");
            return null;
        };
        defer freeRespValue(allocator, val);
        const py_val = respToPy(val) orelse return null;
        _ = c.PyList_SetItem(py_result, @intCast(i), py_val);
    }
    return py_result;
}

fn py_execute_pipeline_pooled_slot(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var pool_obj: ?*c.PyObject = null;
    var slot_value: c.Py_ssize_t = 0;
    var list_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "OnO", &pool_obj, &slot_value, &list_obj) == 0) return null;

    const pool = poolFromCapsule(pool_obj) orelse return null;
    const state = selectPoolConnectionForSlot(pool, @intCast(slot_value));
    const py_list = list_obj orelse return null;
    const num_cmds: usize = @intCast(c.PyList_Size(py_list));
    const allocator = std.heap.c_allocator;

    const cmd_lists = allocator.alloc([]const []const u8, num_cmds) catch return null;
    defer allocator.free(cmd_lists);
    for (0..num_cmds) |ci| {
        const cmd_list = c.PyList_GetItem(py_list, @intCast(ci)) orelse return null;
        const nargs: usize = @intCast(c.PyList_Size(cmd_list));
        const cmd_args = allocator.alloc([]const u8, nargs) catch return null;
        errdefer allocator.free(cmd_args);
        for (0..nargs) |i| {
            const item = c.PyList_GetItem(cmd_list, @intCast(i)) orelse return null;
            cmd_args[i] = pyArgSlice(item) orelse return null;
        }
        cmd_lists[ci] = cmd_args;
    }
    defer {
        for (cmd_lists) |cmd_args| {
            allocator.free(cmd_args);
        }
    }

    state.lock.lock();
    defer state.lock.unlock();

    ensureConnected(state) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "failed to connect");
        return null;
    };

    const pipeline_buf = resp.packPipelineInto(allocator, &state.write_buf, cmd_lists) catch {
        c.PyErr_SetString(c.PyExc_MemoryError, "pipeline pack failed");
        return null;
    };

    zigSend(state, pipeline_buf) catch {
        c.PyErr_SetString(c.PyExc_ConnectionError, "pipeline send failed");
        return null;
    };

    const py_result = c.PyList_New(@intCast(num_cmds)) orelse return null;
    for (0..num_cmds) |i| {
        const val = zigRecvResponse(state, allocator) catch {
            c.PyErr_SetString(c.PyExc_ConnectionError, "pipeline recv failed");
            return null;
        };
        defer freeRespValue(allocator, val);
        const py_val = respToPy(val) orelse return null;
        _ = c.PyList_SetItem(py_result, @intCast(i), py_val);
    }
    return py_result;
}

fn py_close(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var capsule_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "O", &capsule_obj) == 0) return null;

    const state = connectionFromCapsule(capsule_obj) orelse return null;
    state.lock.lock();
    defer state.lock.unlock();
    closeStream(state);
    return c.Py_BuildValue("");
}

fn py_close_pool(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var pool_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "O", &pool_obj) == 0) return null;

    const pool = poolFromCapsule(pool_obj) orelse return null;
    for (pool.connections) |*connection| {
        connection.lock.lock();
        closeStream(connection);
        connection.lock.unlock();
    }
    return c.Py_BuildValue("");
}

fn py_parse_resp(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var data_ptr: [*c]const u8 = null;
    var data_len: c.Py_ssize_t = 0;
    if (c.PyArg_ParseTuple(args, "y#", &data_ptr, &data_len) == 0) return null;
    const result = resp.parse(std.heap.c_allocator, data_ptr[0..@intCast(data_len)]) catch {
        c.PyErr_SetString(c.PyExc_ValueError, "RESP parse error");
        return null;
    };
    defer freeRespValue(std.heap.c_allocator, result.value);
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
        cmd_args[i] = pyArgSlice(item) orelse return null;
    }
    const buf = resp.packCommand(allocator, cmd_args) catch return null;
    defer allocator.free(buf);
    return c.PyBytes_FromStringAndSize(@ptrCast(buf.ptr), @intCast(buf.len));
}

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

var methods = [_]c.PyMethodDef{
    .{ .ml_name = "connect", .ml_meth = @ptrCast(&py_connect), .ml_flags = c.METH_VARARGS, .ml_doc = "Connect to Redis and return a native handle" },
    .{ .ml_name = "connect_pool", .ml_meth = @ptrCast(&py_connect_pool), .ml_flags = c.METH_VARARGS, .ml_doc = "Connect to Redis and return a native pool handle" },
    .{ .ml_name = "execute", .ml_meth = @ptrCast(&py_execute), .ml_flags = c.METH_VARARGS, .ml_doc = "Execute command on a native handle" },
    .{ .ml_name = "execute_pooled", .ml_meth = @ptrCast(&py_execute_pooled), .ml_flags = c.METH_VARARGS, .ml_doc = "Execute command on a native pool handle" },
    .{ .ml_name = "execute_pooled_slot", .ml_meth = @ptrCast(&py_execute_pooled_slot), .ml_flags = c.METH_VARARGS, .ml_doc = "Execute command on a specific native pool slot" },
    .{ .ml_name = "execute_pipeline", .ml_meth = @ptrCast(&py_execute_pipeline), .ml_flags = c.METH_VARARGS, .ml_doc = "Pipeline execute on a native handle" },
    .{ .ml_name = "execute_pipeline_pooled", .ml_meth = @ptrCast(&py_execute_pipeline_pooled), .ml_flags = c.METH_VARARGS, .ml_doc = "Pipeline execute on a native pool handle" },
    .{ .ml_name = "execute_pipeline_pooled_slot", .ml_meth = @ptrCast(&py_execute_pipeline_pooled_slot), .ml_flags = c.METH_VARARGS, .ml_doc = "Pipeline execute on a specific native pool slot" },
    .{ .ml_name = "close", .ml_meth = @ptrCast(&py_close), .ml_flags = c.METH_VARARGS, .ml_doc = "Close a native handle connection" },
    .{ .ml_name = "close_pool", .ml_meth = @ptrCast(&py_close_pool), .ml_flags = c.METH_VARARGS, .ml_doc = "Close a native pool handle" },
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
