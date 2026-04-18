const std = @import("std");

/// SIMD-accelerated string operations using the Muła algorithm
/// for substring searching and parallel character validation.
///
/// Reference: "SIMD-friendly algorithms for substring searching"
/// by Wojciech Muła (http://0x80.pl/notesen/2016-11-28-simd-strfind.html)
///
/// AVX-512 Support: Uses std.simd.suggestVectorLength() to dynamically
/// select optimal SIMD width (32 for AVX2, 64 for AVX-512).

/// Optimal SIMD block size - auto-detected at compile time.
/// Uses 64 bytes on AVX-512 capable CPUs, 32 bytes otherwise.
const optimal_block_size = std.simd.suggestVectorLength(u8) orelse 32;

/// Character frequency table for selecting rarest bytes in a needle.
/// Lower values = rarer characters = fewer false positives in SIMD scan.
const CHAR_FREQUENCY: [256]u8 = blk: {
    var freq: [256]u8 = [_]u8{0} ** 256;
    // Space and common letters get high frequency
    freq[' '] = 255;
    freq['e'] = 250;
    freq['t'] = 245;
    freq['a'] = 240;
    freq['o'] = 235;
    freq['i'] = 230;
    freq['n'] = 225;
    freq['s'] = 220;
    freq['h'] = 215;
    freq['r'] = 210;
    // Common punctuation
    freq['.'] = 200;
    freq[','] = 195;
    freq[':'] = 50;
    freq[';'] = 45;
    // Uppercase get medium frequency
    for ('A'..'Z' + 1) |c| {
        freq[c] = 100;
    }
    // Lowercase get high frequency
    for ('a'..'z' + 1) |c| {
        if (freq[c] == 0) freq[c] = 150;
    }
    // Digits get medium frequency
    for ('0'..'9' + 1) |c| {
        freq[c] = 120;
    }
    // Special chars get low frequency (rare = good for matching)
    freq['@'] = 10;
    freq['#'] = 8;
    freq['$'] = 7;
    freq['%'] = 6;
    freq['&'] = 5;
    freq['!'] = 15;
    freq['?'] = 12;
    freq['/'] = 30;
    freq['-'] = 80;
    freq['_'] = 40;
    break :blk freq;
};

/// Find the two rarest characters in a needle for SIMD matching.
/// Returns (first_offset, second_offset) into the needle.
pub fn findRarest(needle: []const u8) [2]usize {
    if (needle.len < 2) return .{ 0, if (needle.len > 1) 1 else 0 };

    var min1_freq: u16 = 65535;
    var min2_freq: u16 = 65535;
    var min1_pos: usize = 0;
    var min2_pos: usize = needle.len - 1;

    for (needle, 0..) |c, i| {
        const freq = @as(u16, CHAR_FREQUENCY[c]);
        if (freq < min1_freq) {
            // Shift old min1 to min2
            min2_freq = min1_freq;
            min2_pos = min1_pos;
            min1_freq = freq;
            min1_pos = i;
        } else if (freq < min2_freq and i != min1_pos) {
            min2_freq = freq;
            min2_pos = i;
        }
    }

    // Ensure first_offset < second_offset for consistent behavior
    if (min1_pos <= min2_pos) {
        return .{ min1_pos, min2_pos };
    } else {
        return .{ min2_pos, min1_pos };
    }
}

/// SIMD substring search using the Muła algorithm.
/// Processes 32 bytes at a time (AVX2-width) for maximum throughput.
/// Uses character frequency selection to minimize false positives.
pub fn simdContains(haystack: []const u8, needle: []const u8) bool {
    return simdIndexOf(haystack, needle) != null;
}

