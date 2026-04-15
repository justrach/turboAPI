const std = @import("std");
const validator = @import("validator");

/// ParseAndValidate combines JSON parsing with validation in one step.
/// Combines JSON parsing with validation in one step.
///
/// Example:
///   const user = try parseAndValidate(User, json_string, allocator);
pub fn parseAndValidate(comptime T: type, json_str: []const u8, allocator: std.mem.Allocator) !T {
    // Parse JSON to intermediate representation
    const parsed = try std.json.parseFromSlice(std.json.Value, allocator, json_str, .{});
    defer parsed.deinit();

    // Convert to target type with validation
    return try fromJsonValue(T, parsed.value, allocator);
}

/// Convert a JSON Value to a typed struct with validation
fn fromJsonValue(comptime T: type, value: std.json.Value, allocator: std.mem.Allocator) !T {
    const type_info = @typeInfo(T);

    switch (type_info) {
        .@"struct" => |struct_info| {
            if (value != .object) return error.ExpectedObject;

            var result: T = undefined;
            var errors = validator.ValidationErrors.init(allocator);
            defer errors.deinit();

            // Track which string fields were allocated so we can free on error
            var string_allocated: [struct_info.fields.len]bool = .{false} ** struct_info.fields.len;

            errdefer {
                inline for (struct_info.fields, 0..) |field, i| {
                    if (comptime isStringSliceType(field.type)) {
                        if (string_allocated[i]) {
                            allocator.free(@field(result, field.name));
                        }
                    }
                }
            }

            // Process fields manually to avoid comptime control flow issues
            comptime var field_index = 0;
            inline while (field_index < struct_info.fields.len) : (field_index += 1) {
                const field = struct_info.fields[field_index];
                const json_value = value.object.get(field.name);

                // Handle missing fields
                if (json_value == null) {
                    if (@typeInfo(field.type) == .@"optional") {
                        @field(result, field.name) = null;
                    } else {
                        try errors.add(field.name, "Required field missing");
                    }
                } else {
                    // Handle present fields
                    const json_val = json_value.?;
                    const field_result = fromJsonValueTyped(field.type, json_val, allocator);
                    if (field_result) |field_value| {
                        @field(result, field.name) = field_value;
                        if (comptime isStringSliceType(field.type)) {
                            string_allocated[field_index] = true;
                        }
                    } else |err| {
                        const msg = try std.fmt.allocPrint(allocator, "Invalid value: {}", .{err});
                        defer allocator.free(msg);
                        try errors.add(field.name, msg);
                        // Set default values based on type
                        @field(result, field.name) = switch (@typeInfo(field.type)) {
                            .@"bool" => false,
                            .@"int" => 0,
                            .@"float" => 0.0,
                            .@"pointer" => |ptr_info| blk: {
                                if (ptr_info.size == .slice and ptr_info.child == u8) {
                                    break :blk "";
                                } else {
                                    return error.UnsupportedType;
                                }
                            },
                            .@"optional" => null,
                            else => return error.UnsupportedType,
                        };
                    }
                }
            }

            if (errors.hasErrors()) {
                std.debug.print("JSON validation errors:\n{f}\n", .{errors});
                return error.ValidationFailed;
            }

            // Run additional struct-level validation
            try validator.validateStruct(T, result, &errors);

            if (errors.hasErrors()) {
                std.debug.print("Struct validation errors:\n{f}\n", .{errors});
                return error.ValidationFailed;
            }

            return result;
        },
        else => return fromJsonValueTyped(T, value, allocator),
    }
}

/// Check if a type is []const u8 (an allocated string slice)
fn isStringSliceType(comptime T: type) bool {
    const info = @typeInfo(T);
    if (info == .@"pointer") {
        const ptr = info.@"pointer";
        return ptr.size == .slice and ptr.child == u8;
    }
    return false;
}

/// Convert JSON value to a specific type
fn fromJsonValueTyped(comptime T: type, value: std.json.Value, allocator: std.mem.Allocator) !T {
    const type_info = @typeInfo(T);

    return switch (type_info) {
        .@"bool" => if (value == .bool) value.bool else error.TypeMismatch,
        .@"int" => if (value == .integer) std.math.cast(T, value.integer) orelse error.IntegerOverflow else error.TypeMismatch,
        .@"float" => if (value == .float) @as(T, @floatCast(value.float)) else if (value == .integer) @as(T, @floatFromInt(value.integer)) else error.TypeMismatch,
        .@"pointer" => |ptr_info| {
            if (ptr_info.size == .slice and ptr_info.child == u8) {
                if (value == .string) {
                    return try allocator.dupe(u8, value.string);
                }
                return error.TypeMismatch;
            }
            return error.UnsupportedType;
        },
        .@"optional" => |opt_info| {
            if (value == .null) return null;
            return try fromJsonValueTyped(opt_info.child, value, allocator);
        },
        else => error.UnsupportedType,
    };
}

