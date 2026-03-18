// dhi_validator.zig — Runtime JSON schema validation for TurboAPI.
// Validates request bodies in Zig before touching the Python GIL.
// Supports nested objects, unions (str | int), typed arrays, and Field constraints.

const std = @import("std");

const allocator = std.heap.c_allocator;

// ── Schema types ────────────────────────────────────────────────────────────

pub const FieldType = enum {
    string,
    integer,
    float,
    boolean,
    array,
    object,
    union_type,
    any,
};

pub const FieldConstraint = struct {
    name: []const u8,
    field_type: FieldType,
    required: bool = true,
    // String constraints
    min_length: ?usize = null,
    max_length: ?usize = null,
    // Numeric constraints
    gt: ?f64 = null,
    ge: ?f64 = null,
    lt: ?f64 = null,
    le: ?f64 = null,
    // Nested object schema (for type=object with a dhi model)
    nested_schema: ?*const ModelSchema = null,
    // Array item type (for type=array with typed items like list[str])
    items_type: ?FieldType = null,
    // Array item schema (for type=array with nested models like list[ContactInfo])
    items_schema: ?*const ModelSchema = null,
    // Union allowed types (for type=union like str | int)
    union_types: ?[]const FieldType = null,
};

pub const ModelSchema = struct {
    name: []const u8,
    fields: []const FieldConstraint,
};

pub const ValidationResult = union(enum) {
    ok: []const u8,
    err: ValidationError,
};

pub const ValidationError = struct {
    status_code: u16,
    body: []const u8,

    pub fn deinit(self: ValidationError) void {
        if (self.body.len > 0) allocator.free(@constCast(self.body));
    }
};

// ── Validation ──────────────────────────────────────────────────────────────

/// Validate raw JSON bytes against a runtime schema.
pub fn validateJson(json_bytes: []const u8, schema: *const ModelSchema) ValidationResult {
    const parsed = std.json.parseFromSlice(std.json.Value, allocator, json_bytes, .{}) catch {
        return .{ .err = makeError(422, "Invalid JSON") };
    };
    defer parsed.deinit();

    return validateObject(parsed.value, schema, "body");
}

fn validateObject(value: std.json.Value, schema: *const ModelSchema, path: []const u8) ValidationResult {
    if (value != .object) {
        return .{ .err = makePathError(422, path, "Expected JSON object") };
    }

    for (schema.fields) |field| {
        const val_opt = value.object.get(field.name);

        if (val_opt == null) {
            if (field.required) {
                const field_path = joinPath(path, field.name);
                defer allocator.free(field_path);
                return .{ .err = makePathError(422, field_path, "Field is required") };
            }
            continue;
        }

        const val = val_opt.?;

        // Null check — allowed for optional fields
        if (val == .null) {
            if (field.required) {
                const field_path = joinPath(path, field.name);
                defer allocator.free(field_path);
                return .{ .err = makePathError(422, field_path, "Field is required") };
            }
            continue;
        }

        const field_path = joinPath(path, field.name);
        defer allocator.free(field_path);

        const result = validateField(val, &field, field_path);
        switch (result) {
            .ok => {},
            .err => return result,
        }
    }

    return .{ .ok = "" };
}