/// SIMD-based indexOf - returns the first index of needle in haystack.
/// Uses dynamic block sizing: 64 bytes on AVX-512, 32 bytes on AVX2.
pub fn simdIndexOf(haystack: []const u8, needle: []const u8) ?usize {
    const n = haystack.len;
    const k = needle.len;

    if (k == 0) return 0;
    if (k > n) return null;
    if (k == 1) return std.mem.indexOfScalar(u8, haystack, needle[0]);

    // Dynamic block size: 64 on AVX-512, 32 on AVX2 (compile-time selected)
    const block_size = optimal_block_size;
    const Block = @Vector(block_size, u8);

    // Select the two rarest characters for SIMD comparison
    const offsets = findRarest(needle);
    const first_offset = offsets[0];
    const second_offset = offsets[1];

    const first_char: Block = @splat(needle[first_offset]);
    const second_char: Block = @splat(needle[second_offset]);

    var i: usize = 0;
    while (i + k + block_size <= n + 1) : (i += block_size) {
        // Ensure we don't read past the end
        if (i + first_offset + block_size > n or i + second_offset + block_size > n) break;

        const first_block: Block = haystack[i + first_offset ..][0..block_size].*;
        const second_block: Block = haystack[i + second_offset ..][0..block_size].*;

        const eq_first = first_char == first_block;
        const eq_second = second_char == second_block;

        var mask: std.bit_set.IntegerBitSet(block_size) = .{
            .mask = @bitCast(eq_first & eq_second),
        };

        while (mask.findFirstSet()) |bitpos| {
            const candidate = i + bitpos;
            if (candidate + k <= n) {
                if (std.mem.eql(u8, haystack[candidate..][0..k], needle)) {
                    return candidate;
                }
            }
            mask.unset(bitpos);
        }
    }

    // Scalar fallback for the tail
    if (i < n) {
        const remaining = haystack[i..];
        if (remaining.len >= k) {
            if (std.mem.indexOf(u8, remaining, needle)) |rel_idx| {
                return i + rel_idx;
            }
        }
    }

    return null;
}

/// SIMD-based startsWith check.
/// For short prefixes, uses scalar. For longer ones, uses SIMD comparison.
pub fn simdStartsWith(str: []const u8, prefix: []const u8) bool {
    if (prefix.len > str.len) return false;
    if (prefix.len == 0) return true;

    // For short prefixes (<=16 bytes), scalar is fine
    if (prefix.len <= 16) {
        return std.mem.startsWith(u8, str, prefix);
    }

    // SIMD comparison in 16-byte chunks
    const Block16 = @Vector(16, u8);
    var i: usize = 0;

    while (i + 16 <= prefix.len) : (i += 16) {
        const str_block: Block16 = str[i..][0..16].*;
        const prefix_block: Block16 = prefix[i..][0..16].*;
        const eq = str_block == prefix_block;
        if (!@reduce(.And, eq)) return false;
    }

    // Check remaining bytes
    while (i < prefix.len) : (i += 1) {
        if (str[i] != prefix[i]) return false;
    }

    return true;
}

/// SIMD-based endsWith check.
pub fn simdEndsWith(str: []const u8, suffix: []const u8) bool {
    if (suffix.len > str.len) return false;
    if (suffix.len == 0) return true;

    const offset = str.len - suffix.len;

    if (suffix.len <= 16) {
        return std.mem.endsWith(u8, str, suffix);
    }

    const Block16 = @Vector(16, u8);
    var i: usize = 0;

    while (i + 16 <= suffix.len) : (i += 16) {
        const str_block: Block16 = str[offset + i ..][0..16].*;
        const suffix_block: Block16 = suffix[i..][0..16].*;
        const eq = str_block == suffix_block;
        if (!@reduce(.And, eq)) return false;
    }

    while (i < suffix.len) : (i += 1) {
        if (str[offset + i] != suffix[i]) return false;
    }

    return true;
}

