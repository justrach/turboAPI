// dev.zig — dev-mode helpers: hot reload injection, error overlay, debug endpoint.
// Owned by mer.zig (pub const dev = @import("dev.zig")) to avoid Zig file-ownership errors.
// Does NOT import mer.zig to prevent circular dependencies.

const std = @import("std");
const res_mod = @import("response.zig");

/// Minimal route info passed from server.zig for the debug endpoint.
pub const RouteDebugInfo = struct {
    path: []const u8,
};

pub const hot_reload_script =
    \\<script>
    \\(function(){
    \\  const es = new EventSource('/_mer/events');
    \\  es.onmessage = () => location.reload();
    \\})();
    \\</script>
    \\</body>
;

pub fn injectHotReload(alloc: std.mem.Allocator, body: []const u8) ![]u8 {
    const marker = "</body>";
    const idx = std.mem.lastIndexOf(u8, body, marker) orelse return error.NoBodyTag;
    const before = body[0..idx];
    const after = body[idx + marker.len ..];
    return std.fmt.allocPrint(alloc, "{s}{s}{s}", .{ before, hot_reload_script, after });
}

/// Dev error overlay — renders a styled error page in the browser when a route handler fails.
pub fn sendErrorOverlay(std_req: *std.http.Server.Request, target: []const u8, err: anyerror, version: []const u8) !void {
    const error_name = @errorName(err);

    const fixed = [1]std.http.Header{
        .{ .name = "content-type", .value = "text/html; charset=utf-8" },
    };
    var header_buf: [4096]u8 = undefined;
    var bw = try std_req.respondStreaming(&header_buf, .{
        .respond_options = .{
            .status = .internal_server_error,
            .extra_headers = &fixed,
        },
    });

    try bw.writer.writeAll(
        \\<!DOCTYPE html><html><head><meta charset="UTF-8"><title>merjs error</title>
        \\<style>
        \\*{margin:0;padding:0;box-sizing:border-box}
        \\body{font-family:-apple-system,system-ui,monospace;background:#1a1a2e;color:#e0e0e0;padding:2em}
        \\.err-box{max-width:720px;margin:3em auto;border:2px solid #ff5555;border-radius:12px;overflow:hidden}
        \\.err-header{background:#ff5555;color:#fff;padding:16px 24px;font-size:14px;font-weight:600;letter-spacing:0.5px}
        \\.err-body{padding:24px}
        \\.err-name{font-size:28px;color:#ff7979;margin-bottom:12px}
        \\.err-path{color:#82b1ff;font-size:16px;margin-bottom:24px}
        \\.err-hint{background:#222244;border-radius:8px;padding:16px;margin-top:16px;font-size:13px;line-height:1.6;color:#aaa}
        \\.err-hint code{color:#64ffda;background:#1a1a2e;padding:2px 6px;border-radius:3px}
        \\.err-footer{border-top:1px solid #333;padding:16px 24px;font-size:12px;color:#666}
        \\</style></head><body>
        \\<div class="err-box">
        \\<div class="err-header">MERJS DEV ERROR</div>
        \\<div class="err-body">
        \\<div class="err-name">
    );
    try bw.writer.writeAll(error_name);
    try bw.writer.writeAll(
        \\</div>
        \\<div class="err-path">
    );
    try bw.writer.writeAll(target);
    try bw.writer.writeAll(
        \\</div>
        \\<div class="err-hint">
        \\<strong>Debugging tips:</strong><br>
        \\&bull; Run with <code>--verbose</code> to see per-request timing<br>
        \\&bull; Visit <code>/_mer/debug</code> to see all registered routes<br>
        \\&bull; Check the terminal for the full error log<br>
        \\&bull; Use <code>std.log.scoped(.mypage)</code> in your page handler for custom logs
        \\</div>
        \\</div>
        \\<div class="err-footer">merjs v
    );
    try bw.writer.writeAll(version);
    try bw.writer.writeAll(
        \\ &mdash; this error page is only shown in dev mode</div>
        \\</div></body></html>
    );
    try bw.end();
}

/// Build a response for the /_mer/debug endpoint.
/// Caller is responsible for sending it via sendResponse (which adds security headers).
pub fn serveDebug(
    alloc: std.mem.Allocator,
    routes: []const RouteDebugInfo,
    exact_count: usize,
    dynamic_count: usize,
    query_string: []const u8,
    version: []const u8,
) !res_mod.Response {
    const want_json = std.mem.indexOf(u8, query_string, "format=json") != null;
    var body: std.ArrayListUnmanaged(u8) = .{};
    const w = body.writer(alloc);

    if (want_json) {
        // JSON mode — for agents and programmatic access.
        try w.writeAll("{\"version\":\"");
        try w.writeAll(version);
        try w.writeAll("\",\"zig\":\"");
        try w.writeAll(@import("builtin").zig_version_string);
        try w.print("\",\"routes_exact\":{d},\"routes_dynamic\":{d},\"routes\":[", .{ exact_count, dynamic_count });
        for (routes, 0..) |route, i| {
            if (i > 0) try w.writeAll(",");
            const rtype: []const u8 = if (std.mem.startsWith(u8, route.path, "/api/")) "api" else "page";
            try w.print("{{\"path\":\"{s}\",\"type\":\"{s}\"}}", .{ route.path, rtype });
        }
        try w.writeAll("],\"hints\":[");
        try w.writeAll("\"Run with --verbose for per-request timing\",");
        try w.writeAll("\"Visit /_mer/events for SSE hot reload stream\",");
        try w.writeAll("\"Use std.log.scoped(.mypage) in page handlers\"");
        try w.writeAll("]}");

        return res_mod.Response.init(.ok, .json, body.items);
    } else {
        // HTML mode — for browsers.
        try w.writeAll("<html><head><title>merjs debug</title><style>");
        try w.writeAll("body{font-family:monospace;max-width:720px;margin:2em auto;background:#1a1a2e;color:#e0e0e0}");
        try w.writeAll("h1{color:#64ffda}h2{color:#82b1ff;margin-top:1.5em}table{border-collapse:collapse;width:100%}");
        try w.writeAll("td,th{text-align:left;padding:4px 12px;border-bottom:1px solid #333}th{color:#aaa}");
        try w.writeAll("code{color:#64ffda;background:#222244;padding:2px 6px;border-radius:3px}");
        try w.writeAll("</style></head><body>");
        try w.writeAll("<h1>merjs debug</h1>");

        try w.writeAll("<h2>Routes</h2><table><tr><th>Path</th><th>Type</th></tr>");
        for (routes) |route| {
            const rtype: []const u8 = if (std.mem.startsWith(u8, route.path, "/api/")) "API" else "Page";
            try w.print("<tr><td>{s}</td><td>{s}</td></tr>", .{ route.path, rtype });
        }
        try w.writeAll("</table>");

        try w.writeAll("<h2>Config</h2><table>");
        try w.print("<tr><td>Version</td><td>{s}</td></tr>", .{version});
        try w.print("<tr><td>Zig</td><td>{s}</td></tr>", .{@import("builtin").zig_version_string});
        try w.print("<tr><td>Routes</td><td>{d} exact + {d} dynamic</td></tr>", .{ exact_count, dynamic_count });
        try w.writeAll("</table>");

        try w.writeAll("<h2>Hints</h2><ul>");
        try w.writeAll("<li>Run with <code>--verbose</code> to log per-request timing</li>");
        try w.writeAll("<li>Use <code>std.log.scoped(.mypage)</code> in page handlers for route-level logs</li>");
        try w.writeAll("<li><code>/_mer/events</code> — SSE hot reload stream</li>");
        try w.writeAll("<li>Append <code>?format=json</code> to this URL for machine-readable output</li>");
        try w.writeAll("</ul>");

        try w.writeAll("</body></html>");

        return res_mod.Response.init(.ok, .html, body.items);
    }
}
