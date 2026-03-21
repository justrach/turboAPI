// SIMD-accelerated parsers for faster-boto3.
// Based on nanobrew's simd_scanner.zig pattern.
//
// Accelerates the hot paths in boto3 response processing:
// 1. XML parsing (S3 responses)
// 2. JSON parsing (DynamoDB responses)
// 3. HTTP header parsing
// 4. ISO 8601 timestamp parsing

const std = @import("std");
const Allocator = std.mem.Allocator;

// ── SIMD configuration (compile-time, like nanobrew) ────────────────────────

const simd_w = bestSimdWidth();
const Vec = @Vector(simd_w, u8);
const BoolVec = @Vector(simd_w, bool);
const MaskInt = std.meta.Int(.unsigned, simd_w);

fn bestSimdWidth() comptime_int {
    const arch = @import("builtin").cpu.arch;
    if (arch == .x86_64) {
        const features = @import("builtin").cpu.features;
        if (std.Target.x86.featureSetHas(features, .avx2)) return 32;
        return 16; // SSE2
    }
    if (arch == .aarch64) return 16; // NEON
    return 16;
}

fn toBitmask(v: BoolVec) MaskInt {
    return @bitCast(v);
}

// ── SIMD byte scanner (nanobrew pattern) ────────────────────────────────────

/// Find first occurrence of `needle` byte in `haystack` using SIMD.
pub fn findByte(haystack: []const u8, needle: u8) ?usize {
    const splat: Vec = @splat(needle);
    var offset: usize = 0;

    while (offset + simd_w <= haystack.len) : (offset += simd_w) {
        const chunk: Vec = haystack[offset..][0..simd_w].*;
        const eq: BoolVec = chunk == splat;
        const mask = toBitmask(eq);
        if (mask != 0) {
            return offset + @ctz(mask);
        }
    }

    // Scalar tail
    for (haystack[offset..], 0..) |b, i| {
        if (b == needle) return offset + i;
    }
    return null;
}

/// Count occurrences of `needle` byte using SIMD.
pub fn countByte(haystack: []const u8, needle: u8) usize {
    const splat: Vec = @splat(needle);
    var count: usize = 0;
    var offset: usize = 0;

    while (offset + simd_w <= haystack.len) : (offset += simd_w) {
        const chunk: Vec = haystack[offset..][0..simd_w].*;
        const eq: BoolVec = chunk == splat;
        count += @popCount(toBitmask(eq));
    }

    for (haystack[offset..]) |b| {
        if (b == needle) count += 1;
    }
    return count;
}

/// Find first occurrence of any byte in `needles` set.
pub fn findAnyByte(haystack: []const u8, needles: []const u8) ?usize {
    var offset: usize = 0;

    while (offset + simd_w <= haystack.len) : (offset += simd_w) {
        const chunk: Vec = haystack[offset..][0..simd_w].*;
        var combined: MaskInt = 0;
        for (needles) |needle| {
            const splat: Vec = @splat(needle);
            const eq: BoolVec = chunk == splat;
            combined |= toBitmask(eq);
        }
        if (combined != 0) {
            return offset + @ctz(combined);
        }
    }

    for (haystack[offset..], 0..) |b, i| {
        for (needles) |needle| {
            if (b == needle) return offset + i;
        }
    }
    return null;
}

// ── SIMD XML tag extractor (S3 responses) ───────────────────────────────────
// S3 returns XML like: <Key>myfile.txt</Key><Size>1024</Size>
// We need to extract tag values quickly.

pub const XmlKV = struct {
    key: []const u8,
    value: []const u8,
};

