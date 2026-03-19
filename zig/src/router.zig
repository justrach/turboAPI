// Radix trie router with parameterized path matching.
// Supports static segments, parameterized segments ({id}), and wildcard (*path).

const std = @import("std");

const Allocator = std.mem.Allocator;

// ── Public types ────────────────────────────────────────────────────────────

pub const MAX_ROUTE_PARAMS = 8;

pub const RouteParam = struct {
    key: []const u8,
    value: []const u8,
};

/// Zero-alloc route params — fixed-size stack array instead of HashMap.
/// Supports up to MAX_ROUTE_PARAMS path parameters per route.
pub const RouteParams = struct {
    items_buf: [MAX_ROUTE_PARAMS]RouteParam = undefined,
    len: usize = 0,

    pub fn get(self: *const RouteParams, key: []const u8) ?[]const u8 {
        for (self.items_buf[0..self.len]) |p| {
            if (std.mem.eql(u8, p.key, key)) return p.value;
        }
        return null;
    }

    pub fn put(self: *RouteParams, key: []const u8, value: []const u8) void {
        if (self.len < MAX_ROUTE_PARAMS) {
            self.items_buf[self.len] = .{ .key = key, .value = value };
            self.len += 1;
        }
    }

    pub fn removeLast(self: *RouteParams) void {
        if (self.len > 0) self.len -= 1;
    }

    pub fn entries(self: *const RouteParams) []const RouteParam {
        return self.items_buf[0..self.len];
    }
};

pub const RouteMatch = struct {
    handler_key: []const u8,
    params: RouteParams = .{},
    /// Heap-allocated values that this match owns (e.g. joined wildcard paths)
    owned_values: std.ArrayListUnmanaged([]const u8) = .empty,
    alloc: Allocator,

    pub fn deinit(self: *RouteMatch) void {
        for (self.owned_values.items) |v| {
            self.alloc.free(v);
        }
        self.owned_values.deinit(self.alloc);
        // No HashMap to deinit — params are stack-allocated
    }
};

