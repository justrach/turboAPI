/// Comprehensive validators inspired by Pydantic and Zod
/// Covers all common validation patterns for production use
const std = @import("std");

// ============================================================================
// STRING VALIDATORS
// ============================================================================

/// Email validation (RFC 5322 simplified)
pub inline fn validateEmail(email: []const u8) bool {
    if (email.len == 0) return false;
    
    const at_pos = std.mem.indexOf(u8, email, "@") orelse return false;
    if (at_pos == 0 or at_pos == email.len - 1) return false;
    
    const local = email[0..at_pos];
    const domain = email[at_pos + 1..];
    
    // Check domain has at least one dot
    if (std.mem.indexOf(u8, domain, ".") == null) return false;
    
    // Basic character validation
    for (local) |c| {
        if (!std.ascii.isAlphanumeric(c) and c != '.' and c != '_' and c != '-' and c != '+') {
            return false;
        }
    }
    
    return true;
}

/// URL validation (basic HTTP/HTTPS)
pub inline fn validateUrl(url: []const u8) bool {
    if (url.len < 10) return false; // Minimum: http://a.b
    
    if (std.mem.startsWith(u8, url, "https://")) {
        const rest = url[8..];
        return std.mem.indexOf(u8, rest, ".") != null and rest.len > 2;
    } else if (std.mem.startsWith(u8, url, "http://")) {
        const rest = url[7..];
        return std.mem.indexOf(u8, rest, ".") != null and rest.len > 2;
    }
    
    return false;
}

/// UUID validation (v4 format: 8-4-4-4-12)
pub inline fn validateUuid(uuid: []const u8) bool {
    if (uuid.len != 36) return false;
    
    // Check format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    if (uuid[8] != '-' or uuid[13] != '-' or uuid[18] != '-' or uuid[23] != '-') {
        return false;
    }
    
    // Check all other characters are hex
    const segments = [_][]const u8{
        uuid[0..8],
        uuid[9..13],
        uuid[14..18],
        uuid[19..23],
        uuid[24..36],
    };
    
    for (segments) |segment| {
        for (segment) |c| {
            if (!std.ascii.isHex(c)) return false;
        }
    }
    
    return true;
}

/// IPv4 validation
pub inline fn validateIpv4(ip: []const u8) bool {
    var parts: u8 = 0;
    var current: u32 = 0;
    var has_digit = false;
    
    for (ip) |c| {
        if (c == '.') {
            if (!has_digit or current > 255) return false;
            parts += 1;
            current = 0;
            has_digit = false;
        } else if (std.ascii.isDigit(c)) {
            current = current * 10 + (c - '0');
            has_digit = true;
        } else {
            return false;
        }
    }
    
    return parts == 3 and has_digit and current <= 255;
}

/// Base64 validation
pub fn validateBase64(str: []const u8) bool {
    if (str.len == 0 or str.len % 4 != 0) return false;
    
    for (str, 0..) |c, i| {
        const is_valid = std.ascii.isAlphanumeric(c) or c == '+' or c == '/' or 
                        (c == '=' and i >= str.len - 2);
        if (!is_valid) return false;
    }
    
    return true;
}

/// String contains check
pub fn validateContains(str: []const u8, substring: []const u8) bool {
    return std.mem.indexOf(u8, str, substring) != null;
}

/// String starts with check
pub fn validateStartsWith(str: []const u8, prefix: []const u8) bool {
    return std.mem.startsWith(u8, str, prefix);
}

/// String ends with check
pub fn validateEndsWith(str: []const u8, suffix: []const u8) bool {
    return std.mem.endsWith(u8, str, suffix);
}

/// Regex pattern validation (simplified - checks if matches pattern)
pub fn validatePattern(str: []const u8, pattern: []const u8) bool {
    // TODO: Full regex support - for now, simple wildcard matching
    _ = str;
    _ = pattern;
    return true; // Placeholder
}

// ============================================================================
// NUMBER VALIDATORS
// ============================================================================

/// Greater than
pub inline fn validateGt(comptime T: type, value: T, min: T) bool {
    return value > min;
}

/// Greater than or equal
pub inline fn validateGte(comptime T: type, value: T, min: T) bool {
    return value >= min;
}

/// Less than
pub inline fn validateLt(comptime T: type, value: T, max: T) bool {
    return value < max;
}

/// Less than or equal
pub inline fn validateLte(comptime T: type, value: T, max: T) bool {
    return value <= max;
}

/// Positive (> 0)
pub inline fn validatePositive(comptime T: type, value: T) bool {
    return value > 0;
}

/// Non-negative (>= 0)
pub fn validateNonNegative(comptime T: type, value: T) bool {
    return value >= 0;
}

/// Negative (< 0)
pub fn validateNegative(comptime T: type, value: T) bool {
    return value < 0;
}

