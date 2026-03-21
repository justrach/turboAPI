// mer.zig — public API surface for page authors.
// All user code imports this as `@import("mer")`.
// Implementation lives in dedicated files; this re-exports them.

const std = @import("std");
const req_mod = @import("request.zig");
const res_mod = @import("response.zig");
const session_mod = @import("session.zig");
const fetch_mod = @import("fetch.zig");

/// Framework version — kept in sync with build.zig.zon.
pub const version = "0.1.1";

// --- Streaming SSR ----------------------------------------------------------

pub const StreamParts = struct { head: []const u8, tail: []const u8 };

pub const StreamWriter = struct {
    allocator: std.mem.Allocator,
    ctx: *anyopaque,
    writeFn: *const fn (ctx: *anyopaque, data: []const u8) void,
    flushFn: *const fn (ctx: *anyopaque) void,

    pub fn write(self: *StreamWriter, data: []const u8) void {
        self.writeFn(self.ctx, data);
    }

    pub fn flush(self: *StreamWriter) void {
        self.flushFn(self.ctx);
    }

    pub fn placeholder(self: *StreamWriter, id: []const u8, fallback_html: []const u8) void {
        self.write("<div id=\"P:");
        self.write(id);
        self.write("\">");
        self.write(fallback_html);
        self.write("</div>");
    }

    pub fn resolve(self: *StreamWriter, id: []const u8, content: []const u8) void {
        self.write("<div hidden id=\"S:");
        self.write(id);
        self.write("\">");
        self.write(content);
        self.write("</div><script>");
        self.write("(function(){var p=document.getElementById('P:");
        self.write(id);
        self.write("'),s=document.getElementById('S:");
        self.write(id);
        self.write("');if(p&&s){p.outerHTML=s.innerHTML;s.remove()}}())");
        self.write("</script>");
        self.flush();
    }
};

// --- Request / Response types -----------------------------------------------

pub const Method = req_mod.Method;
pub const Param = req_mod.Param;
pub const Request = req_mod.Request;
pub const ContentType = res_mod.ContentType;
pub const Response = res_mod.Response;
pub const SameSite = res_mod.SameSite;
pub const SetCookie = res_mod.SetCookie;

// --- Response helpers -------------------------------------------------------

pub const html = res_mod.html;
pub const json = res_mod.json;
pub const text = res_mod.text;
pub const notFound = res_mod.notFound;
pub const internalError = res_mod.internalError;
pub const redirect = res_mod.redirect;
pub const withCookies = res_mod.withCookies;

pub fn typedJson(allocator: std.mem.Allocator, value: anytype) Response {
    var out: std.io.Writer.Allocating = .init(allocator);
    var jw: std.json.Stringify = .{ .writer = &out.writer };
    jw.write(value) catch return internalError("json write failed");
    return res_mod.Response.init(.ok, .json, out.written());
}

pub fn parseJson(comptime T: type, req: Request) !?std.json.Parsed(T) {
    if (req.body.len == 0) return null;
    return std.json.parseFromSlice(T, req.allocator, req.body, .{ .ignore_unknown_fields = true });
}

pub fn formParam(body: []const u8, name: []const u8) ?[]const u8 {
    var params = body;
    while (params.len > 0) {
        const amp = std.mem.indexOfScalar(u8, params, '&') orelse params.len;
        const kv = params[0..amp];
        if (std.mem.indexOfScalar(u8, kv, '=')) |eq| {
            if (std.mem.eql(u8, kv[0..eq], name)) return kv[eq + 1 ..];
        }
        params = if (amp < params.len) params[amp + 1 ..] else "";
    }
    return null;
}

pub fn badRequest(msg: []const u8) Response {
    return res_mod.Response.init(.bad_request, .text, msg);
}

// --- Environment ------------------------------------------------------------

const env_mod = @import("env.zig");
pub fn env(name: []const u8) ?[]const u8 {
    return env_mod.get(name);
}
pub const loadDotenv = env_mod.loadDotenv;

// --- Session (src/session.zig) ----------------------------------------------

pub const Session = session_mod.Session;
pub const SESSION_DEFAULT_TTL = session_mod.SESSION_DEFAULT_TTL;
pub const signSession = session_mod.signSession;
pub const verifySession = session_mod.verifySession;

// --- HTTP fetch (src/fetch.zig) ---------------------------------------------

pub const FetchRequest = fetch_mod.FetchRequest;
pub const FetchResponse = fetch_mod.FetchResponse;
pub const fetch = fetch_mod.fetch;
pub const fetchAll = fetch_mod.fetchAll;
pub const wasmBeginCollect = fetch_mod.wasmBeginCollect;
pub const wasmEndCollect = fetch_mod.wasmEndCollect;
pub const wasmProvideResult = fetch_mod.wasmProvideResult;
pub const wasmClearCache = fetch_mod.wasmClearCache;

// --- SEO / Meta tags --------------------------------------------------------

pub const Meta = struct {
    title: []const u8 = "",
    description: []const u8 = "",
    og_title: ?[]const u8 = null,
    og_description: ?[]const u8 = null,
    og_image: ?[]const u8 = null,
    og_url: ?[]const u8 = null,
    og_type: []const u8 = "website",
    og_site_name: []const u8 = "merjs",
    twitter_card: []const u8 = "summary_large_image",
    twitter_title: ?[]const u8 = null,
    twitter_description: ?[]const u8 = null,
    twitter_image: ?[]const u8 = null,
    twitter_site: ?[]const u8 = null,
    canonical: ?[]const u8 = null,
    robots: ?[]const u8 = null,
    extra_head: ?[]const u8 = null,
};

// --- HTML builder -----------------------------------------------------------

pub const h = @import("html.zig");
pub const lint = @import("html_lint.zig");

// --- CSS helpers (comptime inline styles + class names) ----------------------

pub const css = @import("css.zig");

pub fn render(allocator: std.mem.Allocator, node: h.Node) Response {
    const body = h.render(allocator, node) catch return internalError("html render failed");
    return Response.init(.ok, .html, body);
}

// --- Validation (dhi) -------------------------------------------------------

pub const dhi = @import("dhi.zig");

// --- Telemetry (Sentry + Datadog) -------------------------------------------

pub const telemetry = @import("telemetry.zig");

// --- Dev tools (debug endpoint, error overlay, hot reload) ------------------

pub const dev = @import("dev.zig");
