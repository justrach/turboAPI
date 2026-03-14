// ResponseView – Zig-backed HTTP response builder.
// Instead of trying to replicate PyO3's class system via raw C-API (painful),
// we expose fast C functions that a Python wrapper class calls.

const std = @import("std");
const py = @import("py.zig");
const c = py.c;

// ── Module-level functions exposed to Python ────────────────────────────────

// All response state is held in a Python dict. The Python-side ResponseView
// class wraps these calls for an identical API to the Rust version.

pub fn response_new(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var status_code: c_long = 200;

    if (args) |a| {
        if (c.PyTuple_Size(a) > 0) {
            const first = c.PyTuple_GetItem(a, 0);
            if (first) |item| {
                if (c.PyLong_Check(item) != 0) {
                    status_code = c.PyLong_AsLong(item);
                }
            }
        }
    }

    // Return a dict: {status_code: int, headers: dict, body: bytes}
    const d = c.PyDict_New() orelse return null;

    const sc = c.PyLong_FromLong(status_code) orelse {
        c.Py_DecRef(d);
        return null;
    };
    _ = c.PyDict_SetItemString(d, "status_code", sc);
    c.Py_DecRef(sc);

    const headers = c.PyDict_New() orelse {
        c.Py_DecRef(d);
        return null;
    };
    _ = c.PyDict_SetItemString(d, "headers", headers);
    c.Py_DecRef(headers);

    const body = c.PyBytes_FromStringAndSize("", 0) orelse {
        c.Py_DecRef(d);
        return null;
    };
    _ = c.PyDict_SetItemString(d, "body", body);
    c.Py_DecRef(body);

    return d;
}

// set_header(state_dict, name, value)
pub fn response_set_header(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var state: ?*c.PyObject = null;
    var name: [*c]const u8 = null;
    var value: [*c]const u8 = null;
    if (c.PyArg_ParseTuple(args, "Oss", &state, &name, &value) == 0) return null;

    const headers = c.PyDict_GetItemString(state.?, "headers") orelse return py.pyNone();
    const val_obj = c.PyUnicode_FromString(value) orelse return null;
    _ = c.PyDict_SetItemString(headers, name, val_obj);
    c.Py_DecRef(val_obj);
    return py.pyNone();
}

// get_header(state_dict, name) -> str | None
pub fn response_get_header(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var state: ?*c.PyObject = null;
    var name: [*c]const u8 = null;
    if (c.PyArg_ParseTuple(args, "Os", &state, &name) == 0) return null;

    const headers = c.PyDict_GetItemString(state.?, "headers") orelse return py.pyNone();
    const val = c.PyDict_GetItemString(headers, name);
    if (val) |v| {
        c.Py_IncRef(v);
        return v;
    }
    return py.pyNone();
}

// set_body(state_dict, text_str)
pub fn response_set_body(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var state: ?*c.PyObject = null;
    var data: [*c]const u8 = null;
    if (c.PyArg_ParseTuple(args, "Os", &state, &data) == 0) return null;

    const body = c.PyBytes_FromString(data) orelse return null;
    _ = c.PyDict_SetItemString(state.?, "body", body);
    c.Py_DecRef(body);
    return py.pyNone();
}

// set_body_bytes(state_dict, bytes)
pub fn response_set_body_bytes(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var state: ?*c.PyObject = null;
    var buf: [*c]const u8 = null;
    var len: py.Py_ssize_t = 0;
    if (c.PyArg_ParseTuple(args, "Oy#", &state, &buf, &len) == 0) return null;

    const body = c.PyBytes_FromStringAndSize(buf, len) orelse return null;
    _ = c.PyDict_SetItemString(state.?, "body", body);
    c.Py_DecRef(body);
    return py.pyNone();
}

// json(state_dict, json_str)
pub fn response_json(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var state: ?*c.PyObject = null;
    var data: [*c]const u8 = null;
    if (c.PyArg_ParseTuple(args, "Os", &state, &data) == 0) return null;

    // Set content-type
    const headers = c.PyDict_GetItemString(state.?, "headers");
    if (headers) |h| {
        const ct = c.PyUnicode_FromString("application/json") orelse return null;
        _ = c.PyDict_SetItemString(h, "content-type", ct);
        c.Py_DecRef(ct);
    }
    // Set body
    const body = c.PyBytes_FromString(data) orelse return null;
    _ = c.PyDict_SetItemString(state.?, "body", body);
    c.Py_DecRef(body);
    return py.pyNone();
}

// text(state_dict, text_str)
pub fn response_text(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var state: ?*c.PyObject = null;
    var data: [*c]const u8 = null;
    if (c.PyArg_ParseTuple(args, "Os", &state, &data) == 0) return null;

    const headers = c.PyDict_GetItemString(state.?, "headers");
    if (headers) |h| {
        const ct = c.PyUnicode_FromString("text/plain; charset=utf-8") orelse return null;
        _ = c.PyDict_SetItemString(h, "content-type", ct);
        c.Py_DecRef(ct);
    }
    const body = c.PyBytes_FromString(data) orelse return null;
    _ = c.PyDict_SetItemString(state.?, "body", body);
    c.Py_DecRef(body);
    return py.pyNone();
}