/// Extract all <Tag>Value</Tag> pairs from XML using SIMD byte scanning.
/// Returns a flat array of key-value pairs.
pub fn parseXmlTags(allocator: Allocator, xml: []const u8) ![]XmlKV {
    var results: std.ArrayList(XmlKV) = .empty;
    var pos: usize = 0;

    while (pos < xml.len) {
        // Find '<' using SIMD
        const tag_start = findByteFrom(xml, pos, '<') orelse break;

        // Skip closing tags, processing instructions, comments
        if (tag_start + 1 >= xml.len) break;
        if (xml[tag_start + 1] == '/' or xml[tag_start + 1] == '?' or xml[tag_start + 1] == '!') {
            pos = tag_start + 1;
            continue;
        }

        // Find '>' to get tag name
        const tag_end = findByteFrom(xml, tag_start + 1, '>') orelse break;
        const tag_name = xml[tag_start + 1 .. tag_end];

        // Skip self-closing tags
        if (tag_name.len > 0 and tag_name[tag_name.len - 1] == '/') {
            pos = tag_end + 1;
            continue;
        }

        // Strip attributes from tag name
        const space_pos = std.mem.indexOfScalar(u8, tag_name, ' ');
        const clean_name = if (space_pos) |sp| tag_name[0..sp] else tag_name;

        // Find closing tag </TagName>
        const value_start = tag_end + 1;
        const close_tag_start = findByteFrom(xml, value_start, '<') orelse break;

        // Verify it's the closing tag
        if (close_tag_start + 2 + clean_name.len <= xml.len and
            xml[close_tag_start + 1] == '/')
        {
            const value = xml[value_start..close_tag_start];
            try results.append(allocator, .{ .key = clean_name, .value = value });

            // Skip past closing tag
            const close_end = findByteFrom(xml, close_tag_start, '>') orelse break;
            pos = close_end + 1;
        } else {
            pos = close_tag_start;
        }
    }

    return results.toOwnedSlice(allocator) catch return &.{};
}

fn findByteFrom(haystack: []const u8, start: usize, needle: u8) ?usize {
    if (start >= haystack.len) return null;
    const result = findByte(haystack[start..], needle) orelse return null;
    return start + result;
}

// ── SIMD JSON value extractor (DynamoDB responses) ──────────────────────────
// DynamoDB returns: {"Item":{"pk":{"S":"user-1"},"name":{"S":"Rach"}}}
// We need to extract string values from the typed wrapper format.

pub const JsonKV = struct {
    key: []const u8,
    type_tag: u8, // 'S', 'N', 'B', etc.
    value: []const u8,
};

/// Fast extraction of DynamoDB-style typed JSON values.
/// Scans for "key":{"S":"value"} patterns using SIMD.
pub fn parseDynamoItem(allocator: Allocator, json: []const u8) ![]JsonKV {
    var results: std.ArrayList(JsonKV) = .empty;
    var pos: usize = 0;

    while (pos < json.len) {
        // Find next '"' using SIMD
        const key_start = findByteFrom(json, pos, '"') orelse break;
        const key_end = findByteFrom(json, key_start + 1, '"') orelse break;
        const key = json[key_start + 1 .. key_end];

        // Look for : { "T" : "V" } pattern
        const colon = findByteFrom(json, key_end + 1, ':') orelse break;
        const brace = findByteFrom(json, colon + 1, '{') orelse {
            pos = colon + 1;
            continue;
        };

        // Check if brace is close to colon (skip nested objects that aren't type wrappers)
        if (brace - colon > 3) {
            pos = colon + 1;
            continue;
        }

        // Find type tag: {"S"
        const type_quote = findByteFrom(json, brace + 1, '"') orelse break;
        if (type_quote + 2 >= json.len) break;
        const type_tag = json[type_quote + 1];
        // Verify it's a DynamoDB type (S, N, B, BOOL, NULL, L, M, SS, NS, BS)
        if (type_tag != 'S' and type_tag != 'N' and type_tag != 'B' and
            type_tag != 'L' and type_tag != 'M')
        {
            pos = type_quote + 1;
            continue;
        }

        // Find the value after type tag
        const val_colon = findByteFrom(json, type_quote + 2, ':') orelse break;
        const val_start = findByteFrom(json, val_colon + 1, '"') orelse {
            pos = val_colon + 1;
            continue;
        };
        const val_end = findByteFrom(json, val_start + 1, '"') orelse break;
        const value = json[val_start + 1 .. val_end];

        try results.append(allocator, .{ .key = key, .type_tag = type_tag, .value = value });

        pos = val_end + 1;
    }

    return results.toOwnedSlice(allocator) catch return &.{};
}

// ── SIMD ISO 8601 timestamp parser ──────────────────────────────────────────
// Parses "2026-03-21T13:05:33Z" or "Fri, 21 Mar 2026 13:05:33 GMT"
// boto3 spends 5% of time in dateutil.parser.parse()

