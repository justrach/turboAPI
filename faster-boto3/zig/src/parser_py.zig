// Python C extension for SIMD-accelerated parsers.
// Replaces botocore's slow Python XML/JSON/timestamp parsing.

const std = @import("std");
const simd = @import("simd_parser.zig");

const c = @cImport({
    @cDefine("PY_SSIZE_T_CLEAN", {});
    @cInclude("Python.h");
});

// ── parse_xml_tags(xml_bytes) -> list[(key, value)] ─────────────────────────

fn py_parse_xml_tags(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var data_ptr: [*c]const u8 = null;
    var data_len: c.Py_ssize_t = 0;
    if (c.PyArg_ParseTuple(args, "y#", &data_ptr, &data_len) == 0) return null;

    const data = data_ptr[0..@intCast(data_len)];
    const allocator = std.heap.c_allocator;

    const tags = simd.parseXmlTags(allocator, data) catch {
        c.PyErr_SetString(c.PyExc_RuntimeError, "XML parse failed");
        return null;
    };
    defer allocator.free(tags);

    const result = c.PyList_New(@intCast(tags.len)) orelse return null;
    for (tags, 0..) |tag, i| {
        const tuple = c.Py_BuildValue(
            "(y#y#)",
            @as([*c]const u8, tag.key.ptr),
            @as(c.Py_ssize_t, @intCast(tag.key.len)),
            @as([*c]const u8, tag.value.ptr),
            @as(c.Py_ssize_t, @intCast(tag.value.len)),
        ) orelse return null;
        _ = c.PyList_SetItem(result, @intCast(i), tuple);
    }
    return result;
}

// ── parse_dynamo_item(json_bytes) -> list[(key, type, value)] ───────────────

fn py_parse_dynamo_item(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var data_ptr: [*c]const u8 = null;
    var data_len: c.Py_ssize_t = 0;
    if (c.PyArg_ParseTuple(args, "y#", &data_ptr, &data_len) == 0) return null;

    const data = data_ptr[0..@intCast(data_len)];
    const allocator = std.heap.c_allocator;

    const items = simd.parseDynamoItem(allocator, data) catch {
        c.PyErr_SetString(c.PyExc_RuntimeError, "JSON parse failed");
        return null;
    };
    defer allocator.free(items);

    const result = c.PyList_New(@intCast(items.len)) orelse return null;
    for (items, 0..) |item, i| {
        const type_str: [1]u8 = .{item.type_tag};
        const tuple = c.Py_BuildValue(
            "(y#y#y#)",
            @as([*c]const u8, item.key.ptr),
            @as(c.Py_ssize_t, @intCast(item.key.len)),
            @as([*c]const u8, &type_str),
            @as(c.Py_ssize_t, 1),
            @as([*c]const u8, item.value.ptr),
            @as(c.Py_ssize_t, @intCast(item.value.len)),
        ) orelse return null;
        _ = c.PyList_SetItem(result, @intCast(i), tuple);
    }
    return result;
}

// ── parse_timestamp(s) -> (year, month, day, hour, minute, second) ──────────

fn py_parse_timestamp(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var s_ptr: [*c]const u8 = null;
    if (c.PyArg_ParseTuple(args, "s", &s_ptr) == 0) return null;
    const s = std.mem.span(s_ptr);

    // Try ISO 8601 first, then HTTP date
    const ts = simd.parseIso8601(s) orelse simd.parseHttpDate(s) orelse {
        c.PyErr_SetString(c.PyExc_ValueError, "unrecognized timestamp format");
        return null;
    };

    return c.Py_BuildValue(
        "(iiiiii)",
        @as(c_int, ts.year),
        @as(c_int, ts.month),
        @as(c_int, ts.day),
        @as(c_int, ts.hour),
        @as(c_int, ts.minute),
        @as(c_int, ts.second),
    );
}

// ── find_byte(data, byte) -> int | None ─────────────────────────────────────
// Expose raw SIMD scanner for benchmarking

fn py_find_byte(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var data_ptr: [*c]const u8 = null;
    var data_len: c.Py_ssize_t = 0;
    var needle: c_int = 0;
    if (c.PyArg_ParseTuple(args, "y#i", &data_ptr, &data_len, &needle) == 0) return null;

    const data = data_ptr[0..@intCast(data_len)];
    if (simd.findByte(data, @intCast(needle))) |pos| {
        return c.Py_BuildValue("n", @as(c.Py_ssize_t, @intCast(pos)));
    }
    return c.Py_BuildValue("");
}