/// SIMD UUID validation - validates the 8-4-4-4-12 hex format in parallel.
/// UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (36 chars)
/// We validate hex characters and hyphen positions simultaneously using SIMD.
pub fn simdValidateUuid(uuid: []const u8) bool {
    if (uuid.len != 36) return false;

    // Check hyphen positions first (scalar - only 4 checks)
    if (uuid[8] != '-' or uuid[13] != '-' or uuid[18] != '-' or uuid[23] != '-') {
        return false;
    }

    // Now validate hex characters using SIMD
    // We have 32 hex chars total: 8+4+4+4+12 = 32
    // Extract them into a contiguous 32-byte buffer for SIMD processing
    var hex_chars: [32]u8 = undefined;
    @memcpy(hex_chars[0..8], uuid[0..8]);
    @memcpy(hex_chars[8..12], uuid[9..13]);
    @memcpy(hex_chars[12..16], uuid[14..18]);
    @memcpy(hex_chars[16..20], uuid[19..23]);
    @memcpy(hex_chars[20..32], uuid[24..36]);

    // SIMD validate all 32 hex chars at once
    const Block = @Vector(32, u8);
    const chars: Block = hex_chars;

    // Check if each char is a valid hex digit:
    // '0'-'9' (0x30-0x39), 'a'-'f' (0x61-0x66), 'A'-'F' (0x41-0x46)

    const zero: Block = @splat('0');
    const nine: Block = @splat('9');
    const lower_a: Block = @splat('a');
    const lower_f: Block = @splat('f');
    const upper_a: Block = @splat('A');
    const upper_f: Block = @splat('F');

    const is_digit = (chars >= zero) & (chars <= nine);
    const is_lower_hex = (chars >= lower_a) & (chars <= lower_f);
    const is_upper_hex = (chars >= upper_a) & (chars <= upper_f);

    const is_valid = is_digit | is_lower_hex | is_upper_hex;
    return @reduce(.And, is_valid);
}

/// SIMD-based email validation with parallel character class checking.
/// Validates the entire email string structure in SIMD passes.
pub fn simdValidateEmail(email: []const u8) bool {
    if (email.len < 3 or email.len > 320) return false;

    // First pass: find @ position using SIMD
    var at_pos: ?usize = null;
    var at_count: u32 = 0;

    const Block = @Vector(32, u8);
    const at_char: Block = @splat('@');

    var i: usize = 0;
    while (i + 32 <= email.len) : (i += 32) {
        const chunk: Block = email[i..][0..32].*;
        const eq_at = chunk == at_char;
        const at_bits: u32 = @bitCast(eq_at);
        const count = @popCount(at_bits);
        at_count += count;
        if (at_count > 1) return false;
        if (count == 1 and at_pos == null) {
            at_pos = i + @ctz(at_bits);
        }
    }

    // Scalar tail for @ search
    while (i < email.len) : (i += 1) {
        if (email[i] == '@') {
            at_count += 1;
            if (at_count > 1) return false;
            if (at_pos == null) at_pos = i;
        }
    }

    const at = at_pos orelse return false;
    if (at == 0 or at >= email.len - 1) return false;

    // Check local part (before @)
    const local = email[0..at];
    if (local.len == 0 or local.len > 64) return false;

    // Check domain (after @)
    const domain = email[at + 1 ..];
    if (domain.len < 3) return false;

    // Domain must contain a dot
    var has_dot = false;
    var j: usize = 0;
    const Block16 = @Vector(16, u8);
    const dot_char16: Block16 = @splat('.');

    while (j + 16 <= domain.len) : (j += 16) {
        const chunk: Block16 = domain[j..][0..16].*;
        const eq_dot = chunk == dot_char16;
        if (@reduce(.Or, eq_dot)) {
            has_dot = true;
            break;
        }
    }
    if (!has_dot) {
        while (j < domain.len) : (j += 1) {
            if (domain[j] == '.') {
                has_dot = true;
                break;
            }
        }
    }
    if (!has_dot) return false;

    // SIMD character validation for local part
    // Valid: a-z, A-Z, 0-9, ._%+-
    var k: usize = 0;
    while (k + 32 <= local.len) : (k += 32) {
        const chunk: Block = local[k..][0..32].*;
        if (!isValidEmailLocalChars(chunk)) return false;
    }
    // Scalar tail
    while (k < local.len) : (k += 1) {
        if (!isValidEmailLocalChar(local[k])) return false;
    }

    // SIMD character validation for domain
    // Valid: a-z, A-Z, 0-9, .-
    k = 0;
    while (k + 32 <= domain.len) : (k += 32) {
        const chunk: Block = domain[k..][0..32].*;
        if (!isValidEmailDomainChars(chunk)) return false;
    }
    while (k < domain.len) : (k += 1) {
        if (!isValidEmailDomainChar(domain[k])) return false;
    }

    return true;
}