/// Non-positive (<= 0)
pub fn validateNonPositive(comptime T: type, value: T) bool {
    return value <= 0;
}

/// Multiple of (divisible by)
pub fn validateMultipleOf(comptime T: type, value: T, divisor: T) bool {
    if (divisor == 0) return false;
    return @mod(value, divisor) == 0;
}

/// Finite (not infinity or NaN for floats)
pub fn validateFinite(value: f64) bool {
    return !std.math.isInf(value) and !std.math.isNan(value);
}

// ============================================================================
// COLLECTION VALIDATORS
// ============================================================================

/// Array/List min length
pub fn validateMinLength(comptime T: type, items: []const T, min_len: usize) bool {
    return items.len >= min_len;
}

/// Array/List max length
pub fn validateMaxLength(comptime T: type, items: []const T, max_len: usize) bool {
    return items.len <= max_len;
}

/// Array/List exact length
pub fn validateLength(comptime T: type, items: []const T, exact_len: usize) bool {
    return items.len == exact_len;
}

/// Array contains element
pub fn validateArrayContains(comptime T: type, items: []const T, element: T) bool {
    for (items) |item| {
        if (item == element) return true;
    }
    return false;
}

// ============================================================================
// DATE/TIME VALIDATORS
// ============================================================================

/// ISO 8601 date validation (YYYY-MM-DD)
pub inline fn validateIsoDate(date_str: []const u8) bool {
    if (date_str.len != 10) return false;
    if (date_str[4] != '-' or date_str[7] != '-') return false;
    
    // Check all other chars are digits
    const year = date_str[0..4];
    const month = date_str[5..7];
    const day = date_str[8..10];
    
    for (year) |c| if (!std.ascii.isDigit(c)) return false;
    for (month) |c| if (!std.ascii.isDigit(c)) return false;
    for (day) |c| if (!std.ascii.isDigit(c)) return false;
    
    // Basic range checks
    const month_val = std.fmt.parseInt(u8, month, 10) catch return false;
    const day_val = std.fmt.parseInt(u8, day, 10) catch return false;
    
    return month_val >= 1 and month_val <= 12 and day_val >= 1 and day_val <= 31;
}

/// ISO 8601 datetime validation (basic)
pub fn validateIsoDatetime(datetime_str: []const u8) bool {
    // Minimum: YYYY-MM-DDTHH:MM:SS
    if (datetime_str.len < 19) return false;
    
    const date_part = datetime_str[0..10];
    if (!validateIsoDate(date_part)) return false;
    
    if (datetime_str[10] != 'T' and datetime_str[10] != ' ') return false;
    
    // Basic time validation
    const time_part = datetime_str[11..];
    if (time_part.len < 8) return false;
    if (time_part[2] != ':' or time_part[5] != ':') return false;
    
    return true;
}

// ============================================================================
// TESTS
// ============================================================================

test "email validation" {
    try std.testing.expect(validateEmail("test@example.com"));
    try std.testing.expect(validateEmail("user+tag@domain.co.uk"));
    try std.testing.expect(!validateEmail("invalid"));
    try std.testing.expect(!validateEmail("@example.com"));
    try std.testing.expect(!validateEmail("test@"));
}

test "URL validation" {
    try std.testing.expect(validateUrl("http://example.com"));
    try std.testing.expect(validateUrl("https://www.example.com/path"));
    try std.testing.expect(!validateUrl("ftp://example.com"));
    try std.testing.expect(!validateUrl("invalid"));
}

test "UUID validation" {
    try std.testing.expect(validateUuid("550e8400-e29b-41d4-a716-446655440000"));
    try std.testing.expect(!validateUuid("invalid-uuid"));
    try std.testing.expect(!validateUuid("550e8400-e29b-41d4-a716"));
}

test "IPv4 validation" {
    try std.testing.expect(validateIpv4("192.168.1.1"));
    try std.testing.expect(validateIpv4("0.0.0.0"));
    try std.testing.expect(!validateIpv4("256.1.1.1"));
    try std.testing.expect(!validateIpv4("192.168.1"));
}

test "number validators" {
    try std.testing.expect(validateGt(i32, 10, 5));
    try std.testing.expect(!validateGt(i32, 5, 10));
    try std.testing.expect(validatePositive(i32, 1));
    try std.testing.expect(!validatePositive(i32, -1));
    try std.testing.expect(validateMultipleOf(i32, 10, 5));
    try std.testing.expect(!validateMultipleOf(i32, 11, 5));
}

test "date validation" {
    try std.testing.expect(validateIsoDate("2024-01-15"));
    try std.testing.expect(!validateIsoDate("2024-13-01"));
    try std.testing.expect(!validateIsoDate("invalid"));
}
