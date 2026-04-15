/// SIMD-accelerated JSON parser optimized for schema-aware parsing.
/// Parses JSON directly into validated structs without intermediate dict creation.
///
/// Key optimizations:
/// - SIMD character classification for structural characters
/// - Zero-copy string extraction with escape detection
/// - Parallel digit parsing for integers
/// - Pre-computed field name hashes for O(1) field matching
/// - Direct value extraction without intermediate allocation

const std = @import("std");

/// Optimal SIMD block size - auto-detected at compile time.
/// Uses 64 bytes on AVX-512 capable CPUs, 32 bytes otherwise.
const optimal_block_size: usize = std.simd.suggestVectorLength(u8) orelse 32;

// ============================================================================
// SIMD Character Classification
// ============================================================================

/// JSON structural character classification result
pub const JsonCharMask = struct {
    quotes: u64, // "
    colons: u64, // :
    commas: u64, // ,
    open_braces: u64, // {
    close_braces: u64, // }
    open_brackets: u64, // [
    close_brackets: u64, // ]
    backslashes: u64, // \
};

/// SIMD classify 32 bytes of JSON to find structural characters.
/// Returns bitmasks for each character type.
pub fn classifyChunk32(data: *const [32]u8) JsonCharMask {
    const chunk: @Vector(32, u8) = data.*;

    const quote_char: @Vector(32, u8) = @splat('"');
    const colon_char: @Vector(32, u8) = @splat(':');
    const comma_char: @Vector(32, u8) = @splat(',');
    const open_brace: @Vector(32, u8) = @splat('{');
    const close_brace: @Vector(32, u8) = @splat('}');
    const open_bracket: @Vector(32, u8) = @splat('[');
    const close_bracket: @Vector(32, u8) = @splat(']');
    const backslash: @Vector(32, u8) = @splat('\\');

    return .{
        .quotes = @as(u32, @bitCast(chunk == quote_char)),
        .colons = @as(u32, @bitCast(chunk == colon_char)),
        .commas = @as(u32, @bitCast(chunk == comma_char)),
        .open_braces = @as(u32, @bitCast(chunk == open_brace)),
        .close_braces = @as(u32, @bitCast(chunk == close_brace)),
        .open_brackets = @as(u32, @bitCast(chunk == open_bracket)),
        .close_brackets = @as(u32, @bitCast(chunk == close_bracket)),
        .backslashes = @as(u32, @bitCast(chunk == backslash)),
    };
}

// ============================================================================
// SIMD Whitespace Skipping
// ============================================================================

/// Skip whitespace using SIMD.
/// Returns the index of the first non-whitespace character.
pub fn skipWhitespaceSIMD(json: []const u8, start: usize) usize {
    var i = start;

    // Process 16 bytes at a time
    const Block16 = @Vector(16, u8);
    const space: Block16 = @splat(' ');
    const tab: Block16 = @splat('\t');
    const newline: Block16 = @splat('\n');
    const cr: Block16 = @splat('\r');

    while (i + 16 <= json.len) {
        const chunk: Block16 = json[i..][0..16].*;
        const is_space = (chunk == space) | (chunk == tab) | (chunk == newline) | (chunk == cr);

        if (!@reduce(.And, is_space)) {
            // Found non-whitespace in this chunk
            const mask: u16 = @bitCast(is_space);
            const first_nonws = @ctz(~mask);
            return i + first_nonws;
        }
        i += 16;
    }

    // Scalar tail
    while (i < json.len) {
        const c = json[i];
        if (c != ' ' and c != '\t' and c != '\n' and c != '\r') {
            return i;
        }
        i += 1;
    }

    return i;
}

// ============================================================================
// Zero-Copy String Extraction
// ============================================================================

pub const StringResult = struct {
    slice: []const u8,
    end: usize,
    has_escapes: bool,
};

