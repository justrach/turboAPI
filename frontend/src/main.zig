// main.zig — CLI entry point.
// Usage:
//   zig build serve               (dev server on :3000, hot reload)
//   zig build serve -- --port 8080
//   zig build serve -- --no-dev   (disable hot reload)

const std = @import("std");
const Server = @import("server.zig").Server;
const Config = @import("server.zig").Config;
const ssr = @import("ssr.zig");
const watcher_mod = @import("watcher.zig");
const prerender = @import("prerender.zig");

const log = std.log.scoped(.main);

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa.deinit();
    const alloc = gpa.allocator();

    const args = try std.process.argsAlloc(alloc);
    defer std.process.argsFree(alloc, args);

    // Load .env before threads start — safe to read without mutex after this.
    @import("mer").loadDotenv(alloc);

    var config = Config{
        .host = "127.0.0.1",
        .port = 3000,
        .dev = true,
    };

    var do_prerender = false;

    var i: usize = 1;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--port") and i + 1 < args.len) {
            config.port = try std.fmt.parseInt(u16, args[i + 1], 10);
            i += 1;
        } else if (std.mem.eql(u8, args[i], "--host") and i + 1 < args.len) {
            config.host = args[i + 1];
            i += 1;
        } else if (std.mem.eql(u8, args[i], "--no-dev")) {
            config.dev = false;
        } else if (std.mem.eql(u8, args[i], "--verbose") or std.mem.eql(u8, args[i], "-v")) {
            config.verbose = true;
        } else if (std.mem.eql(u8, args[i], "--prerender")) {
            do_prerender = true;
        }
    }

    // Build router from generated routes.
    var router = ssr.buildRouter(alloc);
    defer router.deinit();

    // SSG mode: pre-render pages to dist/ and exit.
    if (do_prerender) {
        try prerender.run(alloc, &router);
        return;
    }

    // File watcher (dev mode only).
    var watcher = watcher_mod.Watcher.init(alloc, "app");
    defer watcher.deinit();

    if (config.dev) {
        const wt = try std.Thread.spawn(.{}, watcher_mod.Watcher.run, .{&watcher});
        wt.detach();
        log.info("hot reload active — watching app/", .{});
    }

    var server = Server.init(alloc, config, &router, if (config.dev) &watcher else null);
    try server.listen();
}
