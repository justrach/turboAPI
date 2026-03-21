// prerender.zig — Static Site Generation (SSG) for merjs.
// Inspired by Next.js pre-rendering: at build time, call each page's render(),
// write the resulting HTML to dist/. Pages opt in via `pub const prerender = true`.
//
// Usage: zig build prerender

const std = @import("std");
const mer = @import("mer");
const Router = @import("router.zig").Router;
const dispatch_mod = @import("dispatch.zig");

const log = std.log.scoped(.prerender);

pub fn run(alloc: std.mem.Allocator, router: *const Router) !void {
    // Clean and recreate dist/
    std.fs.cwd().deleteTree("dist") catch {};
    try std.fs.cwd().makePath("dist");

    var rendered: usize = 0;
    var skipped: usize = 0;

    for (router.routes) |route| {
        if (!route.prerender) {
            skipped += 1;
            continue;
        }

        var arena = std.heap.ArenaAllocator.init(alloc);
        defer arena.deinit();
        const arena_alloc = arena.allocator();

        // Call render via the router dispatch so layout wrapping applies.
        const req = mer.Request.init(arena_alloc, .GET, route.path);
        const response = dispatch_mod.dispatch(router.*, req);

        if (response.content_type != .html) {
            log.info("skip {s} (not HTML)", .{route.path});
            skipped += 1;
            continue;
        }

        // Map URL path → file path in dist/:
        //   "/"       → "dist/index.html"
        //   "/about"  → "dist/about.html"
        //   "/blog/x" → "dist/blog/x.html"
        const fs_path = try urlToFsPath(arena_alloc, route.path);

        // Ensure parent dirs exist.
        if (std.mem.lastIndexOfScalar(u8, fs_path, '/')) |sep| {
            try std.fs.cwd().makePath(fs_path[0..sep]);
        }

        const file = try std.fs.cwd().createFile(fs_path, .{});
        defer file.close();
        try file.writeAll(response.body);

        rendered += 1;
        log.info("{s} → {s} ({d} bytes)", .{ route.path, fs_path, response.body.len });
    }

    // Copy public/ assets into dist/ so the static export is self-contained.
    copyPublicDir(alloc) catch |err| {
        log.warn("could not copy public/ → dist/: {s}", .{@errorName(err)});
    };

    log.info("{d} page(s) pre-rendered, {d} skipped (SSR-only)", .{ rendered, skipped });
}

fn urlToFsPath(alloc: std.mem.Allocator, url_path: []const u8) ![]u8 {
    if (std.mem.eql(u8, url_path, "/")) {
        return alloc.dupe(u8, "dist/index.html");
    }
    const rel = if (url_path.len > 0 and url_path[0] == '/') url_path[1..] else url_path;
    return std.fmt.allocPrint(alloc, "dist/{s}.html", .{rel});
}

fn copyPublicDir(alloc: std.mem.Allocator) !void {
    var dir = try std.fs.cwd().openDir("public", .{ .iterate = true });
    defer dir.close();
    var it = dir.iterate();
    while (try it.next()) |entry| {
        if (entry.kind != .file) continue;
        if (std.mem.eql(u8, entry.name, ".gitkeep")) continue;
        const src_path = try std.fmt.allocPrint(alloc, "public/{s}", .{entry.name});
        defer alloc.free(src_path);
        const dst_path = try std.fmt.allocPrint(alloc, "dist/{s}", .{entry.name});
        defer alloc.free(dst_path);
        std.fs.cwd().copyFile(src_path, std.fs.cwd(), dst_path, .{}) catch |err| {
            log.warn("copy {s}: {s}", .{ entry.name, @errorName(err) });
        };
    }
}