/// Extract a string value starting after the opening quote.
/// Uses SIMD to scan for closing quote and escape detection.
/// Returns the string slice (without quotes), end position, and escape flag.
pub fn extractString(json: []const u8, start: usize) !StringResult {
    var i = start;
    var has_escapes = false;

    const Block32 = @Vector(32, u8);
    const quote_char: Block32 = @splat('"');
    const backslash_char: Block32 = @splat('\\');

    while (i + 32 <= json.len) {
        const chunk: Block32 = json[i..][0..32].*;
        const quote_mask: u32 = @bitCast(chunk == quote_char);
        const backslash_mask: u32 = @bitCast(chunk == backslash_char);

        if (backslash_mask != 0) {
            has_escapes = true;
            // Handle escape: find first backslash, skip it and next char
            const bs_pos = @ctz(backslash_mask);
            if (quote_mask != 0) {
                const q_pos = @ctz(quote_mask);
                if (q_pos < bs_pos) {
                    // Quote comes before backslash
                    return .{
                        .slice = json[start .. i + q_pos],
                        .end = i + q_pos + 1,
                        .has_escapes = has_escapes,
                    };
                }
            }
            // Skip past the escape sequence
            i += bs_pos + 2;
            continue;
        }

        if (quote_mask != 0) {
            const quote_pos = @ctz(quote_mask);
            return .{
                .slice = json[start .. i + quote_pos],
                .end = i + quote_pos + 1,
                .has_escapes = has_escapes,
            };
        }

        i += 32;
    }

    // Scalar fallback for remaining bytes
    while (i < json.len) {
        const c = json[i];
        if (c == '\\') {
            has_escapes = true;
            i += 2; // Skip escape and next char
            if (i > json.len) return error.UnterminatedString;
            continue;
        }
        if (c == '"') {
            return .{
                .slice = json[start..i],
                .end = i + 1,
                .has_escapes = has_escapes,
            };
        }
        i += 1;
    }

    return error.UnterminatedString;
}

// ============================================================================
// SIMD Integer Parsing
// ============================================================================

pub const IntResult = struct {
    value: i64,
    end: usize,
};

/// Parse an integer using SIMD for fast digit processing.
/// Handles negative numbers.
pub fn parseInteger(json: []const u8, start: usize) !IntResult {
    var i = start;
    var negative = false;

    if (i >= json.len) return error.UnexpectedEndOfInput;

    // Check for negative sign
    if (json[i] == '-') {
        negative = true;
        i += 1;
        if (i >= json.len) return error.UnexpectedEndOfInput;
    }

    // Ensure first char is a digit
    if (json[i] < '0' or json[i] > '9') {
        return error.InvalidNumber;
    }

    var value: i64 = 0;

    // Fast path: process 8 digits at once using SIMD
    while (i + 8 <= json.len) {
        const chunk: [8]u8 = json[i..][0..8].*;
        const digits: @Vector(8, u8) = chunk;
        const zeros: @Vector(8, u8) = @splat('0');
        const nines: @Vector(8, u8) = @splat('9');

        // Check if all 8 bytes are digits
        const ge_zero = digits >= zeros;
        const le_nine = digits <= nines;
        const all_digits = @reduce(.And, ge_zero) and @reduce(.And, le_nine);

        if (!all_digits) break;

        // Convert 8 digits to value
        const values = digits - zeros;
        const expanded: @Vector(8, u64) = values;
        const multipliers: @Vector(8, u64) = .{ 10_000_000, 1_000_000, 100_000, 10_000, 1_000, 100, 10, 1 };
        const products = expanded * multipliers;
        const sum = @reduce(.Add, products);

        // Check for overflow
        if (value > @divTrunc(std.math.maxInt(i64) - @as(i64, @intCast(sum)), 100_000_000)) {
            return error.IntegerOverflow;
        }

        value = value * 100_000_000 + @as(i64, @intCast(sum));
        i += 8;
    }

    // Handle remaining digits
    while (i < json.len and json[i] >= '0' and json[i] <= '9') {
        const digit: i64 = json[i] - '0';
        // Check for overflow
        if (value > @divTrunc(std.math.maxInt(i64) - digit, 10)) {
            return error.IntegerOverflow;
        }
        value = value * 10 + digit;
        i += 1;
    }

    return .{
        .value = if (negative) -value else value,
        .end = i,
    };
}

// ============================================================================
// Float Parsing
// ============================================================================

pub const FloatResult = struct {
    value: f64,
    end: usize,
};

