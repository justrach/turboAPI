// dispatch.zig — request dispatch: route matching → render → layout wrapping.
// Extracted from router.zig so the Router struct stays focused on routing data
// structures (init/deinit/findRoute/matchRoute).

const std = @import("std");
const mer = @import("mer");
const Router = @import("router.zig").Router;
const Route = @import("router.zig").Route;
const matchRoute = @import("router.zig").matchRoute;

/// Match a URL path to a route and call its render function.
pub fn dispatch(router: Router, req: mer.Request) mer.Response {
    var meta: mer.Meta = .{};
    var params_buf: [8]mer.Param = undefined;

    var response: mer.Response = blk: {
        // 1. O(1) exact match via hash map.
        if (router.exact_map.get(req.path)) |idx| {
            meta = router.routes[idx].meta;
            break :blk router.routes[idx].render(req);
        }

        // 2. Dynamic pattern match (only routes with `:param` segments).
        for (router.dynamic_routes) |route| {
            if (matchRoute(route.path, req.path, &params_buf)) |n| {
                meta = route.meta;
                var dyn_req = req;
                dyn_req.params = req.allocator.dupe(mer.Param, params_buf[0..n]) catch &.{};
                break :blk route.render(dyn_req);
            }
        }

        // 3. Trailing-slash normalisation (except root).
        if (req.path.len > 1 and req.path[req.path.len - 1] == '/') {
            const trimmed = req.path[0 .. req.path.len - 1];
            if (router.exact_map.get(trimmed)) |idx| {
                meta = router.routes[idx].meta;
                break :blk router.routes[idx].render(req);
            }
            for (router.dynamic_routes) |route| {
                if (matchRoute(route.path, trimmed, &params_buf)) |n| {
                    meta = route.meta;
                    var dyn_req = req;
                    dyn_req.params = req.allocator.dupe(mer.Param, params_buf[0..n]) catch &.{};
                    break :blk route.render(dyn_req);
                }
            }
        }

        if (router.not_found) |nf| break :blk nf(req);
        break :blk mer.notFound();
    };

    // Auto-wrap HTML responses with layout (skip if response already has <!DOCTYPE).
    if (router.layout) |wrap| {
        if (response.content_type == .html and response.body.len > 0) {
            if (!std.mem.startsWith(u8, response.body, "<!")) {
                response.body = wrap(req.allocator, req.path, response.body, meta);
            }
        }
    }

    return response;
}

/// Result of a streaming dispatch — head/body/tail are separate for chunked flushing.
pub const StreamResult = struct {
    head: []const u8,
    body: []const u8,
    tail: []const u8,
    response: mer.Response,
    is_streaming: bool,
};

/// Dispatch with streaming layout support. If stream_layout is set and the
/// response is HTML, returns head/body/tail separately for chunked flushing.
/// Otherwise falls back to the normal assembled response.
pub fn dispatchStreaming(router: Router, req: mer.Request) StreamResult {
    var meta: mer.Meta = .{};
    var params_buf: [8]mer.Param = undefined;

    var response: mer.Response = blk: {
        if (router.exact_map.get(req.path)) |idx| {
            meta = router.routes[idx].meta;
            break :blk router.routes[idx].render(req);
        }
        for (router.dynamic_routes) |route| {
            if (matchRoute(route.path, req.path, &params_buf)) |n| {
                meta = route.meta;
                var dyn_req = req;
                dyn_req.params = req.allocator.dupe(mer.Param, params_buf[0..n]) catch &.{};
                break :blk route.render(dyn_req);
            }
        }
        if (req.path.len > 1 and req.path[req.path.len - 1] == '/') {
            const trimmed = req.path[0 .. req.path.len - 1];
            if (router.exact_map.get(trimmed)) |idx| {
                meta = router.routes[idx].meta;
                break :blk router.routes[idx].render(req);
            }
            for (router.dynamic_routes) |route| {
                if (matchRoute(route.path, trimmed, &params_buf)) |n| {
                    meta = route.meta;
                    var dyn_req = req;
                    dyn_req.params = req.allocator.dupe(mer.Param, params_buf[0..n]) catch &.{};
                    break :blk route.render(dyn_req);
                }
            }
        }
        if (router.not_found) |nf| break :blk nf(req);
        break :blk mer.notFound();
    };

    // Use streaming layout if available and response is an HTML fragment.
    if (router.stream_layout) |stream_wrap| {
        if (response.content_type == .html and response.body.len > 0) {
            if (!std.mem.startsWith(u8, response.body, "<!")) {
                const parts = stream_wrap(req.allocator, req.path, meta);
                return .{
                    .head = parts.head,
                    .body = response.body,
                    .tail = parts.tail,
                    .response = response,
                    .is_streaming = true,
                };
            }
        }
    }

    // Fallback: use regular layout wrapping.
    if (router.layout) |wrap| {
        if (response.content_type == .html and response.body.len > 0) {
            if (!std.mem.startsWith(u8, response.body, "<!")) {
                response.body = wrap(req.allocator, req.path, response.body, meta);
            }
        }
    }

    return .{ .head = "", .body = response.body, .tail = "", .response = response, .is_streaming = false };
}

