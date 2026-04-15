/// Ultra-fast JSON parsing + validation in Zig
/// Parses JSON and validates in a single pass for maximum performance
const std = @import("std");
const validators = @import("validators_comprehensive.zig");

/// Field specification for validation
pub const FieldSpec = struct {
    name: []const u8,
    validator_type: ValidatorType,
    param1: i64 = 0,
    param2: i64 = 0,
    string_param: []const u8 = "",
};

pub const ValidatorType = enum {
    Int,
    IntGt,
    IntGte,
    IntLt,
    IntLte,
    IntPositive,
    IntNonNegative,
    String,
    StringMinLen,
    StringMaxLen,
    Email,
    Url,
    Uuid,
    Ipv4,
    Base64,
    IsoDate,
    IsoDatetime,
    Float,
    FloatGt,
    FloatFinite,
    Boolean,
};

/// Validation result for a single item
pub const ValidationResult = struct {
    is_valid: bool,
    error_field: ?[]const u8 = null,
};

/// Parse and validate JSON array in one pass
pub fn validateJsonArray(
    json_bytes: []const u8,
    field_specs: []const FieldSpec,
    allocator: std.mem.Allocator,
) ![]ValidationResult {
    var results = std.ArrayList(ValidationResult).init(allocator);
    defer results.deinit();
    
    // Parse JSON
    const parsed = try std.json.parseFromSlice(
        std.json.Value,
        allocator,
        json_bytes,
        .{},
    );
    defer parsed.deinit();
    
    const array = parsed.value.array;
    
    // Validate each item
    for (array.items) |item| {
        const result = validateJsonObject(item.object, field_specs);
        try results.append(result);
    }
    
    return try results.toOwnedSlice();
}

/// Validate a single JSON object against field specs
fn validateJsonObject(
    obj: std.json.ObjectMap,
    field_specs: []const FieldSpec,
) ValidationResult {
    for (field_specs) |spec| {
        const field_value = obj.get(spec.name) orelse {
            return .{ .is_valid = false, .error_field = spec.name };
        };
        
        const is_valid = switch (spec.validator_type) {
            .Int => validateIntField(field_value, spec.param1, spec.param2),
            .IntGt => blk: {
                if (field_value != .integer) break :blk false;
                break :blk validators.validateGt(i64, field_value.integer, spec.param1);
            },
            .IntGte => blk: {
                if (field_value != .integer) break :blk false;
                break :blk validators.validateGte(i64, field_value.integer, spec.param1);
            },
            .IntLt => blk: {
                if (field_value != .integer) break :blk false;
                break :blk validators.validateLt(i64, field_value.integer, spec.param1);
            },
            .IntLte => blk: {
                if (field_value != .integer) break :blk false;
                break :blk validators.validateLte(i64, field_value.integer, spec.param1);
            },
            .IntPositive => blk: {
                if (field_value != .integer) break :blk false;
                break :blk validators.validatePositive(i64, field_value.integer);
            },
            .IntNonNegative => blk: {
                if (field_value != .integer) break :blk false;
                break :blk validators.validateNonNegative(i64, field_value.integer);
            },
            .String => validateStringField(field_value, spec.param1, spec.param2),
            .StringMinLen => blk: {
                if (field_value != .string) break :blk false;
                break :blk field_value.string.len >= @as(usize, @intCast(spec.param1));
            },
            .StringMaxLen => blk: {
                if (field_value != .string) break :blk false;
                break :blk field_value.string.len <= @as(usize, @intCast(spec.param1));
            },
            .Email => blk: {
                if (field_value != .string) break :blk false;
                break :blk validators.validateEmail(field_value.string);
            },
            .Url => blk: {
                if (field_value != .string) break :blk false;
                break :blk validators.validateUrl(field_value.string);
            },
            .Uuid => blk: {
                if (field_value != .string) break :blk false;
                break :blk validators.validateUuid(field_value.string);
            },
            .Ipv4 => blk: {
                if (field_value != .string) break :blk false;
                break :blk validators.validateIpv4(field_value.string);
            },
            .Base64 => blk: {
                if (field_value != .string) break :blk false;
                break :blk validators.validateBase64(field_value.string);
            },
            .IsoDate => blk: {
                if (field_value != .string) break :blk false;
                break :blk validators.validateIsoDate(field_value.string);
            },
            .IsoDatetime => blk: {
                if (field_value != .string) break :blk false;
                break :blk validators.validateIsoDatetime(field_value.string);
            },
            .Float => field_value == .float or field_value == .integer,
            .FloatGt => blk: {
                const val = if (field_value == .float) field_value.float else if (field_value == .integer) @as(f64, @floatFromInt(field_value.integer)) else break :blk false;
                break :blk validators.validateGt(f64, val, @as(f64, @floatFromInt(spec.param1)));
            },
            .FloatFinite => blk: {
                if (field_value != .float) break :blk false;
                break :blk validators.validateFinite(field_value.float);
            },
            .Boolean => field_value == .bool,
        };
        
        if (!is_valid) {
            return .{ .is_valid = false, .error_field = spec.name };
        }
    }
    
    return .{ .is_valid = true };
}

fn validateIntField(value: std.json.Value, min: i64, max: i64) bool {
    if (value != .integer) return false;
    const int_val = value.integer;
    return int_val >= min and int_val <= max;
}

fn validateStringField(value: std.json.Value, min_len: i64, max_len: i64) bool {
    if (value != .string) return false;
    const len = value.string.len;
    return len >= @as(usize, @intCast(min_len)) and len <= @as(usize, @intCast(max_len));
}

test "JSON array validation" {
    const allocator = std.testing.allocator;
    
    const json =
        \\[
        \\  {"name": "Alice", "age": 25, "email": "alice@example.com"},
        \\  {"name": "Bob", "age": 30, "email": "bob@example.com"},
        \\  {"name": "X", "age": 15, "email": "invalid"}
        \\]
    ;
    
    const specs = [_]FieldSpec{
        .{ .name = "name", .validator_type = .String, .param1 = 2, .param2 = 100 },
        .{ .name = "age", .validator_type = .Int, .param1 = 18, .param2 = 120 },
        .{ .name = "email", .validator_type = .Email },
    };
    
    const results = try validateJsonArray(json, &specs, allocator);
    defer allocator.free(results);
    
    try std.testing.expect(results[0].is_valid);
    try std.testing.expect(results[1].is_valid);
    try std.testing.expect(!results[2].is_valid); // Multiple failures
}
