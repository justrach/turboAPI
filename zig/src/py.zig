// Thin wrappers around the Python C-API, imported via @cImport.
// Everything the rest of the Zig codebase needs goes through here.

pub const c = @cImport({
    @cDefine("PY_SSIZE_T_CLEAN", {});
    @cInclude("Python.h");
});

// Re-export the types we use everywhere
pub const PyObject = c.PyObject;
pub const PyMethodDef = c.PyMethodDef;
pub const PyModuleDef = c.PyModuleDef;
pub const PyModuleDef_Base = c.PyModuleDef_Base;
pub const Py_ssize_t = c.Py_ssize_t;

// ── Constants ──
pub const METH_VARARGS = c.METH_VARARGS;
pub const METH_KEYWORDS = c.METH_VARARGS | c.METH_KEYWORDS;
pub const METH_NOARGS = c.METH_NOARGS;

// ── Helpers ──

pub fn incref(obj: *PyObject) *PyObject {
    c.Py_IncRef(obj);
    return obj;
}

pub fn decref(obj: *PyObject) void {
    c.Py_DecRef(obj);
}

pub fn none() *PyObject {
    return incref(@as(*PyObject, @ptrCast(c._Py_NoneStruct[0..])));
}

pub fn pyNone() *PyObject {
    return incref(&c._Py_NoneStruct);
}

pub fn pyTrue() *PyObject {
    return incref(@ptrCast(&c._Py_TrueStruct));
}

pub fn pyFalse() *PyObject {
    return incref(@ptrCast(&c._Py_FalseStruct));
}

pub fn isNone(obj: *PyObject) bool {
    return obj == @as(*PyObject, @ptrCast(&c._Py_NoneStruct));
}

pub fn setError(comptime fmt: []const u8, args: anytype) void {
    var buf: [1024]u8 = undefined;
    const msg = std.fmt.bufPrint(&buf, fmt, args) catch "internal error";
    const z: [*c]const u8 = @ptrCast(msg.ptr);
    c.PyErr_SetString(c.PyExc_RuntimeError, z);
}

pub fn newString(s: []const u8) ?*PyObject {
    return c.PyUnicode_FromStringAndSize(@ptrCast(s.ptr), @intCast(s.len));
}

pub fn newBytes(data: []const u8) ?*PyObject {
    return c.PyBytes_FromStringAndSize(@ptrCast(data.ptr), @intCast(data.len));
}

pub fn newInt(val: i64) ?*PyObject {
    return c.PyLong_FromLongLong(val);
}

pub fn newDict() ?*PyObject {
    return c.PyDict_New();
}

pub fn dictSetItemString(dict: *PyObject, key: [*:0]const u8, val: *PyObject) bool {
    return c.PyDict_SetItemString(dict, key, val) == 0;
}

pub fn newList(size: usize) ?*PyObject {
    return c.PyList_New(@intCast(size));
}

pub fn createModule(def: *PyModuleDef) ?*PyObject {
    return c.PyModule_Create(def);
}

pub fn moduleAddObject(module: *PyObject, name: [*:0]const u8, obj: *PyObject) bool {
    return c.PyModule_AddObject(module, name, obj) == 0;
}

pub fn parseArgs(args: ?*PyObject, fmt: [*:0]const u8, ptrs: anytype) bool {
    return @call(.auto, c.PyArg_ParseTuple, .{ args, fmt } ++ ptrs) != 0;
}

const std = @import("std");

// GIL management — PyEval_SaveThread/RestoreThread return/take PyThreadState*
// which Zig's @cImport can't translate. We declare them manually.
pub extern fn PyEval_SaveThread() ?*anyopaque;
pub extern fn PyEval_RestoreThread(state: ?*anyopaque) void;

// Per-worker thread state — cheaper than PyGILState_Ensure/Release on every call.
// Create one PyThreadState per OS thread at startup; reuse for every request.
pub extern fn PyEval_AcquireThread(tstate: ?*anyopaque) void;
pub extern fn PyEval_ReleaseThread(tstate: ?*anyopaque) void;
pub extern fn PyThreadState_New(interp: ?*anyopaque) ?*anyopaque;
pub extern fn PyThreadState_Clear(tstate: ?*anyopaque) void;
pub extern fn PyThreadState_DeleteCurrent() void;
pub extern fn PyInterpreterState_Get() ?*anyopaque;

// Fast call API — avoids arg tuple/dict construction for simple cases.
pub extern fn PyObject_CallNoArgs(callable: *c.PyObject) ?*c.PyObject;
pub extern fn PyObject_Vectorcall(
    callable: *c.PyObject,
    args: [*]const ?*c.PyObject,
    nargsf: usize,
    kwnames: ?*c.PyObject,
) ?*c.PyObject;

// Tuple access — used to unpack (status, content_type, body) response tuples.
pub extern fn PyTuple_GetItem(op: *c.PyObject, i: c.Py_ssize_t) ?*c.PyObject;