/// Like dispatch() but calls renderStream (if present) with a buffering writer,
/// so pages that only export renderStream work on Cloudflare Workers.
pub fn dispatchBuffered(router: Router, req: mer.Request) mer.Response {
    var meta: mer.Meta = .{};
    var params_buf: [8]mer.Param = undefined;

    // Find the route.
    const route: ?Route = blk: {
        if (router.exact_map.get(req.path)) |idx| {
            meta = router.routes[idx].meta;
            break :blk router.routes[idx];
        }
        for (router.dynamic_routes) |r| {
            if (matchRoute(r.path, req.path, &params_buf)) |n| {
                meta = r.meta;
                var dyn_req = req;
                dyn_req.params = req.allocator.dupe(mer.Param, params_buf[0..n]) catch &.{};
                break :blk r;
            }
        }
        if (req.path.len > 1 and req.path[req.path.len - 1] == '/') {
            const trimmed = req.path[0 .. req.path.len - 1];
            if (router.exact_map.get(trimmed)) |idx| {
                meta = router.routes[idx].meta;
                break :blk router.routes[idx];
            }
        }
        break :blk null;
    };

    // If the route has renderStream, buffer it into a full response.
    if (route) |r| {
        if (r.render_stream) |rs| {
            var ctx = BufCtx{ .alloc = req.allocator };
            var stream = mer.StreamWriter{
                .allocator = req.allocator,
                .ctx = &ctx,
                .writeFn = bufWriteFn,
                .flushFn = bufFlushFn,
            };
            rs(req, &stream);
            const body = ctx.list.toOwnedSlice(req.allocator) catch "";

            // Wrap with stream layout (head + body + tail).
            if (router.stream_layout) |wrap| {
                const parts = wrap(req.allocator, req.path, meta);
                const full = std.mem.concat(req.allocator, u8, &.{ parts.head, body, parts.tail }) catch body;
                return .{ .status = .ok, .content_type = .html, .body = full };
            }
            if (router.layout) |wrap| {
                return .{ .status = .ok, .content_type = .html, .body = wrap(req.allocator, req.path, body, meta) };
            }
            return .{ .status = .ok, .content_type = .html, .body = body };
        }
    }

    // No renderStream — fall back to regular dispatch.
    return dispatch(router, req);
}

const BufCtx = struct {
    list: std.ArrayListUnmanaged(u8) = .{},
    alloc: std.mem.Allocator,
};

fn bufWriteFn(ctx: *anyopaque, data: []const u8) void {
    const bc: *BufCtx = @ptrCast(@alignCast(ctx));
    bc.list.appendSlice(bc.alloc, data) catch {};
}

fn bufFlushFn(ctx: *anyopaque) void {
    _ = ctx;
}
