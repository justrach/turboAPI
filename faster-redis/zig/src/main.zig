const std = @import("std");
const resp = @import("resp.zig");
const c = @cImport({ @cDefine("PY_SSIZE_T_CLEAN", {}); @cInclude("Python.h"); });

fn py_parse_resp(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var data_ptr: [*c]const u8 = null;
    var data_len: c.Py_ssize_t = 0;
    if (c.PyArg_ParseTuple(args, "y#", &data_ptr, &data_len) == 0) return null;
    const data = data_ptr[0..@intCast(data_len)];
    const result = resp.parse(std.heap.c_allocator, data) catch {
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
    .m_doc = "Zig RESP parser + command packer",
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
