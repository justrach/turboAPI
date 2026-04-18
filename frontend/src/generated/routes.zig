const Route = @import("../router.zig").Route;

const app_benchmarks = @import("app/benchmarks");
const app_docs = @import("app/docs");
const app_index = @import("app/index");
const app_notes = @import("app/notes");
const app_quickstart = @import("app/quickstart");
const app_turbopg = @import("app/turbopg");
const app_turboboto = @import("app/turboboto");
const app_httpcore = @import("app/httpcore");
const app_v1_0_28 = @import("app/v1_0_28");

pub const routes: []const Route = &.{
    .{ .path = "/benchmarks", .render = app_benchmarks.render, .render_stream = if (@hasDecl(app_benchmarks, "renderStream")) app_benchmarks.renderStream else null, .meta = if (@hasDecl(app_benchmarks, "meta")) app_benchmarks.meta else .{}, .prerender = if (@hasDecl(app_benchmarks, "prerender")) app_benchmarks.prerender else false },
    .{ .path = "/docs", .render = app_docs.render, .render_stream = if (@hasDecl(app_docs, "renderStream")) app_docs.renderStream else null, .meta = if (@hasDecl(app_docs, "meta")) app_docs.meta else .{}, .prerender = if (@hasDecl(app_docs, "prerender")) app_docs.prerender else false },
    .{ .path = "/", .render = app_index.render, .render_stream = if (@hasDecl(app_index, "renderStream")) app_index.renderStream else null, .meta = if (@hasDecl(app_index, "meta")) app_index.meta else .{}, .prerender = if (@hasDecl(app_index, "prerender")) app_index.prerender else false },
    .{ .path = "/notes", .render = app_notes.render, .render_stream = if (@hasDecl(app_notes, "renderStream")) app_notes.renderStream else null, .meta = if (@hasDecl(app_notes, "meta")) app_notes.meta else .{}, .prerender = if (@hasDecl(app_notes, "prerender")) app_notes.prerender else false },
    .{ .path = "/quickstart", .render = app_quickstart.render, .render_stream = if (@hasDecl(app_quickstart, "renderStream")) app_quickstart.renderStream else null, .meta = if (@hasDecl(app_quickstart, "meta")) app_quickstart.meta else .{}, .prerender = if (@hasDecl(app_quickstart, "prerender")) app_quickstart.prerender else false },
    .{ .path = "/turbopg", .render = app_turbopg.render, .render_stream = if (@hasDecl(app_turbopg, "renderStream")) app_turbopg.renderStream else null, .meta = if (@hasDecl(app_turbopg, "meta")) app_turbopg.meta else .{}, .prerender = if (@hasDecl(app_turbopg, "prerender")) app_turbopg.prerender else false },
    .{ .path = "/turboboto", .render = app_turboboto.render, .render_stream = if (@hasDecl(app_turboboto, "renderStream")) app_turboboto.renderStream else null, .meta = if (@hasDecl(app_turboboto, "meta")) app_turboboto.meta else .{}, .prerender = if (@hasDecl(app_turboboto, "prerender")) app_turboboto.prerender else false },
    .{ .path = "/httpcore", .render = app_httpcore.render, .render_stream = if (@hasDecl(app_httpcore, "renderStream")) app_httpcore.renderStream else null, .meta = if (@hasDecl(app_httpcore, "meta")) app_httpcore.meta else .{}, .prerender = if (@hasDecl(app_httpcore, "prerender")) app_httpcore.prerender else false },
    .{ .path = "/v1.0.28", .render = app_v1_0_28.render, .render_stream = if (@hasDecl(app_v1_0_28, "renderStream")) app_v1_0_28.renderStream else null, .meta = if (@hasDecl(app_v1_0_28, "meta")) app_v1_0_28.meta else .{}, .prerender = if (@hasDecl(app_v1_0_28, "prerender")) app_v1_0_28.prerender else false },
};

const app_layout = @import("app/layout");
pub const layout = app_layout.wrap;
pub const streamLayout = if (@hasDecl(app_layout, "streamWrap")) app_layout.streamWrap else null;
const app_404 = @import("app/404");
pub const notFound = app_404.render;
