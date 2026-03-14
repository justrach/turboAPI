// TurboNet – Zig HTTP core for TurboAPI
// Zig HTTP core for TurboAPI — Python C extension module.

const std = @import("std");
pub const py = @import("py.zig");
const c = py.c;
const response = @import("response.zig");
const server = @import("server.zig");
pub const router = @import("router.zig");

// ── Method table ────────────────────────────────────────────────────────────

fn hello(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    return py.newString("turbonet-zig is alive!");
}

var methods = [_]py.PyMethodDef{
    // Smoke test
    .{ .ml_name = "hello", .ml_meth = @ptrCast(&hello), .ml_flags = c.METH_NOARGS, .ml_doc = "Smoke test" },

    // ResponseView functions
    .{ .ml_name = "_rv_new", .ml_meth = @ptrCast(&response.response_new), .ml_flags = c.METH_VARARGS, .ml_doc = null },
    .{ .ml_name = "_rv_set_header", .ml_meth = @ptrCast(&response.response_set_header), .ml_flags = c.METH_VARARGS, .ml_doc = null },
    .{ .ml_name = "_rv_get_header", .ml_meth = @ptrCast(&response.response_get_header), .ml_flags = c.METH_VARARGS, .ml_doc = null },
    .{ .ml_name = "_rv_set_body", .ml_meth = @ptrCast(&response.response_set_body), .ml_flags = c.METH_VARARGS, .ml_doc = null },
    .{ .ml_name = "_rv_set_body_bytes", .ml_meth = @ptrCast(&response.response_set_body_bytes), .ml_flags = c.METH_VARARGS, .ml_doc = null },
    .{ .ml_name = "_rv_json", .ml_meth = @ptrCast(&response.response_json), .ml_flags = c.METH_VARARGS, .ml_doc = null },
    .{ .ml_name = "_rv_text", .ml_meth = @ptrCast(&response.response_text), .ml_flags = c.METH_VARARGS, .ml_doc = null },

    // Server functions
    .{ .ml_name = "_server_new", .ml_meth = @ptrCast(&server.server_new), .ml_flags = c.METH_VARARGS, .ml_doc = null },
    .{ .ml_name = "_server_add_route", .ml_meth = @ptrCast(&server.server_add_route), .ml_flags = c.METH_VARARGS, .ml_doc = null },
    .{ .ml_name = "_server_add_route_fast", .ml_meth = @ptrCast(&server.server_add_route_fast), .ml_flags = c.METH_VARARGS, .ml_doc = null },
    .{ .ml_name = "_server_add_route_model", .ml_meth = @ptrCast(&server.server_add_route_model), .ml_flags = c.METH_VARARGS, .ml_doc = null },
    .{ .ml_name = "_server_add_route_async_fast", .ml_meth = @ptrCast(&server.server_add_route_async_fast), .ml_flags = c.METH_VARARGS, .ml_doc = null },
    .{ .ml_name = "_server_add_route_model_validated", .ml_meth = @ptrCast(&server.server_add_route_model_validated), .ml_flags = c.METH_VARARGS, .ml_doc = null },
    .{ .ml_name = "_server_add_native_route", .ml_meth = @ptrCast(&server.server_add_native_route), .ml_flags = c.METH_VARARGS, .ml_doc = null },
    .{ .ml_name = "_server_add_middleware", .ml_meth = @ptrCast(&server.server_add_middleware), .ml_flags = c.METH_VARARGS, .ml_doc = null },
    .{ .ml_name = "_server_run", .ml_meth = @ptrCast(&server.server_run), .ml_flags = c.METH_NOARGS, .ml_doc = null },
    .{ .ml_name = "configure_rate_limiting", .ml_meth = @ptrCast(&server.configure_rate_limiting), .ml_flags = c.METH_VARARGS, .ml_doc = null },

    // sentinel
    .{ .ml_name = null, .ml_meth = null, .ml_flags = 0, .ml_doc = null },
};

// ── Module definition ───────────────────────────────────────────────────────

var module_def = c.PyModuleDef{
    .m_base = std.mem.zeroes(c.PyModuleDef_Base),
    .m_name = "turbonet",
    .m_doc = "TurboNet – Zig HTTP core for TurboAPI",
    .m_size = -1,
    .m_methods = @ptrCast(&methods),
    .m_slots = null,
    .m_traverse = null,
    .m_clear = null,
    .m_free = null,
};