/// SIMD check for valid email local-part characters (32 bytes at once)
inline fn isValidEmailLocalChars(chars: @Vector(32, u8)) bool {
    const lower_a: @Vector(32, u8) = @splat('a');
    const lower_z: @Vector(32, u8) = @splat('z');
    const upper_a: @Vector(32, u8) = @splat('A');
    const upper_z: @Vector(32, u8) = @splat('Z');
    const digit_0: @Vector(32, u8) = @splat('0');
    const digit_9: @Vector(32, u8) = @splat('9');
    const dot: @Vector(32, u8) = @splat('.');
    const underscore: @Vector(32, u8) = @splat('_');
    const percent: @Vector(32, u8) = @splat('%');
    const plus: @Vector(32, u8) = @splat('+');
    const dash: @Vector(32, u8) = @splat('-');

    const is_lower = (chars >= lower_a) & (chars <= lower_z);
    const is_upper = (chars >= upper_a) & (chars <= upper_z);
    const is_digit = (chars >= digit_0) & (chars <= digit_9);
    const is_special = (chars == dot) | (chars == underscore) | (chars == percent) | (chars == plus) | (chars == dash);

    const is_valid = is_lower | is_upper | is_digit | is_special;
    return @reduce(.And, is_valid);
}

/// Scalar check for valid email local-part character
inline fn isValidEmailLocalChar(c: u8) bool {
    return (c >= 'a' and c <= 'z') or
        (c >= 'A' and c <= 'Z') or
        (c >= '0' and c <= '9') or
        c == '.' or c == '_' or c == '%' or c == '+' or c == '-';
}

/// SIMD check for valid email domain characters (32 bytes at once)
inline fn isValidEmailDomainChars(chars: @Vector(32, u8)) bool {
    const lower_a: @Vector(32, u8) = @splat('a');
    const lower_z: @Vector(32, u8) = @splat('z');
    const upper_a: @Vector(32, u8) = @splat('A');
    const upper_z: @Vector(32, u8) = @splat('Z');
    const digit_0: @Vector(32, u8) = @splat('0');
    const digit_9: @Vector(32, u8) = @splat('9');
    const dot: @Vector(32, u8) = @splat('.');
    const dash: @Vector(32, u8) = @splat('-');

    const is_lower = (chars >= lower_a) & (chars <= lower_z);
    const is_upper = (chars >= upper_a) & (chars <= upper_z);
    const is_digit = (chars >= digit_0) & (chars <= digit_9);
    const is_special = (chars == dot) | (chars == dash);

    const is_valid = is_lower | is_upper | is_digit | is_special;
    return @reduce(.And, is_valid);
}

/// Scalar check for valid email domain character
inline fn isValidEmailDomainChar(c: u8) bool {
    return (c >= 'a' and c <= 'z') or
        (c >= 'A' and c <= 'Z') or
        (c >= '0' and c <= '9') or
        c == '.' or c == '-';
}

/// SIMD-based IPv4 validation.
/// Checks digit and dot characters in parallel, then validates octets.
pub fn simdValidateIpv4(ip: []const u8) bool {
    if (ip.len < 7 or ip.len > 15) return false;

    // SIMD character class validation (all chars must be digits or dots)
    if (ip.len >= 16) {
        const Block16 = @Vector(16, u8);
        const chunk: Block16 = ip[0..16].*;
        const digit_0: Block16 = @splat('0');
        const digit_9: Block16 = @splat('9');
        const dot: Block16 = @splat('.');
        const is_digit = (chunk >= digit_0) & (chunk <= digit_9);
        const is_dot = chunk == dot;
        const is_valid = is_digit | is_dot;
        if (!@reduce(.And, is_valid)) return false;
    }

    // Parse octets (scalar - fast for 4 octets)
    var parts: u8 = 0;
    var current: u32 = 0;
    var has_digit = false;
    var digit_count: u8 = 0;

    for (ip) |c| {
        if (c == '.') {
            if (!has_digit or current > 255) return false;
            if (digit_count > 1 and ip[0] == '0') return false; // no leading zeros
            parts += 1;
            current = 0;
            has_digit = false;
            digit_count = 0;
        } else if (c >= '0' and c <= '9') {
            current = current * 10 + (c - '0');
            has_digit = true;
            digit_count += 1;
            if (digit_count > 3) return false;
        } else {
            return false;
        }
    }

    return parts == 3 and has_digit and current <= 255;
}

