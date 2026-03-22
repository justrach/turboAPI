// Python C extension for SigV4 acceleration.
// Exposes: derive_signing_key, sign_string, sha256_hex, sign

const std = @import("std");
const sigv4 = @import("sigv4.zig");

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

fn pyNone() ?*c.PyObject {
    return @constCast(@ptrCast(c.Py_None));
}

// _sigv4_accel.derive_signing_key(secret_key, datestamp, region, service) -> bytes
fn py_derive_signing_key(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var sk: [*c]const u8 = null;
    var ds: [*c]const u8 = null;
    var rg: [*c]const u8 = null;
    var sv: [*c]const u8 = null;
    if (c.PyArg_ParseTuple(args, "ssss", &sk, &ds, &rg, &sv) == 0) return null;

    const key = sigv4.deriveSigningKey(
        std.mem.span(sk),
        std.mem.span(ds),
        std.mem.span(rg),
        std.mem.span(sv),
    );

    return c.PyBytes_FromStringAndSize(@ptrCast(&key), 32);
}

// _sigv4_accel.sign_string(signing_key_bytes, string_to_sign) -> str (hex)
fn py_sign_string(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var key_ptr: [*c]const u8 = null;
    var key_len: c.Py_ssize_t = 0;
    var sts: [*c]const u8 = null;
    if (c.PyArg_ParseTuple(args, "y#s", &key_ptr, &key_len, &sts) == 0) return null;

    if (key_len != 32) {
        c.PyErr_SetString(c.PyExc_ValueError, "signing key must be 32 bytes");
        return null;
    }

    const key: *const [32]u8 = @ptrCast(key_ptr);
    const hex = sigv4.signString(key, std.mem.span(sts));

    return c.PyUnicode_FromStringAndSize(@ptrCast(&hex), 64);
}

// _sigv4_accel.sha256_hex(data) -> str (hex)
fn py_sha256_hex(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var data_ptr: [*c]const u8 = null;
    var data_len: c.Py_ssize_t = 0;
    if (c.PyArg_ParseTuple(args, "y#", &data_ptr, &data_len) == 0) return null;

    const data = data_ptr[0..@intCast(data_len)];
    const hex = sigv4.sha256Hex(data);

    return c.PyUnicode_FromStringAndSize(@ptrCast(&hex), 64);
}

// _sigv4_accel.sign(secret_key, datestamp, region, service, string_to_sign) -> str (hex)
fn py_sign(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var sk: [*c]const u8 = null;
    var ds: [*c]const u8 = null;
    var rg: [*c]const u8 = null;
    var sv: [*c]const u8 = null;
    var sts: [*c]const u8 = null;
    if (c.PyArg_ParseTuple(args, "sssss", &sk, &ds, &rg, &sv, &sts) == 0) return null;

    const hex = sigv4.sign(
        std.mem.span(sk),
        std.mem.span(ds),
        std.mem.span(rg),
        std.mem.span(sv),
        std.mem.span(sts),
    );

    return c.PyUnicode_FromStringAndSize(@ptrCast(&hex), 64);
}

var methods = [_]c.PyMethodDef{
    .{ .ml_name = "derive_signing_key", .ml_meth = @ptrCast(&py_derive_signing_key), .ml_flags = c.METH_VARARGS, .ml_doc = "Derive SigV4 signing key (4x HMAC-SHA256)" },
    .{ .ml_name = "sign_string", .ml_meth = @ptrCast(&py_sign_string), .ml_flags = c.METH_VARARGS, .ml_doc = "Sign a string with signing key -> hex" },
    .{ .ml_name = "sha256_hex", .ml_meth = @ptrCast(&py_sha256_hex), .ml_flags = c.METH_VARARGS, .ml_doc = "SHA256 hash -> hex" },
    .{ .ml_name = "sign", .ml_meth = @ptrCast(&py_sign), .ml_flags = c.METH_VARARGS, .ml_doc = "Full SigV4 sign in one call" },
    .{ .ml_name = null, .ml_meth = null, .ml_flags = 0, .ml_doc = null },
};

var module_def = c.PyModuleDef{
    .m_base = module_base,
    .m_name = "_sigv4_accel",
    .m_doc = "Zig-accelerated SigV4 signing for faster-boto3",
    .m_size = -1,
    .m_methods = &methods,
    .m_slots = null,
    .m_traverse = null,
    .m_clear = null,
    .m_free = null,
};

pub export fn PyInit__sigv4_accel() ?*c.PyObject {
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
