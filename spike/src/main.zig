// nanoapi runtime-layer integration spike.
//
// Boots a real HTTP server using nanoapi.server.serveGeneric with a custom
// Dispatcher — no `App`, no router, no typed routes, no OpenAPI. Just the
// runtime layer (HTTP/1.1 parser, kqueue/io_uring/threaded accept loop,
// response writer) driving a hand-rolled dispatcher.
//
// This is the same shape turboAPI's Python FFI dispatcher will take, minus
// the FFI itself. After this lands, the real port replaces SpikeContext
// below with a Python-interpreter pointer and a dispatch adapter that
// calls into the existing turboAPI handler tuple machinery.

const std = @import("std");
const nanoapi = @import("nanoapi");

const SpikeContext = struct {
    request_count: std.atomic.Value(u64) = .{ .raw = 0 },
};

fn dispatchHandle(ctx: *anyopaque, req: *nanoapi.request.Request) anyerror!nanoapi.response.Response {
    const self: *SpikeContext = @ptrCast(@alignCast(ctx));
    _ = self.request_count.fetchAdd(1, .monotonic);

    if (std.mem.eql(u8, req.path, "/")) {
        return nanoapi.PlainTextResponse.init(req.allocator, "ok\n", .{});
    }
    if (std.mem.eql(u8, req.path, "/hello")) {
        return nanoapi.PlainTextResponse.init(
            req.allocator,
            "hello from turboAPI driving nanoapi runtime\n",
            .{},
        );
    }
    if (std.mem.eql(u8, req.path, "/echo-method")) {
        const body = try std.fmt.allocPrint(req.allocator, "method={s}\n", .{req.method});
        return nanoapi.PlainTextResponse.init(req.allocator, body, .{});
    }
    return nanoapi.PlainTextResponse.init(req.allocator, "not found\n", .{
        .status_code = nanoapi.status.HTTP_404_NOT_FOUND,
    });
}

fn dispatchHasMiddleware(ctx: *anyopaque) bool {
    _ = ctx;
    return false;
}

pub fn main() !void {
    var gpa: std.heap.DebugAllocator(.{}) = .init;
    defer _ = gpa.deinit();
    const allocator = gpa.allocator();

    var spike_ctx: SpikeContext = .{};

    const dispatcher: nanoapi.server.Dispatcher = .{
        .ctx = @ptrCast(&spike_ctx),
        .handle = dispatchHandle,
        .has_middleware = dispatchHasMiddleware,
        .try_static_dispatch = null,
    };

    std.debug.print("[spike] serving on 127.0.0.1:8765 (no App, no router — runtime + custom dispatcher)\n", .{});
    try nanoapi.server.serveGeneric(dispatcher, allocator, .{
        .host = .{ 127, 0, 0, 1 },
        .port = 8765,
        .worker_threads = 1,
    });
}