// Bootstrap code uses _m (the module object) directly, no re-import
const bootstrap_code: [*:0]const u8 =
    \\class ResponseView:
    \\    def __init__(self, status_code=None):
    \\        self._state = _m._rv_new(status_code if status_code is not None else 200)
    \\        self.status_code = status_code if status_code is not None else 200
    \\    def set_header(self, name, value):
    \\        _m._rv_set_header(self._state, name, value)
    \\    def get_header(self, name):
    \\        return _m._rv_get_header(self._state, name)
    \\    def set_body(self, body):
    \\        _m._rv_set_body(self._state, body)
    \\    def set_body_bytes(self, body):
    \\        _m._rv_set_body_bytes(self._state, body)
    \\    def get_body_str(self):
    \\        b = self._state.get('body', b'')
    \\        return b.decode('utf-8') if isinstance(b, bytes) else str(b)
    \\    def get_body_bytes(self):
    \\        return self._state.get('body', b'')
    \\    def json(self, data):
    \\        _m._rv_json(self._state, data)
    \\    def text(self, data):
    \\        _m._rv_text(self._state, data)
    \\
    \\class TurboServer:
    \\    def __init__(self, host=None, port=None):
    \\        args = []
    \\        if host is not None: args.append(host)
    \\        if port is not None: args.append(port)
    \\        self._state = _m._server_new(*args)
    \\    def add_route(self, method, path, handler):
    \\        _m._server_add_route(method, path, handler)
    \\    def add_route_fast(self, method, path, handler, handler_type, param_types_json, original_handler):
    \\        _m._server_add_route_fast(method, path, handler, handler_type, param_types_json, original_handler)
    \\    def add_route_model(self, method, path, handler, param_name, model_class, original_handler):
    \\        _m._server_add_route_model(method, path, handler, param_name, model_class, original_handler)
    \\    def add_route_model_validated(self, method, path, handler, param_name, model_class, original_handler, schema_json):
    \\        _m._server_add_route_model_validated(method, path, handler, param_name, model_class, original_handler, schema_json)
    \\    def add_route_async_fast(self, method, path, handler, handler_type, param_types_json, original_handler):
    \\        _m._server_add_route_async_fast(method, path, handler, handler_type, param_types_json, original_handler)
    \\    def add_native_route(self, method, path, lib_path, symbol_name):
    \\        _m._server_add_native_route(method, path, lib_path, symbol_name)
    \\    def add_middleware(self, middleware):
    \\        _m._server_add_middleware(middleware)
    \\    def run(self):
    \\        _m._server_run()
    \\
    \\class RequestContext:
    \\    def __init__(self):
    \\        self.method = ''
    \\        self.path = ''
    \\        self.headers = {}
    \\        self.metadata = {}
    \\
    \\class ResponseContext:
    \\    def __init__(self):
    \\        self.status_code = 200
    \\        self.headers = {}
    \\        self.metadata = {}
    \\        self.processing_time_ms = 0.0
    \\
    \\class MiddlewarePipeline:
    \\    def __init__(self):
    \\        self._middlewares = []
    \\    def add_middleware(self, mw):
    \\        self._middlewares.append(mw)
    \\
    \\class CorsMiddleware:
    \\    def __init__(self, origins, methods, headers, max_age):
    \\        self.origins = origins
    \\        self.methods = methods
    \\        self.headers = headers
    \\        self.max_age = max_age
    \\
    \\class RateLimitMiddleware:
    \\    def __init__(self, requests_per_minute):
    \\        self.requests_per_minute = requests_per_minute
    \\
    \\_m.ResponseView = ResponseView
    \\_m.TurboServer = TurboServer
    \\_m.RequestContext = RequestContext
    \\_m.ResponseContext = ResponseContext
    \\_m.MiddlewarePipeline = MiddlewarePipeline
    \\_m.CorsMiddleware = CorsMiddleware
    \\_m.RateLimitMiddleware = RateLimitMiddleware
;

export fn PyInit_turbonet() ?*c.PyObject {
    const m = c.PyModule_Create(&module_def) orelse return null;

    // Declare free-threading safety (Python 3.14t+)
    if (@hasDecl(c, "PyUnstable_Module_SetGIL")) {
        if (@hasDecl(c, "Py_MOD_GIL_NOT_USED")) {
            _ = c.PyUnstable_Module_SetGIL(m, c.Py_MOD_GIL_NOT_USED);
        }
    }

    // Execute bootstrap code to add wrapper classes
    const globals = c.PyDict_New() orelse return m;
    defer c.Py_DecRef(globals);

    _ = c.PyDict_SetItemString(globals, "_m", m);
    _ = c.PyDict_SetItemString(globals, "__builtins__", c.PyEval_GetBuiltins());

    const result = c.PyRun_String(bootstrap_code, c.Py_file_input, globals, globals);
    if (result) |r| {
        c.Py_DecRef(r);
    } else {
        c.PyErr_Print();
    }

    return m;
}

test "sanity" {
    var r = router.Router.init(std.testing.allocator);
    defer r.deinit();
}

test "router parameterized match" {
    var r = router.Router.init(std.testing.allocator);
    defer r.deinit();

    try r.addRoute("GET", "/users/{id}/posts/{post_id}", "GET /users/{id}/posts/{post_id}");

    var m = r.findRoute("GET", "/users/42/posts/7").?;
    defer m.deinit();

    try std.testing.expectEqualStrings("42", m.params.get("id").?);
    try std.testing.expectEqualStrings("7", m.params.get("post_id").?);
}
