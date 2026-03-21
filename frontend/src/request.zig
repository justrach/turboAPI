const std = @import("std");

pub const Method = enum {
    GET,
    POST,
    PUT,
    DELETE,
    PATCH,
    HEAD,
    OPTIONS,
    unknown,

    pub fn fromStd(m: std.http.Method) Method {
        return switch (m) {
            .GET => .GET,
            .POST => .POST,
            .PUT => .PUT,
            .DELETE => .DELETE,
            .PATCH => .PATCH,
            .HEAD => .HEAD,
            .OPTIONS => .OPTIONS,
            else => .unknown,
        };
    }
};

/// A matched route parameter (e.g. `:id` segment from `/users/:id`).
pub const Param = struct {
    key: []const u8,
    value: []const u8,
};

pub const Request = struct {
    method: Method,
    path: []const u8,
    /// Raw query string (everything after `?`, without the `?`).
    /// Empty slice when no query string is present.
    query_string: []const u8,
    /// Raw request body bytes.
    /// Empty slice for GET / HEAD / requests with no body.
    body: []const u8,
    /// Raw `Cookie:` header value.
    /// Empty slice when no cookie header is present.
    cookies_raw: []const u8,
    /// Dynamic route parameters extracted by the router.
    /// E.g. for route `/users/:id` and path `/users/42`, params = [{key:"id", value:"42"}].
    params: []const Param,
    allocator: std.mem.Allocator,

    pub fn init(
        allocator: std.mem.Allocator,
        method: Method,
        path: []const u8,
    ) Request {
        return .{
            .allocator = allocator,
            .method = method,
            .path = path,
            .query_string = "",
            .body = "",
            .cookies_raw = "",
            .params = &.{},
        };
    }

    // ── Route parameters ───────────────────────────────────────────────────

    /// Return the value of a dynamic route parameter, or null if absent.
    ///
    ///   // Route: /users/:id   Request: /users/42
    ///   req.param("id")  // → "42"
    pub fn param(self: Request, name: []const u8) ?[]const u8 {
        for (self.params) |p| {
            if (std.mem.eql(u8, p.key, name)) return p.value;
        }
        return null;
    }

    // ── Query parameters ───────────────────────────────────────────────────

    /// Return the value of a query parameter, or null if absent.
    ///
    ///   // URL: /search?q=zig&page=2
    ///   req.queryParam("q")    // → "zig"
    ///   req.queryParam("page") // → "2"
    ///   req.queryParam("x")    // → null
    pub fn queryParam(self: Request, name: []const u8) ?[]const u8 {
        return queryParamFromStr(self.query_string, name);
    }

    /// Collect all query params into a StringHashMap.
    /// Caller owns the map (call `.deinit()` when done).
    pub fn queryParams(self: Request) std.StringHashMap([]const u8) {
        var map = std.StringHashMap([]const u8).init(self.allocator);
        var rest = self.query_string;
        while (rest.len > 0) {
            const amp = std.mem.indexOfScalar(u8, rest, '&') orelse rest.len;
            const kv = rest[0..amp];
            if (std.mem.indexOfScalar(u8, kv, '=')) |eq| {
                map.put(kv[0..eq], kv[eq + 1 ..]) catch {};
            }
            rest = if (amp < rest.len) rest[amp + 1 ..] else "";
        }
        return map;
    }

    // ── Cookies ────────────────────────────────────────────────────────────

    /// Return the value of a cookie, or null if absent.
    ///
    ///   // Cookie: session=abc123; theme=dark
    ///   req.cookie("session") // → "abc123"
    ///   req.cookie("theme")   // → "dark"
    pub fn cookie(self: Request, name: []const u8) ?[]const u8 {
        var rest = self.cookies_raw;
        while (rest.len > 0) {
            // Trim leading whitespace.
            while (rest.len > 0 and rest[0] == ' ') rest = rest[1..];
            const semi = std.mem.indexOfScalar(u8, rest, ';') orelse rest.len;
            const pair = rest[0..semi];
            if (std.mem.indexOfScalar(u8, pair, '=')) |eq| {
                const k = std.mem.trim(u8, pair[0..eq], " ");
                if (std.mem.eql(u8, k, name)) return pair[eq + 1 ..];
            }
            rest = if (semi < rest.len) rest[semi + 1 ..] else "";
        }
        return null;
    }
};

// ── Internal helpers ───────────────────────────────────────────────────────

/// Extract a named query param from a raw query string (no `?` prefix).
pub fn queryParamFromStr(query: []const u8, name: []const u8) ?[]const u8 {
    var rest = query;
    while (rest.len > 0) {
        const amp = std.mem.indexOfScalar(u8, rest, '&') orelse rest.len;
        const kv = rest[0..amp];
        if (std.mem.indexOfScalar(u8, kv, '=')) |eq| {
            if (std.mem.eql(u8, kv[0..eq], name)) return kv[eq + 1 ..];
        }
        rest = if (amp < rest.len) rest[amp + 1 ..] else "";
    }
    return null;
}

// ── Tests ──────────────────────────────────────────────────────────────────

test "queryParam: basic key=value" {
    var req = Request.init(std.testing.allocator, .GET, "/search");
    req.query_string = "q=zig&page=2";
    try std.testing.expectEqualStrings("zig", req.queryParam("q").?);
    try std.testing.expectEqualStrings("2", req.queryParam("page").?);
}

test "queryParam: missing key returns null" {
    var req = Request.init(std.testing.allocator, .GET, "/");
    req.query_string = "a=1";
    try std.testing.expect(req.queryParam("b") == null);
}

test "queryParam: empty query string returns null" {
    const req = Request.init(std.testing.allocator, .GET, "/");
    try std.testing.expect(req.queryParam("x") == null);
}

test "queryParam: single param, no ampersand" {
    var req = Request.init(std.testing.allocator, .GET, "/");
    req.query_string = "only=one";
    try std.testing.expectEqualStrings("one", req.queryParam("only").?);
}

test "cookie: basic name=value" {
    var req = Request.init(std.testing.allocator, .GET, "/");
    req.cookies_raw = "session=abc123; theme=dark";
    try std.testing.expectEqualStrings("abc123", req.cookie("session").?);
    try std.testing.expectEqualStrings("dark", req.cookie("theme").?);
}

test "cookie: missing name returns null" {
    var req = Request.init(std.testing.allocator, .GET, "/");
    req.cookies_raw = "a=1";
    try std.testing.expect(req.cookie("b") == null);
}

test "cookie: empty cookies_raw returns null" {
    const req = Request.init(std.testing.allocator, .GET, "/");
    try std.testing.expect(req.cookie("session") == null);
}
