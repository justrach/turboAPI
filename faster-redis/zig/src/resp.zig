// RESP2/3 protocol parser — zero-allocation, SIMD-accelerated.
// Replaces redis-py's pure Python _RESP2Parser and competes with hiredis.
//
// RESP format:
//   +OK\r\n                      → Simple string
//   -ERR msg\r\n                 → Error
//   :42\r\n                      → Integer
//   $5\r\nhello\r\n              → Bulk string (length-prefixed)
//   *3\r\n$3\r\nSET\r\n...      → Array
//   _\r\n                        → Null (RESP3)
//   #t\r\n / #f\r\n              → Boolean (RESP3)

const std = @import("std");
const Allocator = std.mem.Allocator;

// ── SIMD helpers ────────────────────────────────────────────────────────────

const simd_w = 16; // NEON on aarch64, SSE2 on x86_64
const Vec = @Vector(simd_w, u8);
const BoolVec = @Vector(simd_w, bool);
const MaskInt = std.meta.Int(.unsigned, simd_w);

/// Find \r\n in buffer using SIMD — scans for \r then checks \n follows.
fn findCRLF(data: []const u8) ?usize {
    const cr: Vec = @splat('\r');
    var offset: usize = 0;

    while (offset + simd_w <= data.len) : (offset += simd_w) {
        const chunk: Vec = data[offset..][0..simd_w].*;
        const eq: BoolVec = chunk == cr;
        var mask: MaskInt = @bitCast(eq);
        while (mask != 0) {
            const bit: u5 = @intCast(@ctz(mask));
            const pos = offset + bit;
            if (pos + 1 < data.len and data[pos + 1] == '\n') {
                return pos;
            }
            mask &= mask - 1;
        }
    }

    // Scalar tail
    while (offset + 1 < data.len) : (offset += 1) {
        if (data[offset] == '\r' and data[offset + 1] == '\n') return offset;
    }
    return null;
}

// ── RESP Value types ────────────────────────────────────────────────────────

pub const RespType = enum {
    simple_string,
    error_string,
    integer,
    bulk_string,
    array,
    null_value,
    boolean,
};

pub const RespValue = struct {
    type: RespType,
    // For strings/errors: slice into the original buffer (zero-copy)
    str_val: []const u8 = "",
    // For integers
    int_val: i64 = 0,
    // For booleans
    bool_val: bool = false,
    // For arrays: allocated slice of child values
    array_val: []RespValue = &.{},
};

pub const ParseError = error{
    Incomplete, // Need more data
    Invalid, // Protocol violation
    OutOfMemory,
};

pub const ParseResult = struct {
    value: RespValue,
    consumed: usize, // Bytes consumed from input
};

// ── Parser ──────────────────────────────────────────────────────────────────

/// Parse a single RESP value from buffer. Returns the value and bytes consumed.
/// Strings are zero-copy slices into the input buffer.
pub fn parse(allocator: Allocator, data: []const u8) ParseError!ParseResult {
    if (data.len == 0) return ParseError.Incomplete;

    return switch (data[0]) {
        '+' => parseSimpleString(data),
        '-' => parseErrorString(data),
        ':' => parseInteger(data),
        '$' => parseBulkString(data),
        '*' => parseArray(allocator, data),
        '_' => parseNull(data),
        '#' => parseBoolean(data),
        else => ParseError.Invalid,
    };
}

fn parseSimpleString(data: []const u8) ParseError!ParseResult {
    const crlf = findCRLF(data[1..]) orelse return ParseError.Incomplete;
    return .{
        .value = .{ .type = .simple_string, .str_val = data[1 .. 1 + crlf] },
        .consumed = 1 + crlf + 2,
    };
}

fn parseErrorString(data: []const u8) ParseError!ParseResult {
    const crlf = findCRLF(data[1..]) orelse return ParseError.Incomplete;
    return .{
        .value = .{ .type = .error_string, .str_val = data[1 .. 1 + crlf] },
        .consumed = 1 + crlf + 2,
    };
}

fn parseInteger(data: []const u8) ParseError!ParseResult {
    const crlf = findCRLF(data[1..]) orelse return ParseError.Incomplete;
    const num_str = data[1 .. 1 + crlf];
    const val = std.fmt.parseInt(i64, num_str, 10) catch return ParseError.Invalid;
    return .{
        .value = .{ .type = .integer, .int_val = val },
        .consumed = 1 + crlf + 2,
    };
}

