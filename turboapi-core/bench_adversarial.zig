// Adversarial router benchmark — designed to catch fake/inflated numbers.
//
// Problems with naive benchmarks:
// 1. Compiler can optimize away unused results (DCE)
// 2. Same 13 paths repeated = perfect branch prediction + L1 cache
// 3. String literals reused = pointer comparison shortcuts
// 4. No param extraction verification = maybe we're not actually matching
// 5. Allocator differences (c_allocator vs testing) can hide costs

const std = @import("std");
const root = @import("src/root.zig");
const Router = root.Router;

const print = std.debug.print;

// Use volatile sink to prevent dead code elimination
var volatile_sink: usize = 0;
fn doNotOptimize(val: anytype) void {
    // Force the compiler to treat the value as used
    @as(*volatile usize, @ptrCast(@constCast(&volatile_sink))).* +%= @intFromPtr(val.ptr);
}

pub fn main() !void {
    const alloc = std.heap.c_allocator;

    var router = Router.init(alloc);
    defer router.deinit();

    // Same 16 routes as the original bench
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

    print("\n", .{});
    print("ADVERSARIAL router benchmark\n", .{});
    print("══════════════════════════════════════════════════════════\n\n", .{});

    // ── TEST 1: Verify correctness first ──────────────────────────────────
    print("  Test 1: Correctness verification\n", .{});
    {
        // Static match
        var m = router.findRoute("GET", "/health") orelse @panic("FAIL: /health not found");
        defer m.deinit();
        std.debug.assert(std.mem.eql(u8, m.handler_key, "GET /health"));

        // Param extraction
        var m2 = router.findRoute("GET", "/api/v1/users/42") orelse @panic("FAIL: /users/42 not found");
        defer m2.deinit();
        std.debug.assert(std.mem.eql(u8, m2.handler_key, "GET /api/v1/users/{id}"));
        std.debug.assert(std.mem.eql(u8, m2.params.get("id").?, "42"));

        // Multi-param
        var m3 = router.findRoute("GET", "/api/v1/users/42/posts/7") orelse @panic("FAIL: multi-param not found");
        defer m3.deinit();
        std.debug.assert(std.mem.eql(u8, m3.params.get("id").?, "42"));
        std.debug.assert(std.mem.eql(u8, m3.params.get("post_id").?, "7"));

        // Miss
        std.debug.assert(router.findRoute("GET", "/nonexistent") == null);

        // Method mismatch
        std.debug.assert(router.findRoute("PATCH", "/health") == null);

        print("    PASS — all correctness checks passed\n\n", .{});
    }

    // ── TEST 2: Anti-DCE — force use of every result ──────────────────────
    print("  Test 2: Anti-DCE (prevent dead code elimination)\n", .{});
    {
        const iters: u64 = 5_000_000;
        var checksum: usize = 0;
        var match_count: usize = 0;
        var miss_count: usize = 0;

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

        // Warmup
        for (0..100_000) |_| {
            for (lookups) |l| {
                if (router.findRoute(l[0], l[1])) |m_c| {
                    var m = m_c;
                    defer m.deinit();
                    checksum +%= m.handler_key.len;
                }
            }
        }

        checksum = 0;
        match_count = 0;
        miss_count = 0;
        var total: u64 = 0;
        var timer = std.time.Timer.start() catch unreachable;

        for (0..iters) |_| {
            for (lookups) |l| {
                if (router.findRoute(l[0], l[1])) |m_c| {
                    var m = m_c;
                    // Force use of handler_key AND params to prevent DCE
                    checksum +%= m.handler_key.len;
                    checksum +%= m.params.len;
                    if (m.params.len > 0) {
                        checksum +%= m.params.items_buf[0].value.len;
                    }
                    m.deinit();
                    match_count += 1;
                } else {
                    miss_count += 1;
                }
                total += 1;
            }
        }

        const elapsed_ns = timer.read();
        const ns_per_op = elapsed_ns / total;
        const ops_per_sec = if (ns_per_op > 0) 1_000_000_000 / ns_per_op else 0;

        print("    {d} lookups/sec   {d}ns avg\n", .{ ops_per_sec, ns_per_op });
        print("    checksum={d} matches={d} misses={d} (anti-DCE)\n", .{ checksum, match_count, miss_count });
        print("    expected: 12 matches + 1 miss per iteration\n\n", .{});
    }

    // ── TEST 3: Runtime-generated paths (defeat string interning) ─────────
    print("  Test 3: Runtime-generated paths (no string literal reuse)\n", .{});
    {
        const iters: u64 = 2_000_000;
        var checksum: usize = 0;
        var total: u64 = 0;

        // Generate paths at runtime so the compiler can't intern them
        var path_buf: [256]u8 = undefined;

        var timer = std.time.Timer.start() catch unreachable;

        for (0..iters) |i| {
            // /api/v1/users/{varying_id}
            const id_len = std.fmt.bufPrint(&path_buf, "/api/v1/users/{d}", .{i % 10000}) catch continue;
            if (router.findRoute("GET", id_len)) |m_c| {
                var m = m_c;
                checksum +%= m.handler_key.len;
                checksum +%= m.params.items_buf[0].value.len;
                m.deinit();
            }
            total += 1;

            // /api/v1/users/{id}/posts/{post_id}
            const multi_len = std.fmt.bufPrint(&path_buf, "/api/v1/users/{d}/posts/{d}", .{ i % 10000, i % 100 }) catch continue;
            if (router.findRoute("GET", multi_len)) |m_c| {
                var m = m_c;
                checksum +%= m.handler_key.len;
                m.deinit();
            }
            total += 1;

            // /api/v1/items/{cat}/{id}
            const items_len = std.fmt.bufPrint(&path_buf, "/api/v1/items/cat{d}/{d}", .{ i % 50, i % 1000 }) catch continue;
            if (router.findRoute("GET", items_len)) |m_c| {
                var m = m_c;
                checksum +%= m.handler_key.len;
                m.deinit();
            }
            total += 1;

            // Static (should still be fast)
            if (router.findRoute("GET", "/health")) |m_c| {
                var m = m_c;
                checksum +%= m.handler_key.len;
                m.deinit();
            }
            total += 1;

            // Miss
            const miss_len = std.fmt.bufPrint(&path_buf, "/nope/{d}", .{i}) catch continue;
            _ = router.findRoute("GET", miss_len);
            total += 1;
        }

        const elapsed_ns = timer.read();
        const ns_per_op = elapsed_ns / total;
        const ops_per_sec = if (ns_per_op > 0) 1_000_000_000 / ns_per_op else 0;

        print("    {d} lookups/sec   {d}ns avg\n", .{ ops_per_sec, ns_per_op });
        print("    checksum={d} (anti-DCE, runtime paths)\n\n", .{checksum});
    }

    // ── TEST 4: Large route table (100 routes) ────────────────────────────
    print("  Test 4: Large route table (100 routes)\n", .{});
    {
        var big_router = Router.init(alloc);
        defer big_router.deinit();

        // Register 100 routes with various patterns
        var name_buf: [128]u8 = undefined;
        for (0..20) |ns| {
            for ([_][]const u8{ "GET", "POST", "PUT", "DELETE", "PATCH" }) |method| {
                const path = std.fmt.bufPrint(&name_buf, "/api/v{d}/resource{d}/{{id}}", .{ ns % 5, ns }) catch continue;
                const key = std.fmt.allocPrint(alloc, "{s} {s}", .{ method, path }) catch continue;
                big_router.addRoute(method, path, key) catch continue;
            }
        }

        const iters: u64 = 2_000_000;
        var checksum: usize = 0;
        var total: u64 = 0;
        var path_buf2: [256]u8 = undefined;

        var timer = std.time.Timer.start() catch unreachable;

        for (0..iters) |i| {
            const ns = i % 20;
            const path = std.fmt.bufPrint(&path_buf2, "/api/v{d}/resource{d}/{d}", .{ ns % 5, ns, i % 10000 }) catch continue;
            if (big_router.findRoute("GET", path)) |m_c| {
                var m = m_c;
                checksum +%= m.handler_key.len;
                m.deinit();
            }
            total += 1;
        }

        const elapsed_ns = timer.read();
        const ns_per_op = elapsed_ns / total;
        const ops_per_sec = if (ns_per_op > 0) 1_000_000_000 / ns_per_op else 0;

        print("    100 routes registered\n", .{});
        print("    {d} lookups/sec   {d}ns avg\n", .{ ops_per_sec, ns_per_op });
        print("    checksum={d} (anti-DCE)\n\n", .{checksum});
    }

    // ── SUMMARY ───────────────────────────────────────────────────────────
    print("══════════════════════════════════════════════════════════\n", .{});
    print("  If Test 2 and Test 3 show similar numbers, the bench is honest.\n", .{});
    print("  If Test 3 is much slower, string interning was inflating Test 2.\n", .{});
    print("  If Test 4 degrades badly, the trie doesn't scale to many routes.\n", .{});
    print("══════════════════════════════════════════════════════════\n\n", .{});
}