pub const Router = struct {
    root: *RouteNode,
    alloc: Allocator,

    pub fn init(alloc: Allocator) Router {
        const root = alloc.create(RouteNode) catch @panic("OOM");
        root.* = RouteNode.initEmpty(alloc);
        return .{ .root = root, .alloc = alloc };
    }

    pub fn deinit(self: *Router) void {
        self.root.deinit(self.alloc);
        self.alloc.destroy(self.root);
    }

    /// Add a route pattern. `handler_key` is stored as-is (e.g. "GET /users/{id}").
    /// `method` is the HTTP method (e.g. "GET"). Path must start with '/'.
    pub fn addRoute(self: *Router, method: []const u8, path: []const u8, handler_key: []const u8) !void {
        if (path.len == 0 or path[0] != '/') return error.InvalidPath;

        const segments = try parsePath(self.alloc, path);
        defer self.alloc.free(segments);

        try self.insertRoute(self.root, segments, method, handler_key);
    }

    /// Find the handler key and extract path parameters for the given path.
    pub fn findRoute(self: *const Router, method: []const u8, path: []const u8) ?RouteMatch {
        const trimmed = if (path.len > 0 and path[0] == '/') path[1..] else path;

        var segments_buf: [64][]const u8 = undefined;
        var seg_count: usize = 0;

        if (trimmed.len == 0) {
            // root path — zero segments
        } else {
            var it = std.mem.splitScalar(u8, trimmed, '/');
            while (it.next()) |seg| {
                if (seg_count >= segments_buf.len) return null;
                segments_buf[seg_count] = seg;
                seg_count += 1;
            }
        }
        const segments = segments_buf[0..seg_count];

        var params: RouteParams = .{};
        var owned: std.ArrayListUnmanaged([]const u8) = .empty;
        if (self.findHandler(self.root, segments, 0, method, &params, &owned)) |handler_key| {
            return RouteMatch{
                .handler_key = handler_key,
                .params = params,
                .owned_values = owned,
                .alloc = self.alloc,
            };
        }
        owned.deinit(self.alloc);
        return null;
    }

    // ── Internal ────────────────────────────────────────────────────────

    fn insertRoute(self: *Router, node: *RouteNode, segments: []const Segment, method: []const u8, handler_key: []const u8) !void {
        if (segments.len == 0) {
            const owned_method = try self.alloc.dupe(u8, method);
            const owned_key = try self.alloc.dupe(u8, handler_key);
            // If a handler for this method already exists, free the old one
            if (node.handlers.fetchRemove(owned_method)) |old| {
                self.alloc.free(old.key);
                self.alloc.free(old.value);
            }
            try node.handlers.put(owned_method, owned_key);
            return;
        }

        const seg = segments[0];
        const rest = segments[1..];

        switch (seg) {
            .static => |name| {
                if (node.children.getPtr(name)) |child_ptr| {
                    try self.insertRoute(child_ptr.*, rest, method, handler_key);
                } else {
                    const child = try self.alloc.create(RouteNode);
                    child.* = RouteNode.initEmpty(self.alloc);
                    const owned_name = try self.alloc.dupe(u8, name);
                    try node.children.put(owned_name, child);
                    try self.insertRoute(child, rest, method, handler_key);
                }
            },
            .param => |param_name| {
                if (node.param_child == null) {
                    const child = try self.alloc.create(RouteNode);
                    child.* = RouteNode.initEmpty(self.alloc);
                    child.param_name = try self.alloc.dupe(u8, param_name);
                    node.param_child = child;
                }
                try self.insertRoute(node.param_child.?, rest, method, handler_key);
            },
            .wildcard => |param_name| {
                const child = if (node.wildcard_child) |wc| wc else blk: {
                    const c = try self.alloc.create(RouteNode);
                    c.* = RouteNode.initEmpty(self.alloc);
                    c.param_name = try self.alloc.dupe(u8, param_name);
                    node.wildcard_child = c;
                    break :blk c;
                };
                const owned_method = try self.alloc.dupe(u8, method);
                const owned_key = try self.alloc.dupe(u8, handler_key);
                try child.handlers.put(owned_method, owned_key);
            },
        }
    }

    fn findHandler(
        self: *const Router,
        node: *const RouteNode,
        segments: []const []const u8,
        index: usize,
        method: []const u8,
        params: *RouteParams,
        owned: *std.ArrayListUnmanaged([]const u8),
    ) ?[]const u8 {
        if (index >= segments.len) {
            return node.handlers.get(method);
        }

        const segment = segments[index];

        // 1. Try static match first (highest priority)
        if (node.children.get(segment)) |child| {
            if (self.findHandler(child, segments, index + 1, method, params, owned)) |h| {
                return h;
            }
        }

        // 2. Try parameter match
        if (node.param_child) |param_child| {
            if (param_child.param_name) |pname| {
                params.put(pname, segment);
                if (self.findHandler(param_child, segments, index + 1, method, params, owned)) |h| {
                    return h;
                }
                // Backtrack
                params.removeLast();
            }
        }

        // 3. Try wildcard match (matches rest of path)
        if (node.wildcard_child) |wc| {
            if (wc.param_name) |pname| {
                if (wc.handlers.get(method)) |handler_key| {
                    // Join remaining segments with '/'
                    var total_len: usize = 0;
                    for (segments[index..]) |s| {
                        if (total_len > 0) total_len += 1;
                        total_len += s.len;
                    }
                    const joined = self.alloc.alloc(u8, total_len) catch return null;
                    var pos: usize = 0;
                    for (segments[index..]) |s| {
                        if (pos > 0) {
                            joined[pos] = '/';
                            pos += 1;
                        }
                        @memcpy(joined[pos..][0..s.len], s);
                        pos += s.len;
                    }
                    params.put(pname, joined);
                    owned.append(self.alloc, joined) catch return null;
                    return handler_key;
                }
            }
        }

        return null;
    }
};

// ── Route node ──────────────────────────────────────────────────────────────