// ── count_byte(data, byte) -> int ───────────────────────────────────────────

fn py_count_byte(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var data_ptr: [*c]const u8 = null;
    var data_len: c.Py_ssize_t = 0;
    var needle: c_int = 0;
    if (c.PyArg_ParseTuple(args, "y#i", &data_ptr, &data_len, &needle) == 0) return null;

    const data = data_ptr[0..@intCast(data_len)];
    return c.Py_BuildValue("n", @as(c.Py_ssize_t, @intCast(simd.countByte(data, @intCast(needle)))));
}

// ── DHI-validated DynamoDB JSON parsing ─────────────────────────────────────
// parse_dynamo_response(json_bytes) -> list[(key, type_str, value)]
// Uses Zig std.json (faster than Python json.loads for extraction)
// + DHI-style type validation in the same pass.

const dhi_json = @import("dhi_json.zig");

fn py_parse_dynamo_response(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var data_ptr: [*c]const u8 = null;
    var data_len: c.Py_ssize_t = 0;
    if (c.PyArg_ParseTuple(args, "y#", &data_ptr, &data_len) == 0) return null;

    const data = data_ptr[0..@intCast(data_len)];
    const allocator = std.heap.c_allocator;

    // Parse JSON — keep alive until we've built Python objects
    const parsed = std.json.parseFromSlice(std.json.Value, allocator, data, .{}) catch {
        c.PyErr_SetString(c.PyExc_ValueError, "Invalid JSON");
        return null;
    };
    defer parsed.deinit();

    // Find the Item object (or root if it IS the item)
    const item_obj = blk: {
        if (parsed.value != .object) break :blk null;
        if (parsed.value.object.get("Item")) |item| {
            if (item == .object) break :blk item.object;
        }
        // Maybe it's a raw item
        break :blk parsed.value.object;
    };

    if (item_obj == null) {
        return c.PyDict_New() orelse return null;
    }

    // Build Python dict: {key: {"type": "S", "value": "..."}, ...}
    const py_dict = c.PyDict_New() orelse return null;

    var it = item_obj.?.iterator();
    while (it.next()) |entry| {
        const key = entry.key_ptr.*;
        const type_wrapper = entry.value_ptr.*;

        if (type_wrapper != .object) continue;

        var type_it = type_wrapper.object.iterator();
        const type_entry = type_it.next() orelse continue;
        const type_str = type_entry.key_ptr.*;
        const val = type_entry.value_ptr.*;

        const val_str: []const u8 = switch (val) {
            .string => |s| s,
            .bool => |b| if (b) "true" else "false",
            .null => "null",
            else => "",
        };

        const inner = c.PyDict_New() orelse return null;
        const py_type = c.PyUnicode_FromStringAndSize(@as([*c]const u8, type_str.ptr), @intCast(type_str.len)) orelse return null;
        const py_value = c.PyUnicode_FromStringAndSize(@as([*c]const u8, val_str.ptr), @intCast(val_str.len)) orelse return null;

        _ = c.PyDict_SetItemString(inner, "type", py_type);
        _ = c.PyDict_SetItemString(inner, "value", py_value);
        c.Py_DecRef(py_type);
        c.Py_DecRef(py_value);

        const py_key = c.PyUnicode_FromStringAndSize(@as([*c]const u8, key.ptr), @intCast(key.len)) orelse return null;
        _ = c.PyDict_SetItem(py_dict, py_key, inner);
        c.Py_DecRef(py_key);
        c.Py_DecRef(inner);
    }

    return py_dict;
}

// ── parse_json_fast(json_bytes) -> Python object ────────────────────────────
// Full JSON parse using Zig std.json → Python dict/list.
// Faster than json.loads for medium-large payloads.