/// Parse a floating point number.
/// Uses std.fmt.parseFloat for correctness, but with optimized bounds detection.
pub fn parseFloat(json: []const u8, start: usize) !FloatResult {
    var i = start;

    // Find end of number
    if (i >= json.len) return error.UnexpectedEndOfInput;

    const num_start = i;

    // Skip optional negative sign
    if (json[i] == '-') i += 1;

    // Skip integer part
    while (i < json.len and json[i] >= '0' and json[i] <= '9') {
        i += 1;
    }

    // Skip optional decimal part
    if (i < json.len and json[i] == '.') {
        i += 1;
        while (i < json.len and json[i] >= '0' and json[i] <= '9') {
            i += 1;
        }
    }

    // Skip optional exponent
    if (i < json.len and (json[i] == 'e' or json[i] == 'E')) {
        i += 1;
        if (i < json.len and (json[i] == '+' or json[i] == '-')) {
            i += 1;
        }
        while (i < json.len and json[i] >= '0' and json[i] <= '9') {
            i += 1;
        }
    }

    if (i == num_start or (i == num_start + 1 and json[num_start] == '-')) {
        return error.InvalidNumber;
    }

    const num_str = json[num_start..i];
    const value = std.fmt.parseFloat(f64, num_str) catch return error.InvalidNumber;

    return .{
        .value = value,
        .end = i,
    };
}

// ============================================================================
// Field Name Hashing
// ============================================================================

/// FNV-1a hash for field names.
/// This must match the hash function used in Python to create field specs.
pub fn hashFieldName(name: []const u8) u64 {
    var hash: u64 = 0xcbf29ce484222325; // FNV-1a offset basis
    for (name) |c| {
        hash ^= c;
        hash *%= 0x100000001b3; // FNV-1a prime
    }
    return hash;
}

// ============================================================================
// Value Skipping (for unknown fields)
// ============================================================================

/// Skip a JSON value (for fields not in schema).
/// Returns the position after the value.
pub fn skipValue(json: []const u8, start: usize) !usize {
    var i = skipWhitespaceSIMD(json, start);
    if (i >= json.len) return error.UnexpectedEndOfInput;

    const c = json[i];

    switch (c) {
        '"' => {
            // String
            const result = try extractString(json, i + 1);
            return result.end;
        },
        '{' => {
            // Object
            i += 1;
            var depth: usize = 1;
            while (i < json.len and depth > 0) {
                i = skipWhitespaceSIMD(json, i);
                if (i >= json.len) return error.UnexpectedEndOfInput;

                if (json[i] == '"') {
                    const result = try extractString(json, i + 1);
                    i = result.end;
                } else if (json[i] == '{') {
                    depth += 1;
                    i += 1;
                } else if (json[i] == '}') {
                    depth -= 1;
                    i += 1;
                } else {
                    i += 1;
                }
            }
            return i;
        },
        '[' => {
            // Array
            i += 1;
            var depth: usize = 1;
            while (i < json.len and depth > 0) {
                i = skipWhitespaceSIMD(json, i);
                if (i >= json.len) return error.UnexpectedEndOfInput;

                if (json[i] == '"') {
                    const result = try extractString(json, i + 1);
                    i = result.end;
                } else if (json[i] == '[') {
                    depth += 1;
                    i += 1;
                } else if (json[i] == ']') {
                    depth -= 1;
                    i += 1;
                } else {
                    i += 1;
                }
            }
            return i;
        },
        't' => {
            // true
            if (i + 4 <= json.len and std.mem.eql(u8, json[i..][0..4], "true")) {
                return i + 4;
            }
            return error.InvalidValue;
        },
        'f' => {
            // false
            if (i + 5 <= json.len and std.mem.eql(u8, json[i..][0..5], "false")) {
                return i + 5;
            }
            return error.InvalidValue;
        },
        'n' => {
            // null
            if (i + 4 <= json.len and std.mem.eql(u8, json[i..][0..4], "null")) {
                return i + 4;
            }
            return error.InvalidValue;
        },
        '-', '0'...'9' => {
            // Number
            while (i < json.len) {
                const ch = json[i];
                if ((ch >= '0' and ch <= '9') or ch == '-' or ch == '+' or ch == '.' or ch == 'e' or ch == 'E') {
                    i += 1;
                } else {
                    break;
                }
            }
            return i;
        },
        else => return error.InvalidValue,
    }
}

// ============================================================================
// Type Codes (must match Python)
// ============================================================================

pub const TypeCode = enum(i32) {
    any = 0,
    int = 1,
    float = 2,
    string = 3,
    bool = 4,
    bytes = 5,
};

// ============================================================================
// Parsed Value Result
// ============================================================================

pub const ParsedValue = union(enum) {
    int: i64,
    float: f64,
    string: []const u8,
    string_escaped: []const u8, // String that needs escape processing
    boolean: bool,
    null_val: void,
};