/// SIMD-based Base64 validation.
/// Validates character classes in parallel using SIMD.
pub fn simdValidateBase64(str: []const u8) bool {
    if (str.len == 0 or str.len % 4 != 0) return false;

    const Block = @Vector(32, u8);
    var i: usize = 0;

    // Check padding location (= can only appear at the end)
    const pad_start = str.len - 2;

    while (i + 32 <= pad_start) : (i += 32) {
        const chunk: Block = str[i..][0..32].*;

        const upper_a: Block = @splat('A');
        const upper_z: Block = @splat('Z');
        const lower_a: Block = @splat('a');
        const lower_z: Block = @splat('z');
        const digit_0: Block = @splat('0');
        const digit_9: Block = @splat('9');
        const plus: Block = @splat('+');
        const slash: Block = @splat('/');

        const is_upper = (chunk >= upper_a) & (chunk <= upper_z);
        const is_lower = (chunk >= lower_a) & (chunk <= lower_z);
        const is_digit = (chunk >= digit_0) & (chunk <= digit_9);
        const is_plus = chunk == plus;
        const is_slash = chunk == slash;

        const is_valid = is_upper | is_lower | is_digit | is_plus | is_slash;
        if (!@reduce(.And, is_valid)) return false;
    }

    // Scalar tail (including possible padding)
    while (i < str.len) : (i += 1) {
        const c = str[i];
        const is_valid = (c >= 'A' and c <= 'Z') or
            (c >= 'a' and c <= 'z') or
            (c >= '0' and c <= '9') or
            c == '+' or c == '/' or
            (c == '=' and i >= pad_start);
        if (!is_valid) return false;
    }

    return true;
}

/// SIMD-based string trim - returns the slice with leading/trailing whitespace removed.
/// Uses SIMD to find the first and last non-whitespace characters.
pub fn simdTrimStart(str: []const u8) []const u8 {
    if (str.len == 0) return str;

    const Block16 = @Vector(16, u8);
    const space: Block16 = @splat(' ');
    const tab: Block16 = @splat('\t');
    const newline: Block16 = @splat('\n');
    const cr: Block16 = @splat('\r');

    var i: usize = 0;
    while (i + 16 <= str.len) : (i += 16) {
        const chunk: Block16 = str[i..][0..16].*;
        const is_space = (chunk == space) | (chunk == tab) | (chunk == newline) | (chunk == cr);
        if (!@reduce(.And, is_space)) {
            // Find exact position of first non-whitespace in this chunk
            for (0..16) |j| {
                if (!isWhitespace(str[i + j])) return str[i + j ..];
            }
        }
    }

    // Scalar tail
    while (i < str.len) : (i += 1) {
        if (!isWhitespace(str[i])) return str[i..];
    }

    return str[str.len..];
}

pub fn simdTrimEnd(str: []const u8) []const u8 {
    if (str.len == 0) return str;

    var end = str.len;

    // Process from the end
    while (end > 0) {
        if (end >= 16) {
            const Block16 = @Vector(16, u8);
            const start = end - 16;
            const chunk: Block16 = str[start..][0..16].*;
            const space: Block16 = @splat(' ');
            const tab: Block16 = @splat('\t');
            const newline: Block16 = @splat('\n');
            const cr: Block16 = @splat('\r');
            const is_space = (chunk == space) | (chunk == tab) | (chunk == newline) | (chunk == cr);
            if (@reduce(.And, is_space)) {
                end -= 16;
                continue;
            }
        }
        // Find exact end position
        while (end > 0 and isWhitespace(str[end - 1])) {
            end -= 1;
        }
        break;
    }

    return str[0..end];
}