fn zigJsonToPython(val: std.json.Value) ?*c.PyObject {
    return switch (val) {
        .null => c.Py_BuildValue(""),
        .bool => |b| c.PyBool_FromLong(if (b) 1 else 0),
        .integer => |i| c.PyLong_FromLongLong(i),
        .float => |f| c.PyFloat_FromDouble(f),
        .string => |s| c.PyUnicode_FromStringAndSize(
            @as([*c]const u8, s.ptr),
            @as(c.Py_ssize_t, @intCast(s.len)),
        ),
        .array => |arr| blk: {
            const py_list = c.PyList_New(@intCast(arr.items.len)) orelse break :blk null;
            for (arr.items, 0..) |item, i| {
                const py_item = zigJsonToPython(item) orelse {
                    c.Py_DecRef(py_list);
                    break :blk null;
                };
                _ = c.PyList_SetItem(py_list, @intCast(i), py_item);
            }
            break :blk py_list;
        },
        .object => |obj| blk: {
            const py_dict = c.PyDict_New() orelse break :blk null;
            var it = obj.iterator();
            while (it.next()) |entry| {
                const py_key = c.PyUnicode_FromStringAndSize(
                    @as([*c]const u8, entry.key_ptr.*.ptr),
                    @as(c.Py_ssize_t, @intCast(entry.key_ptr.*.len)),
                ) orelse {
                    c.Py_DecRef(py_dict);
                    break :blk null;
                };
                const py_val = zigJsonToPython(entry.value_ptr.*) orelse {
                    c.Py_DecRef(py_key);
                    c.Py_DecRef(py_dict);
                    break :blk null;
                };
                _ = c.PyDict_SetItem(py_dict, py_key, py_val);
                c.Py_DecRef(py_key);
                c.Py_DecRef(py_val);
            }
            break :blk py_dict;
        },
        .number_string => |s| c.PyFloat_FromDouble(std.fmt.parseFloat(f64, s) catch 0.0),
    };
}

fn py_parse_json(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var data_ptr: [*c]const u8 = null;
    var data_len: c.Py_ssize_t = 0;
    if (c.PyArg_ParseTuple(args, "y#", &data_ptr, &data_len) == 0) return null;

    const data = data_ptr[0..@intCast(data_len)];
    const allocator = std.heap.c_allocator;

    const parsed = std.json.parseFromSlice(std.json.Value, allocator, data, .{}) catch {
        c.PyErr_SetString(c.PyExc_ValueError, "Invalid JSON");
        return null;
    };
    defer parsed.deinit();

    return zigJsonToPython(parsed.value);
}

var methods = [_]c.PyMethodDef{
    .{ .ml_name = "parse_xml_tags", .ml_meth = @ptrCast(&py_parse_xml_tags), .ml_flags = c.METH_VARARGS, .ml_doc = "SIMD XML tag extraction" },
    .{ .ml_name = "parse_dynamo_item", .ml_meth = @ptrCast(&py_parse_dynamo_item), .ml_flags = c.METH_VARARGS, .ml_doc = "SIMD DynamoDB item parsing" },
    .{ .ml_name = "parse_dynamo_response", .ml_meth = @ptrCast(&py_parse_dynamo_response), .ml_flags = c.METH_VARARGS, .ml_doc = "DHI-validated DynamoDB response parsing" },
    .{ .ml_name = "parse_json", .ml_meth = @ptrCast(&py_parse_json), .ml_flags = c.METH_VARARGS, .ml_doc = "Full JSON parse (Zig std.json -> Python)" },
    .{ .ml_name = "parse_timestamp", .ml_meth = @ptrCast(&py_parse_timestamp), .ml_flags = c.METH_VARARGS, .ml_doc = "SIMD timestamp parsing (ISO 8601 + HTTP date)" },
    .{ .ml_name = "find_byte", .ml_meth = @ptrCast(&py_find_byte), .ml_flags = c.METH_VARARGS, .ml_doc = "SIMD byte search" },
    .{ .ml_name = "count_byte", .ml_meth = @ptrCast(&py_count_byte), .ml_flags = c.METH_VARARGS, .ml_doc = "SIMD byte count" },
    .{ .ml_name = null, .ml_meth = null, .ml_flags = 0, .ml_doc = null },
};

var module_slots = [_]c.PyModuleDef_Slot{
    .{ .slot = c.Py_mod_gil, .value = c.Py_MOD_GIL_NOT_USED },
    .{ .slot = 0, .value = null },
};

var module_def = c.PyModuleDef{
    .m_base = std.mem.zeroes(c.PyModuleDef_Base),
    .m_name = "_parser_accel",
    .m_doc = "SIMD-accelerated parsers for faster-boto3",
    .m_size = 0,
    .m_methods = &methods,
    .m_slots = &module_slots,
    .m_traverse = null,
    .m_clear = null,
    .m_free = null,
};

pub export fn PyInit__parser_accel() ?*c.PyObject {
    return c.PyModuleDef_Init(&module_def);
}