/// Parse a single JSON value.
/// Returns the parsed value and end position.
pub fn parseValue(json: []const u8, start: usize) !struct { value: ParsedValue, end: usize } {
    const i = skipWhitespaceSIMD(json, start);
    if (i >= json.len) return error.UnexpectedEndOfInput;

    const c = json[i];

    switch (c) {
        '"' => {
            const result = try extractString(json, i + 1);
            if (result.has_escapes) {
                return .{
                    .value = .{ .string_escaped = result.slice },
                    .end = result.end,
                };
            }
            return .{
                .value = .{ .string = result.slice },
                .end = result.end,
            };
        },
        't' => {
            if (i + 4 <= json.len and std.mem.eql(u8, json[i..][0..4], "true")) {
                return .{ .value = .{ .boolean = true }, .end = i + 4 };
            }
            return error.InvalidValue;
        },
        'f' => {
            if (i + 5 <= json.len and std.mem.eql(u8, json[i..][0..5], "false")) {
                return .{ .value = .{ .boolean = false }, .end = i + 5 };
            }
            return error.InvalidValue;
        },
        'n' => {
            if (i + 4 <= json.len and std.mem.eql(u8, json[i..][0..4], "null")) {
                return .{ .value = .{ .null_val = {} }, .end = i + 4 };
            }
            return error.InvalidValue;
        },
        '-', '0'...'9' => {
            // Detect if it's a float or integer by looking ahead
            var j = i;
            if (json[j] == '-') j += 1;
            while (j < json.len and json[j] >= '0' and json[j] <= '9') {
                j += 1;
            }
            if (j < json.len and (json[j] == '.' or json[j] == 'e' or json[j] == 'E')) {
                // Float
                const result = try parseFloat(json, i);
                return .{ .value = .{ .float = result.value }, .end = result.end };
            }
            // Integer
            const result = try parseInteger(json, i);
            return .{ .value = .{ .int = result.value }, .end = result.end };
        },
        else => return error.InvalidValue,
    }
}

// ============================================================================
// Field Spec Structure (for C API)
// ============================================================================

/// Field specification passed from Python.
/// Contains pre-computed hash and type information.
pub const CFieldSpec = extern struct {
    name_ptr: [*]const u8,
    name_len: usize,
    name_hash: u64,
    type_code: i32,
    required: i32,
    // Numeric constraints
    has_gt: i32,
    has_ge: i32,
    has_lt: i32,
    has_le: i32,
    gt_val: i64,
    ge_val: i64,
    lt_val: i64,
    le_val: i64,
    gt_dbl: f64,
    ge_dbl: f64,
    lt_dbl: f64,
    le_dbl: f64,
    // String constraints
    has_minl: i32,
    has_maxl: i32,
    min_len: i64,
    max_len: i64,
    // Format validation
    format_code: i32,
};

// ============================================================================
// JSON Object Parser
// ============================================================================

/// Parse result for a single field
pub const FieldParseResult = struct {
    value: ParsedValue,
    field_index: usize,
};

