// Zig HTTP client for faster-boto3.
// Based on nanobrew's pattern: std.http.Client with connection reuse,
// streaming body, stack-allocated header buffers.

const std = @import("std");
const Allocator = std.mem.Allocator;
const http = std.http;

pub const HttpResponse = struct {
    status: u16,
    headers_buf: []const u8,
    body: []const u8,
    allocator: Allocator,

    pub fn deinit(self: *HttpResponse) void {
        self.allocator.free(self.headers_buf);
        self.allocator.free(self.body);
    }
};

pub const HttpError = error{
    ConnectionFailed,
    RequestFailed,
    InvalidUrl,
    OutOfMemory,
};

/// Single HTTP request using nanobrew's pattern:
///   client.request() → sendBody/sendBodiless → receiveHead → reader.streamRemaining
pub fn doRequest(
    allocator: Allocator,
    client: *http.Client,
    method: http.Method,
    url: []const u8,
    extra_headers: []const http.Header,
    body: ?[]const u8,
) HttpError!HttpResponse {
    const uri = std.Uri.parse(url) catch return HttpError.InvalidUrl;

    var req = client.request(method, uri, .{
        .redirect_behavior = @enumFromInt(5),
        .extra_headers = extra_headers,
        .keep_alive = true,
    }) catch return HttpError.ConnectionFailed;

    // Send request
    if (body) |b| {
        req.transfer_encoding = .{ .content_length = b.len };
        var send_body = req.sendBody(&.{}) catch {
            req.deinit();
            return HttpError.RequestFailed;
        };
        send_body.writer.writeAll(b) catch {
            req.deinit();
            return HttpError.RequestFailed;
        };
        send_body.end() catch {
            req.deinit();
            return HttpError.RequestFailed;
        };
    } else {
        req.sendBodiless() catch {
            req.deinit();
            return HttpError.RequestFailed;
        };
    }

    // Receive response headers (stack buffer like nanobrew)
    var head_buf: [16384]u8 = undefined;
    var response = req.receiveHead(&head_buf) catch {
        req.deinit();
        return HttpError.RequestFailed;
    };

    const status_int: u16 = @intFromEnum(response.head.status);

    // Stream response body into allocated buffer
    var out: std.Io.Writer.Allocating = .init(allocator);
    var reader = response.reader(&.{});
    _ = reader.streamRemaining(&out.writer) catch {
        if (out.toOwnedSlice()) |s| allocator.free(s) else |_| {}
        req.deinit();
        return HttpError.RequestFailed;
    };
    const resp_body = out.toOwnedSlice() catch {
        req.deinit();
        return HttpError.OutOfMemory;
    };

    // Extract response headers
    var hdr_out: std.ArrayList(u8) = .empty;
    var hdr_iter = response.head.iterateHeaders();
    while (hdr_iter.next()) |h| {
        hdr_out.appendSlice(allocator, h.name) catch {
            allocator.free(resp_body);
            req.deinit();
            return HttpError.OutOfMemory;
        };
        hdr_out.appendSlice(allocator, ": ") catch {
            allocator.free(resp_body);
            req.deinit();
            return HttpError.OutOfMemory;
        };
        hdr_out.appendSlice(allocator, h.value) catch {
            allocator.free(resp_body);
            req.deinit();
            return HttpError.OutOfMemory;
        };
        hdr_out.appendSlice(allocator, "\r\n") catch {
            allocator.free(resp_body);
            req.deinit();
            return HttpError.OutOfMemory;
        };
    }

    const headers_str = hdr_out.toOwnedSlice(allocator) catch {
        allocator.free(resp_body);
        req.deinit();
        return HttpError.OutOfMemory;
    };

    req.deinit();

    return HttpResponse{
        .status = status_int,
        .headers_buf = headers_str,
        .body = resp_body,
        .allocator = allocator,
    };
}

/// Convenience: one-shot request (creates + destroys client).
pub fn request(
    allocator: Allocator,
    method_str: []const u8,
    url: []const u8,
    headers: []const [2][]const u8,
    body: ?[]const u8,
) HttpError!HttpResponse {
    const method: http.Method = if (std.mem.eql(u8, method_str, "GET"))
        .GET
    else if (std.mem.eql(u8, method_str, "PUT"))
        .PUT
    else if (std.mem.eql(u8, method_str, "POST"))
        .POST
    else if (std.mem.eql(u8, method_str, "DELETE"))
        .DELETE
    else if (std.mem.eql(u8, method_str, "HEAD"))
        .HEAD
    else if (std.mem.eql(u8, method_str, "PATCH"))
        .PATCH
    else
        .GET;

    // Convert [2][]const u8 pairs → http.Header
    var extra_headers: std.ArrayList(http.Header) = .empty;
    defer extra_headers.deinit(allocator);
    for (headers) |h| {
        extra_headers.append(allocator, .{ .name = h[0], .value = h[1] }) catch
            return HttpError.OutOfMemory;
    }

    var client = http.Client{ .allocator = allocator };
    defer client.deinit();

    return doRequest(allocator, &client, method, url, extra_headers.items, body);
}

// ── Batch: parallel requests via Zig threads ────────────────────────────────
// Each thread gets its own http.Client (not thread-safe, like nanobrew).
// All threads run in parallel, results collected into a shared array.

pub const BatchRequest = struct {
    method: http.Method,
    url: []const u8,
    headers: []const http.Header,
    body: ?[]const u8,
};

pub const BatchResult = struct {
    response: ?HttpResponse,
    err_msg: ?[]const u8,
};

fn batchWorker(allocator: Allocator, req: *const BatchRequest, result: *BatchResult) void {
    var client = http.Client{ .allocator = allocator };
    defer client.deinit();

    const resp = doRequest(allocator, &client, req.method, req.url, req.headers, req.body) catch |err| {
        result.* = .{
            .response = null,
            .err_msg = switch (err) {
                HttpError.ConnectionFailed => "connection failed",
                HttpError.RequestFailed => "request failed",
                HttpError.InvalidUrl => "invalid URL",
                HttpError.OutOfMemory => "out of memory",
            },
        };
        return;
    };
    result.* = .{ .response = resp, .err_msg = null };
}

pub fn requestBatch(
    allocator: Allocator,
    requests: []const BatchRequest,
) ![]BatchResult {
    const n = requests.len;
    const results = try allocator.alloc(BatchResult, n);
    @memset(results, .{ .response = null, .err_msg = null });

    if (n == 0) return results;

    // Single request — no thread overhead
    if (n == 1) {
        batchWorker(allocator, &requests[0], &results[0]);
        return results;
    }

    // Cap concurrency at 16 threads (like nanobrew), process in waves
    const max_workers = 16;

    var completed: usize = 0;
    while (completed < n) {
        const batch_end = @min(completed + max_workers, n);
        const wave_size = batch_end - completed;

        var threads: [16]?std.Thread = .{null} ** 16;
        var spawned: usize = 0;

        for (0..wave_size) |j| {
            const idx = completed + j;
            threads[j] = std.Thread.spawn(.{}, batchWorker, .{ allocator, &requests[idx], &results[idx] }) catch {
                // Fallback: run inline
                batchWorker(allocator, &requests[idx], &results[idx]);
                continue;
            };
            spawned += 1;
        }

        // Join this wave before starting next
        for (0..wave_size) |j| {
            if (threads[j]) |t| t.join();
        }

        completed = batch_end;
    }

    return results;
}
