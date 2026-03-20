// GENERATED — do not edit by hand.
// Re-run `zig build codegen` to regenerate.

const Route = @import("../router.zig").Route;

const api_hello = @import("api/hello");
const app_about = @import("app/about");
const app_benchmarks = @import("app/benchmarks");
const app_docs = @import("app/docs");
const app_index = @import("app/index");
const app_notes = @import("app/notes");
const app_quickstart = @import("app/quickstart");
const app_turbopg = @import("app/turbopg");

pub const routes: []const Route = &.{
    .{ .path = "/api/hello", .render = api_hello.render, .render_stream = if (@hasDecl(api_hello, "renderStream")) api_hello.renderStream else null, .meta = if (@hasDecl(api_hello, "meta")) api_hello.meta else .{}, .prerender = if (@hasDecl(api_hello, "prerender")) api_hello.prerender else false },
    .{ .path = "/about", .render = app_about.render, .render_stream = if (@hasDecl(app_about, "renderStream")) app_about.renderStream else null, .meta = if (@hasDecl(app_about, "meta")) app_about.meta else .{}, .prerender = if (@hasDecl(app_about, "prerender")) app_about.prerender else false },
    .{ .path = "/benchmarks", .render = app_benchmarks.render, .render_stream = if (@hasDecl(app_benchmarks, "renderStream")) app_benchmarks.renderStream else null, .meta = if (@hasDecl(app_benchmarks, "meta")) app_benchmarks.meta else .{}, .prerender = if (@hasDecl(app_benchmarks, "prerender")) app_benchmarks.prerender else false },
    .{ .path = "/docs", .render = app_docs.render, .render_stream = if (@hasDecl(app_docs, "renderStream")) app_docs.renderStream else null, .meta = if (@hasDecl(app_docs, "meta")) app_docs.meta else .{}, .prerender = if (@hasDecl(app_docs, "prerender")) app_docs.prerender else false },
    .{ .path = "/", .render = app_index.render, .render_stream = if (@hasDecl(app_index, "renderStream")) app_index.renderStream else null, .meta = if (@hasDecl(app_index, "meta")) app_index.meta else .{}, .prerender = if (@hasDecl(app_index, "prerender")) app_index.prerender else false },
    .{ .path = "/notes", .render = app_notes.render, .render_stream = if (@hasDecl(app_notes, "renderStream")) app_notes.renderStream else null, .meta = if (@hasDecl(app_notes, "meta")) app_notes.meta else .{}, .prerender = if (@hasDecl(app_notes, "prerender")) app_notes.prerender else false },
    .{ .path = "/quickstart", .render = app_quickstart.render, .render_stream = if (@hasDecl(app_quickstart, "renderStream")) app_quickstart.renderStream else null, .meta = if (@hasDecl(app_quickstart, "meta")) app_quickstart.meta else .{}, .prerender = if (@hasDecl(app_quickstart, "prerender")) app_quickstart.prerender else false },
    .{ .path = "/turbopg", .render = app_turbopg.render, .render_stream = if (@hasDecl(app_turbopg, "renderStream")) app_turbopg.renderStream else null, .meta = if (@hasDecl(app_turbopg, "meta")) app_turbopg.meta else .{}, .prerender = if (@hasDecl(app_turbopg, "prerender")) app_turbopg.prerender else false },
};

comptime {
    if (!@hasDecl(app_about, "meta")) @compileError("app/about.zig must export pub const meta: mer.Meta");
    if (!@hasDecl(app_benchmarks, "meta")) @compileError("app/benchmarks.zig must export pub const meta: mer.Meta");
    if (!@hasDecl(app_docs, "meta")) @compileError("app/docs.zig must export pub const meta: mer.Meta");
    if (!@hasDecl(app_index, "meta")) @compileError("app/index.zig must export pub const meta: mer.Meta");
    if (!@hasDecl(app_notes, "meta")) @compileError("app/notes.zig must export pub const meta: mer.Meta");
    if (!@hasDecl(app_quickstart, "meta")) @compileError("app/quickstart.zig must export pub const meta: mer.Meta");
    if (!@hasDecl(app_turbopg, "meta")) @compileError("app/turbopg.zig must export pub const meta: mer.Meta");
}

const app_layout = @import("app/layout");
pub const layout = app_layout.wrap;
pub const streamLayout = if (@hasDecl(app_layout, "streamWrap")) app_layout.streamWrap else null;
const app_404 = @import("app/404");
pub const notFound = app_404.render;