const RouteNode = struct {
    children: std.StringHashMap(*RouteNode),
    param_child: ?*RouteNode,
    wildcard_child: ?*RouteNode,
    param_name: ?[]const u8,
    /// Maps HTTP method → handler_key (e.g. "GET" → "GET /users/{id}")
    handlers: std.StringHashMap([]const u8),

    fn initEmpty(alloc: Allocator) RouteNode {
        return .{
            .children = std.StringHashMap(*RouteNode).init(alloc),
            .param_child = null,
            .wildcard_child = null,
            .param_name = null,
            .handlers = std.StringHashMap([]const u8).init(alloc),
        };
    }

    fn deinit(self: *RouteNode, alloc: Allocator) void {
        // Free static children
        var it = self.children.iterator();
        while (it.next()) |entry| {
            entry.value_ptr.*.deinit(alloc);
            alloc.destroy(entry.value_ptr.*);
            alloc.free(entry.key_ptr.*);
        }
        self.children.deinit();

        // Free param child
        if (self.param_child) |pc| {
            pc.deinit(alloc);
            alloc.destroy(pc);
        }

        // Free wildcard child
        if (self.wildcard_child) |wc| {
            wc.deinit(alloc);
            alloc.destroy(wc);
        }

        // Free owned strings
        if (self.param_name) |pn| alloc.free(pn);
        var hit = self.handlers.iterator();
        while (hit.next()) |entry| {
            alloc.free(entry.key_ptr.*);
            alloc.free(entry.value_ptr.*);
        }
        self.handlers.deinit();
    }
};

// ── Path parsing ────────────────────────────────────────────────────────────

const Segment = union(enum) {
    static: []const u8,
    param: []const u8,
    wildcard: []const u8,
};

fn parsePath(alloc: Allocator, path: []const u8) ![]const Segment {
    const trimmed = if (path.len > 0 and path[0] == '/') path[1..] else path;

    if (trimmed.len == 0) {
        // Root path — zero segments (handler lives at the root node)
        return try alloc.alloc(Segment, 0);
    }

    // Count segments
    var count: usize = 1;
    for (trimmed) |ch| {
        if (ch == '/') count += 1;
    }

    const segs = try alloc.alloc(Segment, count);
    var i: usize = 0;
    var it = std.mem.splitScalar(u8, trimmed, '/');
    while (it.next()) |seg| {
        if (seg.len >= 2 and seg[0] == '{' and seg[seg.len - 1] == '}') {
            segs[i] = .{ .param = seg[1 .. seg.len - 1] };
        } else if (seg.len >= 1 and seg[0] == '*') {
            const name = if (seg.len > 1) seg[1..] else "wildcard";
            segs[i] = .{ .wildcard = name };
        } else {
            segs[i] = .{ .static = seg };
        }
        i += 1;
    }

    return segs;
}

// ── Tests ───────────────────────────────────────────────────────────────────

test "static routes" {
    const alloc = std.testing.allocator;
    var r = Router.init(alloc);
    defer r.deinit();

    try r.addRoute("GET", "/users", "GET /users");

    var m1 = r.findRoute("GET", "/users").?;
    defer m1.deinit();
    try std.testing.expectEqualStrings("GET /users", m1.handler_key);
}

test "multiple methods on same path" {
    const alloc = std.testing.allocator;
    var r = Router.init(alloc);
    defer r.deinit();

    try r.addRoute("GET", "/items", "GET /items");
    try r.addRoute("POST", "/items", "POST /items");

    var m1 = r.findRoute("GET", "/items").?;
    defer m1.deinit();
    try std.testing.expectEqualStrings("GET /items", m1.handler_key);

    var m2 = r.findRoute("POST", "/items").?;
    defer m2.deinit();
    try std.testing.expectEqualStrings("POST /items", m2.handler_key);

    const m3 = r.findRoute("DELETE", "/items");
    try std.testing.expect(m3 == null);
}

test "parameterized routes" {
    const alloc = std.testing.allocator;
    var r = Router.init(alloc);
    defer r.deinit();

    try r.addRoute("GET", "/users/{id}", "GET /users/{id}");

    var m = r.findRoute("GET", "/users/123").?;
    defer m.deinit();
    try std.testing.expectEqualStrings("GET /users/{id}", m.handler_key);
    try std.testing.expectEqualStrings("123", m.params.get("id").?);
}

test "multi-param routes" {
    const alloc = std.testing.allocator;
    var r = Router.init(alloc);
    defer r.deinit();

    try r.addRoute("GET", "/api/v1/users/{id}/posts/{post_id}", "GET /api/v1/users/{id}/posts/{post_id}");

    var m = r.findRoute("GET", "/api/v1/users/42/posts/7").?;
    defer m.deinit();
    try std.testing.expectEqualStrings("42", m.params.get("id").?);
    try std.testing.expectEqualStrings("7", m.params.get("post_id").?);
}

test "wildcard routes" {
    const alloc = std.testing.allocator;
    var r = Router.init(alloc);
    defer r.deinit();

    try r.addRoute("GET", "/files/*path", "GET /files/*path");

    var m = r.findRoute("GET", "/files/docs/readme.txt").?;
    defer m.deinit();
    try std.testing.expectEqualStrings("GET /files/*path", m.handler_key);
    try std.testing.expectEqualStrings("docs/readme.txt", m.params.get("path").?);
}