fn validateField(val: std.json.Value, field: *const FieldConstraint, path: []const u8) ValidationResult {
    switch (field.field_type) {
        .string => {
            if (val != .string) return .{ .err = makePathError(422, path, "Expected string") };
            return validateStringConstraints(val.string, field, path);
        },
        .integer => {
            if (val != .integer) return .{ .err = makePathError(422, path, "Expected integer") };
            const v: f64 = @floatFromInt(val.integer);
            return validateNumericConstraints(v, field, path);
        },
        .float => {
            const v: f64 = if (val == .float) val.float else if (val == .integer) @as(f64, @floatFromInt(val.integer)) else {
                return .{ .err = makePathError(422, path, "Expected number") };
            };
            return validateNumericConstraints(v, field, path);
        },
        .boolean => {
            if (val != .bool) return .{ .err = makePathError(422, path, "Expected boolean") };
        },
        .object => {
            if (val != .object) return .{ .err = makePathError(422, path, "Expected object") };
            // Recursively validate nested schema
            if (field.nested_schema) |ns| {
                return validateObject(val, ns, path);
            }
        },
        .array => {
            if (val != .array) return .{ .err = makePathError(422, path, "Expected array") };
            // Validate array items
            for (val.array.items, 0..) |item, i| {
                const idx_str = std.fmt.allocPrint(allocator, "{s}[{d}]", .{ path, i }) catch continue;
                defer allocator.free(idx_str);

                // Check item schema (nested model array)
                if (field.items_schema) |is| {
                    const r = validateObject(item, is, idx_str);
                    switch (r) {
                        .ok => {},
                        .err => return r,
                    }
                }
                // Check item type (simple typed array)
                else if (field.items_type) |it| {
                    if (!checkType(item, it)) {
                        return .{ .err = makePathError(422, idx_str, "Invalid item type") };
                    }
                }
            }
        },
        .union_type => {
            // Check if value matches any of the union types
            if (field.union_types) |types| {
                var matched = false;
                for (types) |t| {
                    if (checkType(val, t)) {
                        matched = true;
                        break;
                    }
                }
                if (!matched) {
                    return .{ .err = makePathError(422, path, "Value does not match any union type") };
                }
            }
        },
        .any => {},
    }

    return .{ .ok = "" };
}

fn checkType(val: std.json.Value, t: FieldType) bool {
    return switch (t) {
        .string => val == .string,
        .integer => val == .integer,
        .float => val == .float or val == .integer,
        .boolean => val == .bool,
        .array => val == .array,
        .object => val == .object,
        .any => true,
        .union_type => true,
    };
}

fn validateStringConstraints(s: []const u8, field: *const FieldConstraint, path: []const u8) ValidationResult {
    if (field.min_length) |ml| {
        if (s.len < ml) return .{ .err = makePathError(422, path, "String too short") };
    }
    if (field.max_length) |ml| {
        if (s.len > ml) return .{ .err = makePathError(422, path, "String too long") };
    }
    return .{ .ok = "" };
}

fn validateNumericConstraints(v: f64, field: *const FieldConstraint, path: []const u8) ValidationResult {
    if (field.gt) |gt| {
        if (v <= gt) return .{ .err = makePathError(422, path, "Value must be greater than constraint") };
    }
    if (field.ge) |ge| {
        if (v < ge) return .{ .err = makePathError(422, path, "Value must be >= constraint") };
    }
    if (field.lt) |lt| {
        if (v >= lt) return .{ .err = makePathError(422, path, "Value must be less than constraint") };
    }
    if (field.le) |le| {
        if (v > le) return .{ .err = makePathError(422, path, "Value must be <= constraint") };
    }
    return .{ .ok = "" };
}

// ── Error formatting ────────────────────────────────────────────────────────

fn makeError(status: u16, detail: []const u8) ValidationError {
    const body = std.fmt.allocPrint(allocator,
        \\{{"detail":[{{"msg":"{s}","type":"value_error"}}]}}
    , .{detail}) catch "";
    return .{ .status_code = status, .body = body };
}

fn makePathError(status: u16, path: []const u8, msg: []const u8) ValidationError {
    const body = std.fmt.allocPrint(allocator,
        \\{{"detail":[{{"loc":["{s}"],"msg":"{s}","type":"value_error"}}]}}
    , .{ path, msg }) catch "";
    return .{ .status_code = status, .body = body };
}

fn joinPath(parent: []const u8, child: []const u8) []const u8 {
    return std.fmt.allocPrint(allocator, "{s}.{s}", .{ parent, child }) catch child;
}