pub fn simdTrim(str: []const u8) []const u8 {
    const trimmed_start = simdTrimStart(str);
    return simdTrimEnd(trimmed_start);
}

inline fn isWhitespace(c: u8) bool {
    return c == ' ' or c == '\t' or c == '\n' or c == '\r';
}

/// SIMD ISO date validation (YYYY-MM-DD format, 10 chars)
/// Validates digit positions and separator positions in parallel.
pub fn simdValidateIsoDate(date: []const u8) bool {
    if (date.len != 10) return false;

    // Check separators
    if (date[4] != '-' or date[7] != '-') return false;

    // SIMD validate all 8 digit positions at once
    const Block8 = @Vector(8, u8);
    var digits: [8]u8 = undefined;
    @memcpy(digits[0..4], date[0..4]);
    @memcpy(digits[4..6], date[5..7]);
    @memcpy(digits[6..8], date[8..10]);

    const chars: Block8 = digits;
    const zero: Block8 = @splat('0');
    const nine: Block8 = @splat('9');
    const is_digit = (chars >= zero) & (chars <= nine);
    if (!@reduce(.And, is_digit)) return false;

    // Validate ranges
    const month_val = (@as(u16, date[5] - '0') * 10) + (date[6] - '0');
    const day_val = (@as(u16, date[8] - '0') * 10) + (date[9] - '0');

    return month_val >= 1 and month_val <= 12 and day_val >= 1 and day_val <= 31;
}

/// SIMD URL validation - checks protocol prefix and basic structure.
pub fn simdValidateUrl(url: []const u8) bool {
    if (url.len < 10) return false;

    // Check protocol prefix using SIMD (8 bytes for "https://")
    const Block8 = @Vector(8, u8);
    const https_prefix: Block8 = "https://".*;
    const http_prefix: Block8 = "http://\x00".*;

    const first8: Block8 = url[0..8].*;

    const is_https = @reduce(.And, first8 == https_prefix);
    if (is_https) {
        const rest = url[8..];
        return hasDotInDomain(rest);
    }

    // Check http:// (7 chars)
    const first7: @Vector(7, u8) = url[0..7].*;
    const http7: @Vector(7, u8) = "http://".*;
    const is_http = @reduce(.And, first7 == http7);
    if (is_http) {
        const rest = url[7..];
        return hasDotInDomain(rest);
    }

    _ = http_prefix;
    return false;
}

/// Check if domain portion contains a dot (required for valid URL)
fn hasDotInDomain(domain: []const u8) bool {
    if (domain.len < 3) return false;

    const Block16 = @Vector(16, u8);
    const dot: Block16 = @splat('.');
    var i: usize = 0;

    while (i + 16 <= domain.len) : (i += 16) {
        const chunk: Block16 = domain[i..][0..16].*;
        const eq_dot = chunk == dot;
        if (@reduce(.Or, eq_dot)) return true;
    }

    while (i < domain.len) : (i += 1) {
        if (domain[i] == '.') return true;
    }

    return false;
}

// ============================================================================
// TESTS
// ============================================================================

test "simdContains - basic" {
    try std.testing.expect(simdContains("hello world", "world"));
    try std.testing.expect(simdContains("hello world", "hello"));
    try std.testing.expect(simdContains("hello world", "lo wo"));
    try std.testing.expect(!simdContains("hello world", "xyz"));
    try std.testing.expect(simdContains("abcdef", ""));
    try std.testing.expect(!simdContains("", "abc"));
}

test "simdContains - longer strings" {
    const long_str = "The quick brown fox jumps over the lazy dog and keeps running through the fields of golden wheat.";
    try std.testing.expect(simdContains(long_str, "golden wheat"));
    try std.testing.expect(simdContains(long_str, "quick brown"));
    try std.testing.expect(simdContains(long_str, "lazy dog"));
    try std.testing.expect(!simdContains(long_str, "silver wheat"));
}