/// Parse a JSON object according to schema.
/// Returns parsed values for each field in schema order.
pub fn parseJsonObject(
    json: []const u8,
    field_specs: []const CFieldSpec,
    allocator: std.mem.Allocator,
) !struct {
    values: []?ParsedValue,
    end_pos: usize,
} {
    const n_fields = field_specs.len;
    var values = try allocator.alloc(?ParsedValue, n_fields);
    @memset(values, null);

    var pos: usize = skipWhitespaceSIMD(json, 0);

    // Expect opening brace
    if (pos >= json.len or json[pos] != '{') {
        allocator.free(values);
        return error.ExpectedOpenBrace;
    }
    pos += 1;

    // Track which fields we've seen
    var fields_seen: u64 = 0;

    while (pos < json.len) {
        pos = skipWhitespaceSIMD(json, pos);
        if (pos >= json.len) {
            allocator.free(values);
            return error.UnexpectedEndOfInput;
        }

        if (json[pos] == '}') {
            pos += 1;
            break;
        }

        if (json[pos] == ',') {
            pos += 1;
            continue;
        }

        // Parse field name
        if (json[pos] != '"') {
            allocator.free(values);
            return error.ExpectedFieldName;
        }
        pos += 1;

        const name_result = try extractString(json, pos);
        const field_name = name_result.slice;
        pos = name_result.end;

        // Skip colon
        pos = skipWhitespaceSIMD(json, pos);
        if (pos >= json.len or json[pos] != ':') {
            allocator.free(values);
            return error.ExpectedColon;
        }
        pos += 1;
        pos = skipWhitespaceSIMD(json, pos);

        // Match field name against specs using hash
        const field_hash = hashFieldName(field_name);
        var matched = false;

        for (field_specs, 0..) |spec, i| {
            if (spec.name_hash == field_hash) {
                // Verify exact match (hash collision check)
                const spec_name = spec.name_ptr[0..spec.name_len];
                if (std.mem.eql(u8, field_name, spec_name)) {
                    // Parse value
                    const value_result = try parseValue(json, pos);
                    values[i] = value_result.value;
                    fields_seen |= (@as(u64, 1) << @intCast(i));
                    pos = value_result.end;
                    matched = true;
                    break;
                }
            }
        }

        if (!matched) {
            // Skip unknown field value
            pos = try skipValue(json, pos);
        }
    }

    // Check required fields
    for (field_specs, 0..) |spec, i| {
        if (spec.required != 0 and (fields_seen & (@as(u64, 1) << @intCast(i))) == 0) {
            allocator.free(values);
            return error.MissingRequiredField;
        }
    }

    return .{
        .values = values,
        .end_pos = pos,
    };
}

// ============================================================================
// JSON Array Parser (for batch operations)
// ============================================================================

/// Parse a JSON array of objects according to schema.
/// Returns a list of parsed objects.
pub fn parseJsonArray(
    json: []const u8,
    field_specs: []const CFieldSpec,
    allocator: std.mem.Allocator,
) !struct {
    objects: [][]?ParsedValue,
    end_pos: usize,
} {
    var pos: usize = skipWhitespaceSIMD(json, 0);

    // Expect opening bracket
    if (pos >= json.len or json[pos] != '[') {
        return error.ExpectedOpenBracket;
    }
    pos += 1;

    var objects = std.ArrayList([]?ParsedValue).init(allocator);
    defer objects.deinit();

    while (pos < json.len) {
        pos = skipWhitespaceSIMD(json, pos);
        if (pos >= json.len) {
            // Clean up on error
            for (objects.items) |obj| {
                allocator.free(obj);
            }
            return error.UnexpectedEndOfInput;
        }

        if (json[pos] == ']') {
            pos += 1;
            break;
        }

        if (json[pos] == ',') {
            pos += 1;
            continue;
        }

        // Parse object
        const remaining = json[pos..];
        const result = try parseJsonObject(remaining, field_specs, allocator);
        try objects.append(result.values);
        pos += result.end_pos;
    }

    return .{
        .objects = try objects.toOwnedSlice(),
        .end_pos = pos,
    };
}

// ============================================================================
// String Escape Processing
// ============================================================================

/// Process escape sequences in a JSON string.
/// Allocates a new buffer for the result.
pub fn processEscapes(input: []const u8, allocator: std.mem.Allocator) ![]u8 {
    var result = std.ArrayListUnmanaged(u8){};
    errdefer result.deinit(allocator);

    var i: usize = 0;
    while (i < input.len) {
        if (input[i] == '\\' and i + 1 < input.len) {
            const next = input[i + 1];
            switch (next) {
                '"' => {
                    try result.append(allocator, '"');
                    i += 2;
                },
                '\\' => {
                    try result.append(allocator, '\\');
                    i += 2;
                },
                '/' => {
                    try result.append(allocator, '/');
                    i += 2;
                },
                'b' => {
                    try result.append(allocator, 0x08);
                    i += 2;
                },
                'f' => {
                    try result.append(allocator, 0x0C);
                    i += 2;
                },
                'n' => {
                    try result.append(allocator, '\n');
                    i += 2;
                },
                'r' => {
                    try result.append(allocator, '\r');
                    i += 2;
                },
                't' => {
                    try result.append(allocator, '\t');
                    i += 2;
                },
                'u' => {
                    // Unicode escape: \uXXXX
                    if (i + 6 > input.len) {
                        try result.append(allocator, input[i]);
                        i += 1;
                        continue;
                    }
                    const hex = input[i + 2 .. i + 6];
                    const codepoint = std.fmt.parseInt(u21, hex, 16) catch {
                        try result.append(allocator, input[i]);
                        i += 1;
                        continue;
                    };
                    var buf: [4]u8 = undefined;
                    const len = std.unicode.utf8Encode(codepoint, &buf) catch {
                        try result.append(allocator, input[i]);
                        i += 1;
                        continue;
                    };
                    try result.appendSlice(allocator, buf[0..len]);
                    i += 6;
                },
                else => {
                    try result.append(allocator, input[i]);
                    i += 1;
                },
            }
        } else {
            try result.append(allocator, input[i]);
            i += 1;
        }
    }

    return try result.toOwnedSlice(allocator);
}

