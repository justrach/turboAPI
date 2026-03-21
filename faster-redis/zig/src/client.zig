// Zig Redis client — pipelined, connection-pooled, zero-allocation parsing.
// Replaces redis-py's Connection + Parser with native Zig I/O.

const std = @import("std");
const net = std.net;
const resp = @import("resp.zig");
const Allocator = std.mem.Allocator;

pub const RedisError = error{
    ConnectionFailed,
    SendFailed,
    RecvFailed,
    ProtocolError,
    AuthFailed,
    OutOfMemory,
};

pub const RedisClient = struct {
    allocator: Allocator,
    stream: ?net.Stream = null,
    host: []const u8,
    port: u16,
    read_buf: [65536]u8 = undefined,
    read_pos: usize = 0,
    read_len: usize = 0,

    pub fn init(allocator: Allocator, host: []const u8, port: u16) RedisClient {
        return .{
            .allocator = allocator,
            .host = host,
            .port = port,
        };
    }

    pub fn deinit(self: *RedisClient) void {
        if (self.stream) |s| s.close();
        self.stream = null;
    }

    pub fn connect(self: *RedisClient) RedisError!void {
        if (self.stream != null) return;

        const addr = net.Address.resolveIp(self.host, self.port) catch
            return RedisError.ConnectionFailed;
        self.stream = net.tcpConnectToAddress(addr) catch
            return RedisError.ConnectionFailed;

        // TCP_NODELAY for low latency
        if (self.stream) |s| {
            std.posix.setsockopt(s.handle, std.posix.IPPROTO.TCP, std.posix.TCP.NODELAY, &std.mem.toBytes(@as(c_int, 1))) catch {};
        }
    }

    /// Send a single command and read the response.
    pub fn command(self: *RedisClient, args: []const []const u8) RedisError!resp.RespValue {
        const cmd_buf = resp.packCommand(self.allocator, args) catch return RedisError.OutOfMemory;
        defer self.allocator.free(cmd_buf);

        self.send(cmd_buf) catch return RedisError.SendFailed;

        self.send(cmd_buf) catch return RedisError.SendFailed;
        return self.readResponse() catch return RedisError.ProtocolError;
    }

    /// Send multiple commands in a pipeline, read all responses.
    pub fn pipeline(self: *RedisClient, commands: []const []const []const u8) RedisError![]resp.RespValue {
        try self.connect();
        const pipe_buf = resp.packPipeline(self.allocator, commands) catch return RedisError.OutOfMemory;
        defer self.allocator.free(pipe_buf);

        self.send(pipe_buf) catch return RedisError.SendFailed;

        const results = self.allocator.alloc(resp.RespValue, commands.len) catch return RedisError.OutOfMemory;
        for (0..commands.len) |i| {
            results[i] = self.readResponse() catch return RedisError.ProtocolError;
        }
        return results;
    }

    /// Authenticate with password.
    pub fn auth(self: *RedisClient, password: []const u8) RedisError!void {
        const result = try self.command(&.{ "AUTH", password });
        if (result.type == .error_string) return RedisError.AuthFailed;
    }

    /// Select database.
    pub fn selectDb(self: *RedisClient, db: []const u8) RedisError!void {
        _ = try self.command(&.{ "SELECT", db });
    }

    // ── Internal I/O ────────────────────────────────────────────────

    fn send(self: *RedisClient, data: []const u8) !void {
        const s = self.stream orelse return error.NotConnected;
        var sent: usize = 0;
        while (sent < data.len) {
            sent += s.write(data[sent..]) catch return error.BrokenPipe;
        }
    }

    fn readResponse(self: *RedisClient) !resp.RespValue {
        while (true) {
            // Try to parse from existing buffer
            if (self.read_len > self.read_pos) {
                const buf = self.read_buf[self.read_pos..self.read_len];
                if (resp.parse(self.allocator, buf)) |result| {
                    self.read_pos += result.consumed;
                    // Compact buffer if mostly consumed
                    if (self.read_pos > self.read_buf.len / 2) {
                        const remaining = self.read_len - self.read_pos;
                        if (remaining > 0) {
                            std.mem.copyForwards(u8, &self.read_buf, self.read_buf[self.read_pos..self.read_len]);
                        }
                        self.read_len = remaining;
                        self.read_pos = 0;
                    }
                    return result.value;
                } else |err| {
                    if (err != resp.ParseError.Incomplete) return err;
                    // Need more data — fall through to recv
                }
            }

            // Read more data from socket
            const s = self.stream orelse return error.NotConnected;
            if (self.read_len >= self.read_buf.len) {
                // Buffer full, compact
                const remaining = self.read_len - self.read_pos;
                if (remaining > 0) {
                    std.mem.copyForwards(u8, &self.read_buf, self.read_buf[self.read_pos..self.read_len]);
                }
                self.read_len = remaining;
                self.read_pos = 0;
            }
            const n = s.read(self.read_buf[self.read_len..]) catch return error.BrokenPipe;
            if (n == 0) return error.EndOfStream;
            self.read_len += n;
        }
    }
};

// ── Tests ───────────────────────────────────────────────────────────────────

test "packCommand roundtrip" {
    const cmd = try resp.packCommand(std.testing.allocator, &.{ "PING" });
    defer std.testing.allocator.free(cmd);
    try std.testing.expectEqualStrings("*1\r\n$4\r\nPING\r\n", cmd);
}
