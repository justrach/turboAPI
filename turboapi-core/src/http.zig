// HTTP utility functions — pure, zero-dependency helpers for HTTP parsing.

const std = @import("std");

/// Fast query-string value lookup. Format: "k1=v1&k2=v2&...".
/// No percent-decoding (fine for int/float/simple str params in hot path).
pub fn queryStringGet(qs: []const u8, key: []const u8) ?[]const u8 {
    var it = std.mem.splitScalar(u8, qs, '&');
    while (it.next()) |pair| {
        const eq = std.mem.indexOfScalar(u8, pair, '=') orelse continue;
        if (std.mem.eql(u8, pair[0..eq], key)) return pair[eq + 1 ..];
    }
    return null;
}

pub fn hexNibble(ch: u8) ?u8 {
    return switch (ch) {
        '0'...'9' => ch - '0',
        'a'...'f' => ch - 'a' + 10,
        'A'...'F' => ch - 'A' + 10,
        else => null,
    };
}

/// Percent-decode src into buf. '+' → space, '%XX' → byte. Returns decoded slice.
/// If buf is too small, copies as many bytes as fit (safe truncation).
pub fn percentDecode(src: []const u8, buf: []u8) []u8 {
    var out: usize = 0;
    var i: usize = 0;
    while (i < src.len and out < buf.len) {
        if (src[i] == '+') {
            buf[out] = ' ';
            out += 1;
            i += 1;
        } else if (src[i] == '%' and i + 2 < src.len) {
            const hi = hexNibble(src[i + 1]);
            const lo = hexNibble(src[i + 2]);
            if (hi != null and lo != null) {
                buf[out] = (hi.? << 4) | lo.?;
                out += 1;
                i += 3;
            } else {
                buf[out] = src[i];
                out += 1;
                i += 1;
            }
        } else {
            buf[out] = src[i];
            out += 1;
            i += 1;
        }
    }
    return buf[0..out];
}

pub fn statusText(status: u16) []const u8 {
    return switch (status) {
        200 => "OK",
        201 => "Created",
        204 => "No Content",
        301 => "Moved Permanently",
        302 => "Found",
        304 => "Not Modified",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        405 => "Method Not Allowed",
        413 => "Payload Too Large",
        422 => "Unprocessable Entity",
        429 => "Too Many Requests",
        431 => "Request Header Fields Too Large",
        500 => "Internal Server Error",
        502 => "Bad Gateway",
        503 => "Service Unavailable",
        else => "Unknown",
    };
}

/// Format an RFC 2822 HTTP Date header value into buf.
/// Returns the formatted slice (e.g. "Wed, 19 Mar 2026 11:30:27 GMT").
pub fn formatHttpDate(buf: *[40]u8) []const u8 {
    const ts = std.time.timestamp();
    const es: std.time.epoch.EpochSeconds = .{ .secs = @intCast(ts) };
    const ds = es.getDaySeconds();
    const ed = es.getEpochDay();
    const yd = ed.calculateYearDay();
    const md = yd.calculateMonthDay();
    const di: usize = @intCast(@mod(@as(i32, @intCast(ed.day)) + 3, 7));
    const dw = [7][]const u8{ "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun" };
    const mn = [12][]const u8{ "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" };
    return std.fmt.bufPrint(buf, "{s}, {d:0>2} {s} {d} {d:0>2}:{d:0>2}:{d:0>2} GMT", .{
        dw[di], md.day_index + 1, mn[@intFromEnum(md.month) - 1], yd.year,
        ds.getHoursIntoDay(), ds.getMinutesIntoHour(), ds.getSecondsIntoMinute(),
    }) catch "Thu, 01 Jan 2026 00:00:00 GMT";
}

// ── Tests ───────────────────────────────────────────────────────────────────

test "queryStringGet basic" {
    try std.testing.expectEqualStrings("bar", queryStringGet("foo=bar&baz=qux", "foo").?);
    try std.testing.expectEqualStrings("qux", queryStringGet("foo=bar&baz=qux", "baz").?);
    try std.testing.expect(queryStringGet("foo=bar", "missing") == null);
    try std.testing.expect(queryStringGet("", "foo") == null);
}

test "percentDecode basic" {
    var buf: [256]u8 = undefined;
    try std.testing.expectEqualStrings("hello world", percentDecode("hello+world", &buf));
    try std.testing.expectEqualStrings("a/b", percentDecode("a%2Fb", &buf));
    try std.testing.expectEqualStrings("100%", percentDecode("100%25", &buf));
    try std.testing.expectEqualStrings("noop", percentDecode("noop", &buf));
}

test "hexNibble" {
    try std.testing.expectEqual(@as(?u8, 0), hexNibble('0'));
    try std.testing.expectEqual(@as(?u8, 9), hexNibble('9'));
    try std.testing.expectEqual(@as(?u8, 10), hexNibble('a'));
    try std.testing.expectEqual(@as(?u8, 15), hexNibble('F'));
    try std.testing.expectEqual(@as(?u8, null), hexNibble('g'));
}

test "statusText" {
    try std.testing.expectEqualStrings("OK", statusText(200));
    try std.testing.expectEqualStrings("Not Found", statusText(404));
    try std.testing.expectEqualStrings("Internal Server Error", statusText(500));
    try std.testing.expectEqualStrings("Unknown", statusText(999));
}

test "formatHttpDate returns valid format" {
    var buf: [40]u8 = undefined;
    const date = formatHttpDate(&buf);
    // Should contain "GMT" at the end
    try std.testing.expect(std.mem.endsWith(u8, date, "GMT"));
    // Should be reasonable length (29 chars for RFC 2822)
    try std.testing.expect(date.len >= 28);
}

// ── Fuzz tests ──────────────────────────────────────────────────────────────

fn fuzz_percentDecode(_: void, input: []const u8) anyerror!void {
    var out: [4096]u8 = undefined;
    const buf = if (input.len > 0) input[0..@min(input.len, 4096)] else input;
    const result = percentDecode(buf, &out);

    // Output must not exceed input length
    const buf_start = @intFromPtr(&out);
    const buf_end = buf_start + out.len;
    const out_start = @intFromPtr(result.ptr);
    try std.testing.expect(out_start >= buf_start and out_start <= buf_end);
}

test "fuzz: percentDecode — output bounded, no OOB" {
    try std.testing.fuzz({}, fuzz_percentDecode, .{ .corpus = &.{
        "%00",
        "%zz",
        "hello+world",
        "%",
        "%%",
        "%2",
        "%2G",
        "normal",
        "",
    }});
}

fn fuzz_queryStringGet(_: void, input: []const u8) anyerror!void {
    if (input.len < 2) return;
    const split = input[0] % @as(u8, @intCast(@min(input.len, 255)));
    const key = input[1..@min(@as(usize, split) + 1, input.len)];
    const qs = if (@as(usize, split) + 1 < input.len) input[@as(usize, split) + 1 ..] else "";

    const result = queryStringGet(qs, key);
    if (result) |v| {
        // Value must be a subslice of qs
        const qs_start = @intFromPtr(qs.ptr);
        const qs_end = qs_start + qs.len;
        const v_start = @intFromPtr(v.ptr);
        try std.testing.expect(v_start >= qs_start and v_start + v.len <= qs_end);
    }
}

test "fuzz: queryStringGet — result is within input, no panic" {
    try std.testing.fuzz({}, fuzz_queryStringGet, .{ .corpus = &.{
        "\x03foo=bar",
        "\x00=",
        "\x01a&b=c",
        "\x00",
    }});
}
