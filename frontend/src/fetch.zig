// fetch.zig — SSR HTTP client (single + parallel fetch).

const std = @import("std");
const builtin = @import("builtin");

/// Options for a single HTTP request made during server-side rendering.
pub const FetchRequest = struct {
    url: []const u8,
    method: std.http.Method = .GET,
    body: ?[]const u8 = null,
    headers: []const std.http.Header = &.{},
};

/// Response from an HTTP fetch. Owns the body — call `deinit()` when done.
pub const FetchResponse = struct {
    status: std.http.Status,
    body: []u8,

    pub fn deinit(self: FetchResponse, allocator: std.mem.Allocator) void {
        allocator.free(self.body);
    }
};

// ── Freestanding (Workers) two-phase fetch state ─────────────────────────────

const wasm_alloc = if (builtin.os.tag == .freestanding)
    std.heap.wasm_allocator
else
    @as(std.mem.Allocator, undefined);

var wasm_collect_mode: bool = false;
var wasm_collected_urls: std.ArrayListUnmanaged([]const u8) = .{};
var wasm_fetch_cache: std.StringHashMapUnmanaged([]const u8) = .{};
var wasm_urls_buf: []const u8 = "";

/// Begin URL collection pass. fetchAll() will record URLs instead of fetching.
pub fn wasmBeginCollect() void {
    wasm_collect_mode = true;
    wasm_collected_urls.clearRetainingCapacity();
}

/// End collection pass. Returns newline-delimited URL list (WASM memory).
pub fn wasmEndCollect() []const u8 {
    wasm_collect_mode = false;
    if (wasm_urls_buf.len > 0) wasm_alloc.free(wasm_urls_buf);
    var buf: std.ArrayListUnmanaged(u8) = .{};
    for (wasm_collected_urls.items) |url| {
        buf.appendSlice(wasm_alloc, url) catch {};
        buf.append(wasm_alloc, '\n') catch {};
    }
    wasm_urls_buf = buf.toOwnedSlice(wasm_alloc) catch "";
    return wasm_urls_buf;
}

/// Store a pre-fetched result (called by JS before the render pass).
pub fn wasmProvideResult(url: []const u8, body: []const u8) void {
    const u = wasm_alloc.dupe(u8, url) catch return;
    const b = wasm_alloc.dupe(u8, body) catch return;
    wasm_fetch_cache.put(wasm_alloc, u, b) catch {};
}

/// Clear the fetch cache after rendering.
pub fn wasmClearCache() void {
    wasm_fetch_cache.clearRetainingCapacity();
}

/// Make an HTTP request from a server-side page handler.
pub fn fetch(allocator: std.mem.Allocator, opts: FetchRequest) !FetchResponse {
    if (comptime builtin.os.tag == .freestanding) return error.NotSupported;
    var client = std.http.Client{ .allocator = allocator };
    defer client.deinit();

    var collecting: std.io.Writer.Allocating = .init(allocator);
    defer collecting.deinit();

    const result = try client.fetch(.{
        .location = .{ .url = opts.url },
        .method = opts.method,
        .payload = opts.body,
        .extra_headers = opts.headers,
        .response_writer = &collecting.writer,
    });

    const raw = collecting.writer.buffer[0..collecting.writer.end];
    const owned = try allocator.dupe(u8, raw);
    return .{ .status = result.status, .body = owned };
}

fn fetchWorker(allocator: std.mem.Allocator, opts: FetchRequest, out: *?FetchResponse) void {
    out.* = fetch(allocator, opts) catch null;
}

/// Fetch multiple URLs in parallel. Returns results in the same order as inputs.
pub fn fetchAll(allocator: std.mem.Allocator, requests: []const FetchRequest) []?FetchResponse {
    const results = allocator.alloc(?FetchResponse, requests.len) catch return &.{};
    @memset(results, null);

    if (comptime builtin.os.tag == .freestanding) {
        if (wasm_collect_mode) {
            for (requests) |req_opts| {
                const url = wasm_alloc.dupe(u8, req_opts.url) catch continue;
                wasm_collected_urls.append(wasm_alloc, url) catch {};
            }
        } else {
            for (requests, 0..) |req_opts, i| {
                if (wasm_fetch_cache.get(req_opts.url)) |body| {
                    results[i] = .{ .status = .ok, .body = @constCast(body) };
                }
            }
        }
        return results;
    }

    if (comptime builtin.single_threaded) {
        for (requests, 0..) |req_opts, i| {
            results[i] = fetch(allocator, req_opts) catch null;
        }
        return results;
    }

    if (requests.len == 1) {
        results[0] = fetch(allocator, requests[0]) catch null;
        return results;
    }

    const threads = allocator.alloc(std.Thread, requests.len) catch return results;
    defer allocator.free(threads);

    const gpas = allocator.alloc(std.heap.GeneralPurposeAllocator(.{}), requests.len) catch return results;
    defer allocator.free(gpas);
    for (gpas) |*g| g.* = .init;

    for (requests, 0..) |req_opts, i| {
        threads[i] = std.Thread.spawn(.{}, fetchWorker, .{ gpas[i].allocator(), req_opts, &results[i] }) catch {
            results[i] = null;
            continue;
        };
    }

    for (threads[0..requests.len]) |t| t.join();

    for (results, 0..) |*r, i| {
        if (r.*) |resp| {
            const owned = allocator.dupe(u8, resp.body) catch {
                r.* = null;
                continue;
            };
            r.* = .{ .status = resp.status, .body = owned };
            gpas[i].allocator().free(resp.body);
        }
        _ = gpas[i].deinit();
    }

    return results;
}