/// BatchValidate validates multiple JSON objects from an array.
/// Validates multiple JSON objects from an array.
pub fn batchValidate(comptime T: type, json_array: []const u8, allocator: std.mem.Allocator) ![]validator.ValidationResult(T) {
    const parsed = try std.json.parseFromSlice(std.json.Value, allocator, json_array, .{});
    defer parsed.deinit();

    if (parsed.value != .array) return error.ExpectedArray;

    const items = parsed.value.array.items;
    var results = try allocator.alloc(validator.ValidationResult(T), items.len);

    for (items, 0..) |item, i| {
        const result = fromJsonValue(T, item, allocator);
        if (result) |val| {
            results[i] = validator.ValidationResult(T){ .valid = val };
        } else |_| {
            var errors = validator.ValidationErrors.init(allocator);
            try errors.add("item", "Validation failed");
            results[i] = validator.ValidationResult(T){ .invalid = errors };
        }
    }

    return results;
}

/// StreamValidate processes NDJSON (newline-delimited JSON) with constant memory.
/// Processes NDJSON (newline-delimited JSON) with constant memory.
pub fn streamValidate(comptime T: type, reader: anytype, allocator: std.mem.Allocator, callback: fn (validator.ValidationResult(T)) anyerror!void) !void {
    var line_buf: [4096]u8 = undefined;

    while (true) {
        const line = reader.readUntilDelimiterOrEof(&line_buf, '\n') catch |err| {
            if (err == error.EndOfStream) break;
            return err;
        } orelse break;

        if (line.len == 0) continue;

        const result = parseAndValidate(T, line, allocator);
        if (result) |val| {
            const validation_result = validator.ValidationResult(T){ .valid = val };
            try callback(validation_result);
        } else |_| {
            var errors = validator.ValidationErrors.init(allocator);
            try errors.add("line", "Parse or validation failed");
            const validation_result = validator.ValidationResult(T){ .invalid = errors };
            try callback(validation_result);
        }
    }
}

// ============================================================================
// Tests
// ============================================================================

test "parseAndValidate - simple struct" {
    const User = struct {
        name: []const u8,
        age: u8,
    };

    const json =
        \\{"name": "Rach", "age": 27}
    ;

    const user = try parseAndValidate(User, json, std.testing.allocator);
    defer std.testing.allocator.free(user.name);
    try std.testing.expectEqualStrings("Rach", user.name);
    try std.testing.expectEqual(@as(u8, 27), user.age);
}

test "parseAndValidate - optional field" {
    const User = struct {
        name: []const u8,
        age: ?u8,
    };

    const json =
        \\{"name": "Alice"}
    ;

    const user = try parseAndValidate(User, json, std.testing.allocator);
    defer std.testing.allocator.free(user.name);
    try std.testing.expectEqualStrings("Alice", user.name);
    try std.testing.expectEqual(@as(?u8, null), user.age);
}

test "parseAndValidate - missing required field" {
    const User = struct {
        name: []const u8,
        age: u8,
    };

    const json = 
        \\{"name": "Bob"}
    ;

    const result = parseAndValidate(User, json, std.testing.allocator);
    try std.testing.expectError(error.ValidationFailed, result);
}

test "parseAndValidate - type mismatch" {
    const User = struct {
        name: []const u8,
        age: u8,
    };

    const json = 
        \\{"name": "Carol", "age": "not a number"}
    ;

    const result = parseAndValidate(User, json, std.testing.allocator);
    try std.testing.expectError(error.ValidationFailed, result);
}

test "parseAndValidate - with validation conventions" {
    const User = struct {
        name_ne: []const u8,
        email: []const u8,
        age: u8,
    };

    const json = 
        \\{"name_ne": "", "email": "invalid", "age": 27}
    ;

    const result = parseAndValidate(User, json, std.testing.allocator);
    try std.testing.expectError(error.ValidationFailed, result);
}

test "batchValidate - array of objects" {
    const User = struct {
        name: []const u8,
        age: u8,
    };

    const json =
        \\[
        \\  {"name": "Alice", "age": 25},
        \\  {"name": "Bob", "age": 30}
        \\]
    ;

    const results = try batchValidate(User, json, std.testing.allocator);
    defer {
        for (results) |result| {
            if (result.isValid()) {
                std.testing.allocator.free(result.valid.name);
            }
        }
        std.testing.allocator.free(results);
    }

    try std.testing.expectEqual(@as(usize, 2), results.len);
    try std.testing.expect(results[0].isValid());
    try std.testing.expect(results[1].isValid());
}