test "static takes priority over param" {
    const alloc = std.testing.allocator;
    var r = Router.init(alloc);
    defer r.deinit();

    try r.addRoute("GET", "/users/me", "GET /users/me");
    try r.addRoute("GET", "/users/{id}", "GET /users/{id}");

    var m1 = r.findRoute("GET", "/users/me").?;
    defer m1.deinit();
    try std.testing.expectEqualStrings("GET /users/me", m1.handler_key);

    var m2 = r.findRoute("GET", "/users/123").?;
    defer m2.deinit();
    try std.testing.expectEqualStrings("GET /users/{id}", m2.handler_key);
}

test "method mismatch returns null" {
    const alloc = std.testing.allocator;
    var r = Router.init(alloc);
    defer r.deinit();

    try r.addRoute("GET", "/users", "GET /users");

    const m = r.findRoute("DELETE", "/users");
    try std.testing.expect(m == null);
}

test "no match returns null" {
    const alloc = std.testing.allocator;
    var r = Router.init(alloc);
    defer r.deinit();

    try r.addRoute("GET", "/users", "GET /users");

    const m = r.findRoute("GET", "/posts");
    try std.testing.expect(m == null);
}


// ── Fuzz tests ───────────────────────────────────────────────────────────────
// Run: zig build fuzz-router  (then execute the binary with --fuzz)

fn fuzz_findRoute(_: void, input: []const u8) anyerror!void {
    if (input.len == 0) return;

    // First byte selects the HTTP method
    const methods = [_][]const u8{ "GET", "POST", "PUT", "DELETE", "PATCH", "" };
    const method = methods[input[0] % methods.len];
    // Remainder is the path (may be empty, may be garbage)
    const path = if (input.len > 1) input[1..] else "/";

    var r = Router.init(std.heap.c_allocator);
    defer r.deinit();

    // Seed with representative routes
    r.addRoute("GET",    "/",                  "GET /")                 catch return;
    r.addRoute("GET",    "/users",             "GET /users")            catch return;
    r.addRoute("GET",    "/users/{id}",        "GET /users/{id}")       catch return;
    r.addRoute("POST",   "/users",             "POST /users")           catch return;
    r.addRoute("PUT",    "/users/{id}",        "PUT /users/{id}")       catch return;
    r.addRoute("DELETE", "/users/{id}",        "DELETE /users/{id}")    catch return;
    r.addRoute("GET",    "/items/{cat}/{id}",  "GET /items/{cat}/{id}") catch return;
    r.addRoute("GET",    "/files/*",           "GET /files/*")          catch return;
    r.addRoute("GET",    "/health",            "GET /health")           catch return;

    // Invariant: findRoute must never panic regardless of method or path content
    if (r.findRoute(method, path)) |match_c| {
        var match = match_c; // mutable copy so deinit(*self) compiles
        defer match.deinit();
        // Invariant: matched handler_key must always be non-empty
        try std.testing.expect(match.handler_key.len > 0);
    }
    // null is also valid — means no match, not an error
}

test "fuzz: router findRoute — never panics, no OOB on any path" {
    try std.testing.fuzz({}, fuzz_findRoute, .{ .corpus = &.{
        // method byte + path
        "\x00/",                        // GET /
        "\x00/users/42",                // GET /users/42
        "\x01/users",                   // POST /users
        "\x00/users/",                  // trailing slash
        "\x00/items/books/99",          // multi-param
        "\x00/health",                  // static route
        "\x00/files/deep/nested/path",  // wildcard
        // Adversarial inputs
        "\x00" ++ "/" ++ ("a/" ** 70),  // 70 segments — exceeds 64-segment limit → null
        "\x00/\x00secret",              // null byte in path
        "\x00/" ++ ("a" ** 4096),       // very long single segment
        "\x00/%2F%2F/../admin",         // path traversal attempt
        "\x00/users/%00/profile",       // null byte percent-encoded
        "\x00//double//slash//path",    // double slashes
        "\x00/users/{injected}",        // brace injection in request path
        "\x00/\xFF\xFE\xFD",           // invalid UTF-8
        "\x05/anything",                // empty method string
        "\x00",                         // no path (just method byte)
    }});
}