fn parseBulkString(data: []const u8) ParseError!ParseResult {
    const crlf = findCRLF(data[1..]) orelse return ParseError.Incomplete;
    const len_str = data[1 .. 1 + crlf];
    const len = std.fmt.parseInt(i64, len_str, 10) catch return ParseError.Invalid;

    // $-1\r\n → null
    if (len < 0) {
        return .{
            .value = .{ .type = .null_value },
            .consumed = 1 + crlf + 2,
        };
    }

    const ulen: usize = @intCast(len);
    const start = 1 + crlf + 2;
    if (data.len < start + ulen + 2) return ParseError.Incomplete;

    return .{
        .value = .{ .type = .bulk_string, .str_val = data[start .. start + ulen] },
        .consumed = start + ulen + 2,
    };
}

fn parseArray(allocator: Allocator, data: []const u8) ParseError!ParseResult {
    const crlf = findCRLF(data[1..]) orelse return ParseError.Incomplete;
    const count_str = data[1 .. 1 + crlf];
    const count = std.fmt.parseInt(i64, count_str, 10) catch return ParseError.Invalid;

    // *-1\r\n → null array
    if (count < 0) {
        return .{
            .value = .{ .type = .null_value },
            .consumed = 1 + crlf + 2,
        };
    }

    const ucount: usize = @intCast(count);
    const items = allocator.alloc(RespValue, ucount) catch return ParseError.OutOfMemory;

    var pos: usize = 1 + crlf + 2;
    for (0..ucount) |i| {
        if (pos >= data.len) {
            allocator.free(items);
            return ParseError.Incomplete;
        }
        const result = try parse(allocator, data[pos..]);
        items[i] = result.value;
        pos += result.consumed;
    }

    return .{
        .value = .{ .type = .array, .array_val = items },
        .consumed = pos,
    };
}

fn parseNull(data: []const u8) ParseError!ParseResult {
    if (data.len < 3) return ParseError.Incomplete;
    return .{
        .value = .{ .type = .null_value },
        .consumed = 3, // _\r\n
    };
}

fn parseBoolean(data: []const u8) ParseError!ParseResult {
    if (data.len < 4) return ParseError.Incomplete;
    return .{
        .value = .{ .type = .boolean, .bool_val = data[1] == 't' },
        .consumed = 4, // #t\r\n
    };
}

// ── Command packing ─────────────────────────────────────────────────────────

/// Pack a Redis command into RESP format. Returns owned buffer.
/// Example: packCommand(alloc, &.{"SET", "key", "value"})
///   → "*3\r\n$3\r\nSET\r\n$3\r\nkey\r\n$5\r\nvalue\r\n"
pub fn packCommand(allocator: Allocator, args: []const []const u8) ![]u8 {
    // Pre-calculate total size to avoid reallocations
    var total: usize = 0;
    // *N\r\n header
    total += 1 + countDigits(args.len) + 2;
    for (args) |arg| {
        // $len\r\narg\r\n
        total += 1 + countDigits(arg.len) + 2 + arg.len + 2;
    }

    const buf = try allocator.alloc(u8, total);
    var pos: usize = 0;

    // *N\r\n
    buf[pos] = '*';
    pos += 1;
    pos += writeInt(buf[pos..], args.len);
    buf[pos] = '\r';
    buf[pos + 1] = '\n';
    pos += 2;

    for (args) |arg| {
        // $len\r\n
        buf[pos] = '$';
        pos += 1;
        pos += writeInt(buf[pos..], arg.len);
        buf[pos] = '\r';
        buf[pos + 1] = '\n';
        pos += 2;
        // arg\r\n
        @memcpy(buf[pos..][0..arg.len], arg);
        pos += arg.len;
        buf[pos] = '\r';
        buf[pos + 1] = '\n';
        pos += 2;
    }

    return buf;
}

/// Pack multiple commands for pipelining. Returns single buffer.
pub fn packPipeline(allocator: Allocator, commands: []const []const []const u8) ![]u8 {
    var total: usize = 0;
    for (commands) |args| {
        total += 1 + countDigits(args.len) + 2;
        for (args) |arg| {
            total += 1 + countDigits(arg.len) + 2 + arg.len + 2;
        }
    }

    const buf = try allocator.alloc(u8, total);
    var pos: usize = 0;

    for (commands) |args| {
        buf[pos] = '*';
        pos += 1;
        pos += writeInt(buf[pos..], args.len);
        buf[pos] = '\r';
        buf[pos + 1] = '\n';
        pos += 2;
        for (args) |arg| {
            buf[pos] = '$';
            pos += 1;
            pos += writeInt(buf[pos..], arg.len);
            buf[pos] = '\r';
            buf[pos + 1] = '\n';
            pos += 2;
            @memcpy(buf[pos..][0..arg.len], arg);
            pos += arg.len;
            buf[pos] = '\r';
            buf[pos + 1] = '\n';
            pos += 2;
        }
    }

    return buf;
}

