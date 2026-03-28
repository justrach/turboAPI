// Benchmark: turboapi-core radix trie router throughput
// Measures raw route lookups/sec — no HTTP, no I/O, pure routing.

const std = @import("std");
const root = @import("src/root.zig");
const Router = root.Router;

const print = std.debug.print;

pub fn main() !void {
    const alloc = std.heap.c_allocator;

    var router = Router.init(alloc);
    defer router.deinit();

    // Register routes matching a realistic API
    const routes = [_][3][]const u8{
        .{ "GET", "/", "GET /" },
        .{ "GET", "/health", "GET /health" },
        .{ "GET", "/api/v1/users", "GET /api/v1/users" },
        .{ "GET", "/api/v1/users/{id}", "GET /api/v1/users/{id}" },
        .{ "POST", "/api/v1/users", "POST /api/v1/users" },
        .{ "PUT", "/api/v1/users/{id}", "PUT /api/v1/users/{id}" },
        .{ "DELETE", "/api/v1/users/{id}", "DELETE /api/v1/users/{id}" },
        .{ "GET", "/api/v1/users/{id}/posts", "GET /api/v1/users/{id}/posts" },
        .{ "GET", "/api/v1/users/{id}/posts/{post_id}", "GET /api/v1/users/{id}/posts/{post_id}" },
        .{ "GET", "/api/v1/items", "GET /api/v1/items" },
        .{ "GET", "/api/v1/items/{cat}/{id}", "GET /api/v1/items/{cat}/{id}" },
        .{ "POST", "/api/v1/items", "POST /api/v1/items" },
        .{ "GET", "/api/v1/search", "GET /api/v1/search" },
        .{ "GET", "/docs", "GET /docs" },
        .{ "GET", "/openapi.json", "GET /openapi.json" },
        .{ "GET", "/static/*path", "GET /static/*path" },
    };

    for (routes) |r| {
        try router.addRoute(r[0], r[1], r[2]);
    }

    // Lookup patterns — mix of static, param, multi-param, wildcard, miss
    const lookups = [_][2][]const u8{
        .{ "GET", "/" },
        .{ "GET", "/health" },
        .{ "GET", "/api/v1/users" },
        .{ "GET", "/api/v1/users/42" },
        .{ "POST", "/api/v1/users" },
        .{ "GET", "/api/v1/users/42/posts" },
        .{ "GET", "/api/v1/users/42/posts/7" },
        .{ "GET", "/api/v1/items/books/99" },
        .{ "GET", "/api/v1/search" },
        .{ "GET", "/docs" },
        .{ "GET", "/static/css/app.min.css" },
        .{ "DELETE", "/api/v1/users/123" },
        .{ "GET", "/nonexistent" },
    };

    print("\n", .{});
    print("turboapi-core router benchmark\n", .{});
    print("══════════════════════════════════════════════════════\n", .{});
    print("{d} routes registered, {d} lookup patterns\n\n", .{ routes.len, lookups.len });

    // Warmup
    for (0..100_000) |_| {
        for (lookups) |l| {
            if (router.findRoute(l[0], l[1])) |m| {
                var match = m;
                match.deinit();
            }
        }
    }

    print("  Route type                        ops/sec     ns/op\n", .{});
    print("  ───────────────────────────────────────────────────\n", .{});

    const cases = [_]struct { name: []const u8, method: []const u8, path: []const u8 }{
        .{ .name = "static   GET /health            ", .method = "GET", .path = "/health" },
        .{ .name = "static   GET /api/v1/users       ", .method = "GET", .path = "/api/v1/users" },
        .{ .name = "1-param  GET /api/v1/users/42    ", .method = "GET", .path = "/api/v1/users/42" },
        .{ .name = "2-param  GET /users/42/posts/7   ", .method = "GET", .path = "/api/v1/users/42/posts/7" },
        .{ .name = "wildcard GET /static/css/app.css ", .method = "GET", .path = "/static/css/app.min.css" },
        .{ .name = "miss     GET /nonexistent        ", .method = "GET", .path = "/nonexistent" },
    };

    const iters: u64 = 5_000_000;

    for (cases) |c| {
        var timer = std.time.Timer.start() catch unreachable;

        for (0..iters) |_| {
            if (router.findRoute(c.method, c.path)) |m| {
                var match = m;
                match.deinit();
            }
        }

        const elapsed_ns = timer.read();
        const ns_per_op = elapsed_ns / iters;
        const ops_per_sec = if (ns_per_op > 0) 1_000_000_000 / ns_per_op else 0;
        print("  {s} {d:>10}/s   {d:>4}ns\n", .{ c.name, ops_per_sec, ns_per_op });
    }

    // Aggregate: mixed workload
    print("\n  Mixed workload ({d} patterns, {d}M iterations):\n", .{ lookups.len, iters / 1_000_000 });

    var total_ops: u64 = 0;
    var timer = std.time.Timer.start() catch unreachable;

    for (0..iters) |_| {
        for (lookups) |l| {
            if (router.findRoute(l[0], l[1])) |m| {
                var match = m;
                match.deinit();
            }
            total_ops += 1;
        }
    }

    const elapsed_ns = timer.read();
    const ns_per_op = elapsed_ns / total_ops;
    const ops_per_sec = if (ns_per_op > 0) 1_000_000_000 / ns_per_op else 0;

    print("  {d:>10} lookups/sec   {d}ns avg\n", .{ ops_per_sec, ns_per_op });
    print("\n══════════════════════════════════════════════════════\n\n", .{});
}