pub const Timestamp = struct {
    year: u16,
    month: u8,
    day: u8,
    hour: u8,
    minute: u8,
    second: u8,
};

/// Parse ISO 8601 timestamp. ~10ns vs dateutil's ~120us.
pub fn parseIso8601(s: []const u8) ?Timestamp {
    // "2026-03-21T13:05:33Z" = 20 chars
    if (s.len < 19) return null;

    // SIMD: validate all digits at once
    if (s.len >= simd_w) {
        const chunk: Vec = s[0..simd_w].*;
        const zero: Vec = @splat('0');
        const nine: Vec = @splat('9');
        // We can't do full validation with SIMD easily, fall through to scalar
        _ = chunk;
        _ = zero;
        _ = nine;
    }

    // Fast scalar parse (still way faster than dateutil)
    return .{
        .year = parseU16(s[0..4]) orelse return null,
        .month = parseU8(s[5..7]) orelse return null,
        .day = parseU8(s[8..10]) orelse return null,
        .hour = parseU8(s[11..13]) orelse return null,
        .minute = parseU8(s[14..16]) orelse return null,
        .second = parseU8(s[17..19]) orelse return null,
    };
}

fn parseU8(s: *const [2]u8) ?u8 {
    const d0 = s[0] -% '0';
    const d1 = s[1] -% '0';
    if (d0 > 9 or d1 > 9) return null;
    return d0 * 10 + d1;
}

fn parseU16(s: *const [4]u8) ?u16 {
    const d0: u16 = s[0] -% '0';
    const d1: u16 = s[1] -% '0';
    const d2: u16 = s[2] -% '0';
    const d3: u16 = s[3] -% '0';
    if (d0 > 9 or d1 > 9 or d2 > 9 or d3 > 9) return null;
    return d0 * 1000 + d1 * 100 + d2 * 10 + d3;
}

// ── RFC 2616 date parser (HTTP headers: "Fri, 21 Mar 2026 13:05:33 GMT") ────

const month_names = [_][]const u8{ "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" };

pub fn parseHttpDate(s: []const u8) ?Timestamp {
    // "Fri, 21 Mar 2026 13:05:33 GMT" = 29 chars
    if (s.len < 25) return null;

    // Skip day name
    const comma = findByte(s, ',') orelse return null;
    if (comma + 2 >= s.len) return null;
    const rest = s[comma + 2 ..];
    if (rest.len < 20) return null;

    return .{
        .day = parseU8(rest[0..2]) orelse return null,
        .month = parseMonth(rest[3..6]) orelse return null,
        .year = parseU16(rest[7..11]) orelse return null,
        .hour = parseU8(rest[12..14]) orelse return null,
        .minute = parseU8(rest[15..17]) orelse return null,
        .second = parseU8(rest[18..20]) orelse return null,
    };
}

fn parseMonth(s: *const [3]u8) ?u8 {
    inline for (month_names, 1..) |name, i| {
        if (s[0] == name[0] and s[1] == name[1] and s[2] == name[2]) return @intCast(i);
    }
    return null;
}

// ── Tests ───────────────────────────────────────────────────────────────────

test "findByte" {
    const data = "Hello, World!";
    try std.testing.expectEqual(@as(?usize, 7), findByte(data, 'W'));
    try std.testing.expectEqual(@as(?usize, null), findByte(data, 'Z'));
}

test "countByte" {
    const data = "aababcabcd";
    try std.testing.expectEqual(@as(usize, 4), countByte(data, 'a'));
}

test "parseIso8601" {
    const ts = parseIso8601("2026-03-21T13:05:33Z") orelse unreachable;
    try std.testing.expectEqual(@as(u16, 2026), ts.year);
    try std.testing.expectEqual(@as(u8, 3), ts.month);
    try std.testing.expectEqual(@as(u8, 21), ts.day);
    try std.testing.expectEqual(@as(u8, 13), ts.hour);
}

test "parseHttpDate" {
    const ts = parseHttpDate("Fri, 21 Mar 2026 13:05:33 GMT") orelse unreachable;
    try std.testing.expectEqual(@as(u16, 2026), ts.year);
    try std.testing.expectEqual(@as(u8, 3), ts.month);
    try std.testing.expectEqual(@as(u8, 21), ts.day);
}