// ── Schema parsing ──────────────────────────────────────────────────────────

/// Parse a JSON schema descriptor (from Python) into a ModelSchema.
pub fn parseSchema(schema_json: []const u8) ?ModelSchema {
    const parsed = std.json.parseFromSlice(std.json.Value, allocator, schema_json, .{}) catch return null;
    const result = parseSchemaValue(parsed.value);
    if (result == null) parsed.deinit();
    return result;
}

fn parseSchemaValue(root: std.json.Value) ?ModelSchema {
    if (root != .object) return null;

    const name_val = root.object.get("name") orelse return null;
    if (name_val != .string) return null;
    const name = allocator.dupe(u8, name_val.string) catch return null;

    const fields_val = root.object.get("fields") orelse return null;
    if (fields_val != .array) return null;

    const fields = allocator.alloc(FieldConstraint, fields_val.array.items.len) catch return null;

    for (fields_val.array.items, 0..) |item, i| {
        fields[i] = parseFieldConstraint(item) orelse return null;
    }

    return ModelSchema{ .name = name, .fields = fields };
}

fn parseFieldConstraint(item: std.json.Value) ?FieldConstraint {
    if (item != .object) return null;

    const fname = item.object.get("name") orelse return null;
    if (fname != .string) return null;

    const ftype_str = if (item.object.get("type")) |t| (if (t == .string) t.string else "any") else "any";
    const ft = parseFieldType(ftype_str);

    var fc = FieldConstraint{
        .name = allocator.dupe(u8, fname.string) catch return null,
        .field_type = ft,
        .required = if (item.object.get("required")) |r| (if (r == .bool) r.bool else true) else true,
        .min_length = extractUsize(item.object.get("min_length")),
        .max_length = extractUsize(item.object.get("max_length")),
        .gt = if (item.object.get("gt")) |v| extractFloat(v) else null,
        .ge = if (item.object.get("ge")) |v| extractFloat(v) else null,
        .lt = if (item.object.get("lt")) |v| extractFloat(v) else null,
        .le = if (item.object.get("le")) |v| extractFloat(v) else null,
    };

    // Parse nested schema (for object fields with a dhi model)
    if (item.object.get("schema")) |schema_val| {
        if (parseSchemaValue(schema_val)) |nested| {
            const heap_schema = allocator.create(ModelSchema) catch return null;
            heap_schema.* = nested;
            fc.nested_schema = heap_schema;
        }
    }

    // Parse items_schema (for array fields with nested models like list[ContactInfo])
    if (item.object.get("items_schema")) |is_val| {
        if (parseSchemaValue(is_val)) |nested| {
            const heap_schema = allocator.create(ModelSchema) catch return null;
            heap_schema.* = nested;
            fc.items_schema = heap_schema;
        }
    }

    // Parse items_type (for typed arrays like list[str])
    if (item.object.get("items_type")) |it_val| {
        if (it_val == .string) {
            fc.items_type = parseFieldType(it_val.string);
        }
    }

    // Parse union_types (for union fields like str | int)
    if (item.object.get("union_types")) |ut_val| {
        if (ut_val == .array) {
            const types = allocator.alloc(FieldType, ut_val.array.items.len) catch return null;
            for (ut_val.array.items, 0..) |t, j| {
                types[j] = if (t == .string) parseFieldType(t.string) else .any;
            }
            fc.union_types = types;
        }
    }

    return fc;
}

fn extractFloat(v: std.json.Value) ?f64 {
    return switch (v) {
        .float => v.float,
        .integer => @as(f64, @floatFromInt(v.integer)),
        else => null,
    };
}

fn extractUsize(v_opt: ?std.json.Value) ?usize {
    const v = v_opt orelse return null;
    if (v == .integer and v.integer >= 0) return @intCast(v.integer);
    return null;
}