fn countDigits(n: usize) usize {
    if (n == 0) return 1;
    var v = n;
    var d: usize = 0;
    while (v > 0) : (v /= 10) d += 1;
    return d;
}

fn writeInt(buf: []u8, n: usize) usize {
    var tmp: [20]u8 = undefined;
    const s = std.fmt.bufPrint(&tmp, "{d}", .{n}) catch return 0;
    @memcpy(buf[0..s.len], s);
    return s.len;
}

// ── Tests ───────────────────────────────────────────────────────────────────

test "parse simple string" {
    const result = try parse(std.testing.allocator, "+OK\r\n");
    try std.testing.expectEqualStrings("OK", result.value.str_val);
    try std.testing.expectEqual(@as(usize, 5), result.consumed);
}

test "parse error" {
    const result = try parse(std.testing.allocator, "-ERR unknown\r\n");
    try std.testing.expectEqual(RespType.error_string, result.value.type);
    try std.testing.expectEqualStrings("ERR unknown", result.value.str_val);
}

test "parse integer" {
    const result = try parse(std.testing.allocator, ":42\r\n");
    try std.testing.expectEqual(@as(i64, 42), result.value.int_val);
}

test "parse negative integer" {
    const result = try parse(std.testing.allocator, ":-1\r\n");
    try std.testing.expectEqual(@as(i64, -1), result.value.int_val);
}

test "parse bulk string" {
    const result = try parse(std.testing.allocator, "$5\r\nhello\r\n");
    try std.testing.expectEqualStrings("hello", result.value.str_val);
    try std.testing.expectEqual(@as(usize, 11), result.consumed);
}

test "parse null bulk string" {
    const result = try parse(std.testing.allocator, "$-1\r\n");
    try std.testing.expectEqual(RespType.null_value, result.value.type);
}

test "parse array" {
    const data = "*2\r\n$3\r\nfoo\r\n$3\r\nbar\r\n";
    const result = try parse(std.testing.allocator, data);
    defer std.testing.allocator.free(result.value.array_val);
    try std.testing.expectEqual(@as(usize, 2), result.value.array_val.len);
    try std.testing.expectEqualStrings("foo", result.value.array_val[0].str_val);
    try std.testing.expectEqualStrings("bar", result.value.array_val[1].str_val);
}

test "parse empty array" {
    const result = try parse(std.testing.allocator, "*0\r\n");
    defer std.testing.allocator.free(result.value.array_val);
    try std.testing.expectEqual(@as(usize, 0), result.value.array_val.len);
}

test "parse incomplete returns error" {
    const result = parse(std.testing.allocator, "$5\r\nhel");
    try std.testing.expectError(ParseError.Incomplete, result);
}

test "packCommand SET" {
    const cmd = try packCommand(std.testing.allocator, &.{ "SET", "key", "value" });
    defer std.testing.allocator.free(cmd);
    try std.testing.expectEqualStrings("*3\r\n$3\r\nSET\r\n$3\r\nkey\r\n$5\r\nvalue\r\n", cmd);
}

test "packCommand GET" {
    const cmd = try packCommand(std.testing.allocator, &.{ "GET", "mykey" });
    defer std.testing.allocator.free(cmd);
    try std.testing.expectEqualStrings("*2\r\n$3\r\nGET\r\n$5\r\nmykey\r\n", cmd);
}

test "findCRLF basic" {
    try std.testing.expectEqual(@as(?usize, 5), findCRLF("hello\r\nworld"));
    try std.testing.expectEqual(@as(?usize, 0), findCRLF("\r\n"));
    try std.testing.expectEqual(@as(?usize, null), findCRLF("no newline here"));
}

test "findCRLF long string" {
    // Test SIMD path (>16 bytes)
    const data = "a" ** 32 ++ "\r\n" ++ "b" ** 10;
    try std.testing.expectEqual(@as(?usize, 32), findCRLF(data));
}
