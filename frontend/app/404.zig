const mer = @import("mer");

pub const meta: mer.Meta = .{ .title = "404" };

pub fn render(req: mer.Request) mer.Response {
    _ = req;
    return .{ .status = .not_found, .content_type = .html, .body = "<h1>404 — Not Found</h1>" };
}
