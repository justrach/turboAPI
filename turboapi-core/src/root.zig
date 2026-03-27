// turboapi-core — shared HTTP primitives for turboAPI and merjs.
//
// Usage:
//   const core = @import("turboapi-core");
//   var r = core.Router.init(allocator);
//   const date = core.http.formatHttpDate(&buf);

pub const router = @import("router.zig");
pub const http = @import("http.zig");
pub const types = @import("types.zig");
pub const cache = @import("cache.zig");

// Convenience re-exports
pub const Router = router.Router;
pub const RouteParams = router.RouteParams;
pub const RouteMatch = router.RouteMatch;
pub const RouteParam = router.RouteParam;
pub const HeaderPair = types.HeaderPair;

test {
    _ = router;
    _ = http;
    _ = cache;
}