test "simdStartsWith" {
    try std.testing.expect(simdStartsWith("hello world", "hello"));
    try std.testing.expect(!simdStartsWith("hello world", "world"));
    try std.testing.expect(simdStartsWith("hello world", ""));
    try std.testing.expect(!simdStartsWith("hi", "hello"));
    // Test with longer prefix (>16 bytes)
    try std.testing.expect(simdStartsWith("abcdefghijklmnopqrstuvwxyz", "abcdefghijklmnopqr"));
}

test "simdEndsWith" {
    try std.testing.expect(simdEndsWith("hello world", "world"));
    try std.testing.expect(!simdEndsWith("hello world", "hello"));
    try std.testing.expect(simdEndsWith("hello world", ""));
    try std.testing.expect(!simdEndsWith("hi", "world"));
}

test "simdValidateUuid" {
    try std.testing.expect(simdValidateUuid("550e8400-e29b-41d4-a716-446655440000"));
    try std.testing.expect(simdValidateUuid("123e4567-e89b-12d3-a456-426614174000"));
    try std.testing.expect(!simdValidateUuid("invalid-uuid-format"));
    try std.testing.expect(!simdValidateUuid("550e8400-e29b-41d4-a716-44665544000g")); // 'g' is not hex
    try std.testing.expect(!simdValidateUuid("550e8400xe29b-41d4-a716-446655440000")); // wrong separator
}

test "simdValidateEmail" {
    try std.testing.expect(simdValidateEmail("test@example.com"));
    try std.testing.expect(simdValidateEmail("user+tag@domain.co.uk"));
    try std.testing.expect(simdValidateEmail("a@b.c"));
    try std.testing.expect(!simdValidateEmail("invalid"));
    try std.testing.expect(!simdValidateEmail("@example.com"));
    try std.testing.expect(!simdValidateEmail("test@"));
    try std.testing.expect(!simdValidateEmail("test@@example.com"));
}

test "simdValidateIpv4" {
    try std.testing.expect(simdValidateIpv4("192.168.1.1"));
    try std.testing.expect(simdValidateIpv4("0.0.0.0"));
    try std.testing.expect(simdValidateIpv4("255.255.255.255"));
    try std.testing.expect(!simdValidateIpv4("256.1.1.1"));
    try std.testing.expect(!simdValidateIpv4("192.168.1"));
    try std.testing.expect(!simdValidateIpv4("abc.def.ghi.jkl"));
}

test "simdValidateBase64" {
    try std.testing.expect(simdValidateBase64("SGVsbG8gV29ybGQ="));
    try std.testing.expect(simdValidateBase64("dGVzdA=="));
    try std.testing.expect(!simdValidateBase64("not base64!"));
    try std.testing.expect(!simdValidateBase64("abc")); // length not multiple of 4
}

test "simdValidateIsoDate" {
    try std.testing.expect(simdValidateIsoDate("2024-01-15"));
    try std.testing.expect(simdValidateIsoDate("2024-12-31"));
    try std.testing.expect(!simdValidateIsoDate("2024-13-01"));
    try std.testing.expect(!simdValidateIsoDate("2024-00-01"));
    try std.testing.expect(!simdValidateIsoDate("invalid"));
}

test "simdValidateUrl" {
    try std.testing.expect(simdValidateUrl("http://example.com"));
    try std.testing.expect(simdValidateUrl("https://www.example.com/path"));
    try std.testing.expect(!simdValidateUrl("ftp://example.com"));
    try std.testing.expect(!simdValidateUrl("invalid"));
}

test "simdTrim" {
    try std.testing.expectEqualStrings("hello", simdTrim("  hello  "));
    try std.testing.expectEqualStrings("hello world", simdTrim("\t\nhello world\n\t"));
    try std.testing.expectEqualStrings("", simdTrim("    "));
    try std.testing.expectEqualStrings("hello", simdTrim("hello"));
}

test "findRarest" {
    const result = findRarest("newsletter");
    // 'w' and 'l' should be among the rarest
    try std.testing.expect(result[0] < "newsletter".len);
    try std.testing.expect(result[1] < "newsletter".len);
    try std.testing.expect(result[0] != result[1]);
}
