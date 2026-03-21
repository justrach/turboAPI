// ssr.zig — SSR dispatch layer.
// Imports the generated routes table and builds a Router.

const std = @import("std");
const mer = @import("mer");
const Router = @import("router.zig").Router;
const generated = @import("generated/routes.zig");

pub fn buildRouter(allocator: std.mem.Allocator) Router {
    var r = Router.init(allocator, generated.routes);
    if (@hasDecl(generated, "layout")) {
        r.layout = generated.layout;
    }
    // Enable streaming SSR if the layout exports streamWrap.
    if (@hasDecl(generated, "streamLayout")) {
        r.stream_layout = generated.streamLayout;
    }
    if (@hasDecl(generated, "notFound")) {
        r.not_found = generated.notFound;
    }
    return r;
}
