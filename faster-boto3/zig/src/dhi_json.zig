// DHI-validated JSON parser for faster-boto3.
// Combines Zig JSON parsing + DHI schema validation in one pass.
// Used for DynamoDB responses where we know the exact shape.
//
// Two modes:
// 1. parse_validated: Parse JSON + validate against schema → typed dict
// 2. parse_dynamo: Fast DynamoDB Item extraction with type safety

const std = @import("std");
const Allocator = std.mem.Allocator;

// ── DynamoDB type system ────────────────────────────────────────────────────

pub const DynamoType = enum {
    S, // String
    N, // Number
    B, // Binary
    BOOL,
    NULL,
    L, // List
    M, // Map
    SS, // String Set
    NS, // Number Set
    BS, // Binary Set
};

pub const DynamoValue = struct {
    key: []const u8,
    dtype: DynamoType,
    value: []const u8, // raw value as string
};

pub const ParseResult = struct {
    items: []DynamoValue,
    valid: bool,
    error_msg: ?[]const u8,
};

// ── Fast DynamoDB JSON parser ───────────────────────────────────────────────
// DynamoDB items look like: {"pk":{"S":"val"},"count":{"N":"42"}}
// We parse with std.json (fast) and extract typed values with validation.

pub fn parseDynamoResponse(allocator: Allocator, json_bytes: []const u8) ParseResult {
    const parsed = std.json.parseFromSlice(std.json.Value, allocator, json_bytes, .{}) catch {
        return .{ .items = &.{}, .valid = false, .error_msg = "Invalid JSON" };
    };
    defer parsed.deinit();

    return extractDynamoItems(allocator, parsed.value);
}

fn extractDynamoItems(allocator: Allocator, root: std.json.Value) ParseResult {
    // Handle {"Item": {...}} wrapper
    const item_obj = if (root == .object)
        if (root.object.get("Item")) |item|
            if (item == .object) item.object else null
        else if (root == .object) root.object else null
    else
        null;

    if (item_obj == null) {
        // Try unwrapping {"Responses": {"table": [...]}} for BatchGet
        if (root == .object) {
            if (root.object.get("Responses")) |responses| {
                return extractBatchResponse(allocator, responses);
            }
        }
        return .{ .items = &.{}, .valid = true, .error_msg = null };
    }

    return extractFromObject(allocator, item_obj.?);
}

fn extractFromObject(allocator: Allocator, obj: std.json.ObjectMap) ParseResult {
    var results: std.ArrayList(DynamoValue) = .empty;

    var it = obj.iterator();
    while (it.next()) |entry| {
        const key = entry.key_ptr.*;
        const type_wrapper = entry.value_ptr.*;

        if (type_wrapper != .object) continue;

        // Extract {"S": "val"} / {"N": "42"} / {"BOOL": true} etc.
        var type_it = type_wrapper.object.iterator();
        if (type_it.next()) |type_entry| {
            const type_str = type_entry.key_ptr.*;
            const val = type_entry.value_ptr.*;

            const dtype = parseDynamoType(type_str) orelse continue;
            const value_str = extractValueString(val);

            results.append(allocator, .{
                .key = key,
                .dtype = dtype,
                .value = value_str,
            }) catch continue;
        }
    }

    return .{
        .items = results.toOwnedSlice(allocator) catch &.{},
        .valid = true,
        .error_msg = null,
    };
}

fn extractBatchResponse(allocator: Allocator, responses: std.json.Value) ParseResult {
    if (responses != .object) return .{ .items = &.{}, .valid = true, .error_msg = null };

    var all_results: std.ArrayList(DynamoValue) = .empty;

    var table_it = responses.object.iterator();
    while (table_it.next()) |table_entry| {
        const items_array = table_entry.value_ptr.*;
        if (items_array != .array) continue;

        for (items_array.array.items) |item| {
            if (item != .object) continue;
            const result = extractFromObject(allocator, item.object);
            for (result.items) |dv| {
                all_results.append(allocator, dv) catch continue;
            }
            if (result.items.len > 0) allocator.free(result.items);
        }
    }

    return .{
        .items = all_results.toOwnedSlice(allocator) catch &.{},
        .valid = true,
        .error_msg = null,
    };
}

fn parseDynamoType(s: []const u8) ?DynamoType {
    if (std.mem.eql(u8, s, "S")) return .S;
    if (std.mem.eql(u8, s, "N")) return .N;
    if (std.mem.eql(u8, s, "B")) return .B;
    if (std.mem.eql(u8, s, "BOOL")) return .BOOL;
    if (std.mem.eql(u8, s, "NULL")) return .NULL;
    if (std.mem.eql(u8, s, "L")) return .L;
    if (std.mem.eql(u8, s, "M")) return .M;
    if (std.mem.eql(u8, s, "SS")) return .SS;
    if (std.mem.eql(u8, s, "NS")) return .NS;
    if (std.mem.eql(u8, s, "BS")) return .BS;
    return null;
}

fn extractValueString(val: std.json.Value) []const u8 {
    return switch (val) {
        .string => |s| s,
        .bool => |b| if (b) "true" else "false",
        .null => "null",
        .integer => "0", // caller should use raw JSON
        .float => "0.0",
        else => "",
    };
}

// ── Validation: check DynamoDB item against expected schema ─────────────────

pub const FieldSpec = struct {
    name: []const u8,
    expected_type: DynamoType,
    required: bool = true,
};

pub const ItemSchema = struct {
    fields: []const FieldSpec,
};

pub fn validateDynamoItem(
    items: []const DynamoValue,
    schema: *const ItemSchema,
) struct { valid: bool, error_msg: ?[]const u8 } {
    for (schema.fields) |field| {
        if (field.required) {
            var found = false;
            for (items) |item| {
                if (std.mem.eql(u8, item.key, field.name)) {
                    found = true;
                    if (item.dtype != field.expected_type) {
                        return .{ .valid = false, .error_msg = "type mismatch" };
                    }
                    break;
                }
            }
            if (!found) {
                return .{ .valid = false, .error_msg = "missing required field" };
            }
        }
    }
    return .{ .valid = true, .error_msg = null };
}

// ── Tests ───────────────────────────────────────────────────────────────────

test "parseDynamoResponse single item" {
    const json =
        \\{"Item":{"pk":{"S":"user-1"},"name":{"S":"Rach"},"score":{"N":"42"}}}
    ;
    const result = parseDynamoResponse(std.testing.allocator, json);
    defer std.testing.allocator.free(result.items);
    try std.testing.expect(result.valid);
    try std.testing.expectEqual(@as(usize, 3), result.items.len);
}

test "parseDynamoResponse validates type" {
    const items = [_]DynamoValue{
        .{ .key = "pk", .dtype = .S, .value = "user-1" },
        .{ .key = "score", .dtype = .N, .value = "42" },
    };
    const schema = ItemSchema{ .fields = &.{
        .{ .name = "pk", .expected_type = .S },
        .{ .name = "score", .expected_type = .N },
    } };
    const vr = validateDynamoItem(&items, &schema);
    try std.testing.expect(vr.valid);
}