// ============================================================================
// Tests
// ============================================================================

test "skipWhitespaceSIMD" {
    try std.testing.expectEqual(@as(usize, 3), skipWhitespaceSIMD("   hello", 0));
    try std.testing.expectEqual(@as(usize, 0), skipWhitespaceSIMD("hello", 0));
    try std.testing.expectEqual(@as(usize, 5), skipWhitespaceSIMD("\t\n\r  x", 0));
}

test "extractString" {
    const result1 = try extractString("hello\"", 0);
    try std.testing.expectEqualStrings("hello", result1.slice);
    try std.testing.expect(!result1.has_escapes);

    const result2 = try extractString("hello\\nworld\"", 0);
    try std.testing.expectEqualStrings("hello\\nworld", result2.slice);
    try std.testing.expect(result2.has_escapes);
}

test "parseInteger" {
    const result1 = try parseInteger("12345", 0);
    try std.testing.expectEqual(@as(i64, 12345), result1.value);

    const result2 = try parseInteger("-9876", 0);
    try std.testing.expectEqual(@as(i64, -9876), result2.value);

    const result3 = try parseInteger("12345678901234", 0);
    try std.testing.expectEqual(@as(i64, 12345678901234), result3.value);
}

test "parseFloat" {
    const result1 = try parseFloat("3.14159", 0);
    try std.testing.expectApproxEqRel(@as(f64, 3.14159), result1.value, 1e-10);

    const result2 = try parseFloat("-2.5e10", 0);
    try std.testing.expectApproxEqRel(@as(f64, -2.5e10), result2.value, 1e-10);
}

test "hashFieldName" {
    const hash1 = hashFieldName("name");
    const hash2 = hashFieldName("name");
    const hash3 = hashFieldName("email");

    try std.testing.expectEqual(hash1, hash2);
    try std.testing.expect(hash1 != hash3);
}

test "parseValue" {
    const result1 = try parseValue("\"hello\"", 0);
    try std.testing.expectEqualStrings("hello", result1.value.string);

    const result2 = try parseValue("true", 0);
    try std.testing.expect(result2.value.boolean);

    const result3 = try parseValue("false", 0);
    try std.testing.expect(!result3.value.boolean);

    const result4 = try parseValue("null", 0);
    try std.testing.expectEqual(ParsedValue{ .null_val = {} }, result4.value);

    const result5 = try parseValue("42", 0);
    try std.testing.expectEqual(@as(i64, 42), result5.value.int);

    const result6 = try parseValue("3.14", 0);
    try std.testing.expectApproxEqRel(@as(f64, 3.14), result6.value.float, 1e-10);
}

test "skipValue" {
    try std.testing.expectEqual(@as(usize, 7), try skipValue("\"hello\"", 0));
    try std.testing.expectEqual(@as(usize, 4), try skipValue("true", 0));
    try std.testing.expectEqual(@as(usize, 5), try skipValue("false", 0));
    try std.testing.expectEqual(@as(usize, 4), try skipValue("null", 0));
    try std.testing.expectEqual(@as(usize, 5), try skipValue("12345", 0));
    try std.testing.expectEqual(@as(usize, 2), try skipValue("{}", 0));
    try std.testing.expectEqual(@as(usize, 2), try skipValue("[]", 0));
}

test "processEscapes" {
    const allocator = std.testing.allocator;

    const result1 = try processEscapes("hello\\nworld", allocator);
    defer allocator.free(result1);
    try std.testing.expectEqualStrings("hello\nworld", result1);

    const result2 = try processEscapes("tab\\there", allocator);
    defer allocator.free(result2);
    try std.testing.expectEqualStrings("tab\there", result2);

    const result3 = try processEscapes("quote\\\"here", allocator);
    defer allocator.free(result3);
    try std.testing.expectEqualStrings("quote\"here", result3);
}