fn parseFieldType(s: []const u8) FieldType {
    if (std.mem.eql(u8, s, "string") or std.mem.eql(u8, s, "str")) return .string;
    if (std.mem.eql(u8, s, "integer") or std.mem.eql(u8, s, "int")) return .integer;
    if (std.mem.eql(u8, s, "float") or std.mem.eql(u8, s, "number")) return .float;
    if (std.mem.eql(u8, s, "boolean") or std.mem.eql(u8, s, "bool")) return .boolean;
    if (std.mem.eql(u8, s, "array") or std.mem.eql(u8, s, "list")) return .array;
    if (std.mem.eql(u8, s, "object") or std.mem.eql(u8, s, "dict")) return .object;
    if (std.mem.eql(u8, s, "union")) return .union_type;
    return .any;
}

// ── Fuzz tests ───────────────────────────────────────────────────────────────
// Run: zig build fuzz-json  (then execute the binary with --fuzz)

const fuzz_schema = ModelSchema{
    .name = "FuzzModel",
    .fields = &[_]FieldConstraint{
        .{ .name = "name",  .field_type = .string,  .required = true,  .min_length = 1, .max_length = 100 },
        .{ .name = "age",   .field_type = .integer,  .required = true,  .gt = 0, .lt = 200 },
        .{ .name = "score", .field_type = .float,    .required = false },
        .{ .name = "tags",  .field_type = .array,    .required = false, .items_type = .string },
        .{ .name = "meta",  .field_type = .object,   .required = false },
        .{ .name = "flag",  .field_type = .boolean,  .required = false },
    },
};

fn fuzz_validateJson(_: void, input: []const u8) anyerror!void {
    const result = validateJson(input, &fuzz_schema);
    switch (result) {
        .ok => {},
        .err => |e| {
            defer e.deinit();
            // Must always be a client-error status, never 500
            try std.testing.expect(e.status_code == 400 or e.status_code == 422);
            // Error body must be non-empty
            try std.testing.expect(e.body.len > 0);
        },
    }
}

test "fuzz: validateJson — never panics, always ok or 4xx" {
    try std.testing.fuzz({}, fuzz_validateJson, .{ .corpus = &.{
        // Happy path
        "{\"name\":\"Alice\",\"age\":30}",
        // Missing required field
        "{\"name\":\"Bob\"}",
        // Wrong types
        "{\"name\":123,\"age\":\"old\"}",
        // Null values
        "{\"name\":null,\"age\":null}",
        // Empty object
        "{}",
        // Empty input
        "",
        // Not JSON
        "hello world",
        // Deeply nested meta (depth probe)
        "{\"name\":\"x\",\"age\":1,\"meta\":{\"a\":{\"b\":{\"c\":{\"d\":{\"e\":{}}}}}}}",
        // Constraint violations
        "{\"name\":\"\",\"age\":1}",
        "{\"name\":\"x\",\"age\":-5}",
        "{\"name\":\"x\",\"age\":999}",
        // Float in integer field
        "{\"name\":\"x\",\"age\":1.5}",
        // Array of mixed types
        "{\"name\":\"x\",\"age\":1,\"tags\":[1,null,true,\"ok\"]}",
        // Invalid UTF-8 byte sequence
        "{\"name\":\"\xFF\xFE\",\"age\":1}",
        // Unicode name
        "{\"name\":\"\xE3\x81\x93\xE3\x82\x93\",\"age\":1}",
        // Very large integer
        "{\"name\":\"x\",\"age\":99999999999999999999}",
        // Extra unknown fields (should be ignored / ok)
        "{\"name\":\"x\",\"age\":1,\"unknown\":\"extra\",\"another\":42}",
        // JSON array at top level instead of object
        "[{\"name\":\"x\",\"age\":1}]",
        // JSON string at top level
        "\"just a string\"",
        // Trailing garbage after valid JSON
        "{\"name\":\"x\",\"age\":1}garbage",
    }});
}
