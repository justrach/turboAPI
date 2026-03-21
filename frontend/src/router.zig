// router.zig — file-based router with hash-map exact matching.
// app/index.zig    → "/"
// app/about.zig    → "/about"
// app/users/[id].zig → "/users/:id"  (dynamic segment)

const std = @import("std");
const mer = @import("mer");

pub const RenderFn = *const fn (req: mer.Request) mer.Response;
pub const StreamRenderFn = *const fn (req: mer.Request, stream: *mer.StreamWriter) void;
pub const LayoutFn = *const fn (std.mem.Allocator, []const u8, []const u8, mer.Meta) []const u8;

pub const StreamParts = mer.StreamParts;
pub const StreamLayoutFn = *const fn (std.mem.Allocator, []const u8, mer.Meta) StreamParts;

pub const Route = struct {
    path: []const u8,
    render: RenderFn,
    render_stream: ?StreamRenderFn = null,
    meta: mer.Meta = .{},
    prerender: bool = false,
};

pub const Router = struct {
    routes: []const Route,
    allocator: std.mem.Allocator,
    not_found: ?RenderFn = null,
    layout: ?LayoutFn = null,
    stream_layout: ?StreamLayoutFn = null,
    /// Hash map for O(1) exact route lookups.
    exact_map: std.StringHashMapUnmanaged(usize) = .{},
    /// Subset of routes containing dynamic segments (`:param`).
    dynamic_routes: []const Route = &.{},

    pub fn init(allocator: std.mem.Allocator, routes: []const Route) Router {
        var router = Router{ .allocator = allocator, .routes = routes };

        // Build exact match hash map + dynamic route list.
        var dynamic_list: std.ArrayListUnmanaged(Route) = .{};
        for (routes, 0..) |route, i| {
            if (std.mem.indexOfScalar(u8, route.path, ':') != null) {
                dynamic_list.append(allocator, route) catch {};
            } else {
                router.exact_map.put(allocator, route.path, i) catch {};
            }
        }
        router.dynamic_routes = dynamic_list.toOwnedSlice(allocator) catch &.{};

        return router;
    }

    pub fn deinit(self: *Router) void {
        self.exact_map.deinit(self.allocator);
        self.allocator.free(self.dynamic_routes);
    }

    /// Find a route by path (exact or dynamic match). Returns null if not found.
    pub fn findRoute(self: Router, path_arg: []const u8) ?Route {
        if (self.exact_map.get(path_arg)) |idx| return self.routes[idx];
        var params_buf: [8]mer.Param = undefined;
        for (self.dynamic_routes) |route| {
            if (matchRoute(route.path, path_arg, &params_buf) != null) return route;
        }
        // Trailing slash fallback.
        if (path_arg.len > 1 and path_arg[path_arg.len - 1] == '/') {
            const trimmed = path_arg[0 .. path_arg.len - 1];
            if (self.exact_map.get(trimmed)) |idx| return self.routes[idx];
            for (self.dynamic_routes) |route| {
                if (matchRoute(route.path, trimmed, &params_buf) != null) return route;
            }
        }
        return null;
    }
};

/// Try to match `req_path` against `route_path` where `:name` segments are wildcards.
pub fn matchRoute(route_path: []const u8, req_path: []const u8, out: []mer.Param) ?usize {
    var ri = std.mem.splitScalar(u8, route_path, '/');
    var pi = std.mem.splitScalar(u8, req_path, '/');
    var n: usize = 0;

    while (true) {
        const rs = ri.next();
        const ps = pi.next();
        if (rs == null and ps == null) return n;
        if (rs == null or ps == null) return null;
        const r_seg = rs.?;
        const p_seg = ps.?;
        if (r_seg.len > 0 and r_seg[0] == ':') {
            if (p_seg.len == 0) return null;
            if (n >= out.len) return null;
            out[n] = .{ .key = r_seg[1..], .value = p_seg };
            n += 1;
        } else {
            if (!std.mem.eql(u8, r_seg, p_seg)) return null;
        }
    }
}
