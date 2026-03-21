// watcher.zig — file-change detection + SSE hot-reload.
// Polls file mtimes every 300ms. Notifies SSE clients on any change.

const std = @import("std");

const log = std.log.scoped(.watcher);

pub const Client = struct {
    notified: std.atomic.Value(bool),

    pub fn init() Client {
        return .{ .notified = std.atomic.Value(bool).init(false) };
    }

    pub fn notify(self: *Client) void {
        self.notified.store(true, .release);
    }

    /// Spin-wait until notified (checks every 50ms).
    pub fn wait(self: *Client) void {
        while (!self.notified.load(.acquire)) {
            std.Thread.sleep(50 * std.time.ns_per_ms);
        }
    }
};

pub const Watcher = struct {
    allocator: std.mem.Allocator,
    watch_dir: []const u8,
    // std.ArrayList is unmanaged in 0.15 — pass allocator per call.
    clients: std.ArrayList(*Client),
    mutex: std.Thread.Mutex,
    mtimes: std.StringHashMap(i128),

    pub fn init(allocator: std.mem.Allocator, watch_dir: []const u8) Watcher {
        return .{
            .allocator = allocator,
            .watch_dir = watch_dir,
            .clients = .{},
            .mutex = .{},
            .mtimes = std.StringHashMap(i128).init(allocator),
        };
    }

    pub fn deinit(self: *Watcher) void {
        self.clients.deinit(self.allocator);
        var it = self.mtimes.iterator();
        while (it.next()) |entry| self.allocator.free(entry.key_ptr.*);
        self.mtimes.deinit();
    }

    pub fn addClient(self: *Watcher, client: *Client) !void {
        self.mutex.lock();
        defer self.mutex.unlock();
        try self.clients.append(self.allocator, client);
    }

    fn broadcast(self: *Watcher) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        for (self.clients.items) |c| c.notify();
        self.clients.clearRetainingCapacity();
    }

    /// Poll loop — run in a background thread.
    pub fn run(self: *Watcher) void {
        while (true) {
            std.Thread.sleep(300 * std.time.ns_per_ms);
            if (self.pollOnce()) {
                log.info("change detected — reloading", .{});
                self.broadcast();
            }
        }
    }

    fn pollOnce(self: *Watcher) bool {
        var changed = false;
        var dir = std.fs.cwd().openDir(self.watch_dir, .{ .iterate = true }) catch return false;
        defer dir.close();

        var walker = dir.walk(self.allocator) catch return false;
        defer walker.deinit();

        while (walker.next() catch null) |entry| {
            if (entry.kind != .file) continue;
            const stat = dir.statFile(entry.path) catch continue;
            const mtime = stat.mtime;

            if (self.mtimes.get(entry.path)) |prev| {
                if (mtime != prev) {
                    self.mtimes.put(entry.path, mtime) catch {};
                    changed = true;
                }
            } else {
                const key = self.allocator.dupe(u8, entry.path) catch continue;
                self.mtimes.put(key, mtime) catch {};
            }
        }
        return changed;
    }
};

/// Handle GET /_mer/events — blocks until a file changes, then sends SSE reload.
pub fn handleSse(
    watcher: *Watcher,
    alloc: std.mem.Allocator,
    std_req: *std.http.Server.Request,
) !void {
    var header_buf: [512]u8 = undefined;
    var bw = try std_req.respondStreaming(&header_buf, .{
        .respond_options = .{
            .status = .ok,
            .extra_headers = &.{
                .{ .name = "content-type", .value = "text/event-stream" },
                .{ .name = "cache-control", .value = "no-cache" },
                .{ .name = "connection", .value = "keep-alive" },
            },
        },
    });

    // Ping so the browser knows the stream is live.
    try bw.writer.writeAll(": connected\n\n");
    try bw.flush();

    const client = try alloc.create(Client);
    defer alloc.destroy(client);
    client.* = Client.init();
    try watcher.addClient(client);

    // Block until the watcher fires.
    client.wait();

    try bw.writer.writeAll("data: reload\n\n");
    try bw.end();
}
