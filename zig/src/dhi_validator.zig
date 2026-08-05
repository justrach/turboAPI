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

const field_type_map = std.StaticStringMap(FieldType).initComptime(.{
    .{ "string", .string },
    .{ "str", .string },
    .{ "integer", .integer },
    .{ "int", .integer },
    .{ "number", .float },
    .{ "float", .float },
    .{ "boolean", .boolean },
    .{ "bool", .boolean },
    .{ "array", .array },
    .{ "list", .array },
    .{ "object", .object },
    .{ "dict", .object },
    .{ "union", .union_type },
    .{ "any", .any },
});

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

/// Result that retains the parsed JSON tree on success (caller must deinit).
pub const ValidateParseResult = union(enum) {
    ok: std.json.Parsed(std.json.Value),
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

/// String-aware nesting-depth pre-check for attacker-controlled JSON. Both
/// std.json's Value parser and the recursive validators recurse per nesting
/// level, so a deeply nested body (e.g. a megabyte of '[') would overflow the
/// worker stack and kill the process. Cheap O(n) scan; brackets inside
/// strings are ignored so legitimate payloads are never miscounted.
pub fn jsonNestingWithinLimit(data: []const u8, max_depth: usize) bool {
    var depth: usize = 0;
    var in_string = false;
    var escaped = false;
    for (data) |ch| {
        if (in_string) {
            if (escaped) {
                escaped = false;
            } else if (ch == '\\') {
                escaped = true;
            } else if (ch == '"') {
                in_string = false;
            }
            continue;
        }
        switch (ch) {
            '"' => in_string = true,
            '{', '[' => {
                depth += 1;
                if (depth > max_depth) return false;
            },
            '}', ']' => depth -|= 1,
            else => {},
        }
    }
    return true;
}

pub const MAX_JSON_NESTING: usize = 256;

/// Validate raw JSON bytes against a runtime schema.
pub fn validateJson(json_bytes: []const u8, schema: *const ModelSchema) ValidationResult {
    if (!jsonNestingWithinLimit(json_bytes, MAX_JSON_NESTING)) {
        return .{ .err = makeError(422, "JSON nesting too deep") };
    }
    // TODO: arena
    const parsed = std.json.parseFromSlice(std.json.Value, allocator, json_bytes, .{}) catch {
        return .{ .err = makeError(422, "Invalid JSON") };
    };
    defer parsed.deinit();

    var path_buf: [MAX_PATH_LEN]u8 = undefined;
    @memcpy(path_buf[0..4], "body");
    return validateObject(parsed.value, schema, &path_buf, 4);
}

/// Validate and return the parsed JSON tree — avoids a second parse in model_sync.
/// On success the caller owns the Parsed value and must call .deinit().
pub fn validateJsonRetainParsed(json_bytes: []const u8, schema: *const ModelSchema) ValidateParseResult {
    if (!jsonNestingWithinLimit(json_bytes, MAX_JSON_NESTING)) {
        return .{ .err = makeError(422, "JSON nesting too deep") };
    }
    const parsed = std.json.parseFromSlice(std.json.Value, allocator, json_bytes, .{}) catch {
        return .{ .err = makeError(422, "Invalid JSON") };
    };

    var path_buf: [MAX_PATH_LEN]u8 = undefined;
    @memcpy(path_buf[0..4], "body");
    const vr = validateObject(parsed.value, schema, &path_buf, 4);
    switch (vr) {
        .ok => return .{ .ok = parsed },
        .err => |e| {
            parsed.deinit();
            return .{ .err = e };
        },
    }
}

/// Maximum length of a validation error path ("body.items[3].name"). Paths
/// are built in a shared stack buffer — the previous per-field allocPrint
/// made every successful validation pay heap alloc/free cycles (and let an
/// attacker with a huge array force thousands of allocations per request).
const MAX_PATH_LEN: usize = 512;

/// Append ".name" or "[i]" to the shared path buffer, returning the new
/// length. On overflow the path is truncated — acceptable because it only
/// appears in error messages.
fn appendPath(path_buf: *[MAX_PATH_LEN]u8, path_len: usize, comptime fmt: []const u8, args: anytype) usize {
    const s = std.fmt.bufPrint(path_buf[path_len..], fmt, args) catch return path_buf.len;
    return path_len + s.len;
}

fn validateObject(value: std.json.Value, schema: *const ModelSchema, path_buf: *[MAX_PATH_LEN]u8, path_len: usize) ValidationResult {
    if (value != .object) {
        return .{ .err = makePathError(422, path_buf[0..path_len], "Expected JSON object") };
    }

    for (schema.fields) |field| {
        const val_opt = value.object.get(field.name);

        if (val_opt == null) {
            if (field.required) {
                const flen = appendPath(path_buf, path_len, ".{s}", .{field.name});
                return .{ .err = makePathError(422, path_buf[0..flen], "Field is required") };
            }
            continue;
        }

        const val = val_opt.?;

        // Null check — allowed for optional fields
        if (val == .null) {
            if (field.required) {
                const flen = appendPath(path_buf, path_len, ".{s}", .{field.name});
                return .{ .err = makePathError(422, path_buf[0..flen], "Field is required") };
            }
            continue;
        }

        const flen = appendPath(path_buf, path_len, ".{s}", .{field.name});
        const result = validateField(val, &field, path_buf, flen);
        switch (result) {
            .ok => {},
            .err => return result,
        }
    }

    return .{ .ok = "" };
}

fn validateField(val: std.json.Value, field: *const FieldConstraint, path_buf: *[MAX_PATH_LEN]u8, path_len: usize) ValidationResult {
    const path = path_buf[0..path_len];
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
                return validateObject(val, ns, path_buf, path_len);
            }
        },
        .array => {
            if (val != .array) return .{ .err = makePathError(422, path, "Expected array") };
            // Validate array items
            for (val.array.items, 0..) |item, i| {
                const ilen = appendPath(path_buf, path_len, "[{d}]", .{i});

                // Check item schema (nested model array)
                if (field.items_schema) |is| {
                    const r = validateObject(item, is, path_buf, ilen);
                    switch (r) {
                        .ok => {},
                        .err => return r,
                    }
                }
                // Check item type (simple typed array)
                else if (field.items_type) |it| {
                    if (!checkType(item, it)) {
                        return .{ .err = makePathError(422, path_buf[0..ilen], "Invalid item type") };
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
    var buf: [256]u8 = undefined;
    const body = std.fmt.bufPrint(&buf,
        \\{{"detail":[{{"msg":"{s}","type":"value_error"}}]}}
    , .{detail}) catch "";
    const owned = allocator.dupe(u8, body) catch return .{ .status_code = status, .body = "" };
    return .{ .status_code = status, .body = owned };
}

fn makePathError(status: u16, path: []const u8, msg: []const u8) ValidationError {
    const body = std.fmt.allocPrint(allocator,
        \\{{"detail":[{{"loc":["{s}"],"msg":"{s}","type":"value_error"}}]}}
    , .{ path, msg }) catch "";
    return .{ .status_code = status, .body = body };
}

// ── Schema parsing ──────────────────────────────────────────────────────────

/// Parse a JSON schema descriptor (from Python) into a ModelSchema.
pub fn parseSchema(schema_json: []const u8) ?ModelSchema {
    const parsed = std.json.parseFromSlice(std.json.Value, allocator, schema_json, .{}) catch return null;
    defer parsed.deinit();
    return parseSchemaValue(parsed.value) catch null;
}

/// Free a parsed schema and everything it owns (used on parse-failure paths;
/// successfully parsed schemas live for the process lifetime).
fn freeSchema(schema: *const ModelSchema) void {
    allocator.free(schema.name);
    for (schema.fields) |*f| freeField(f);
    allocator.free(schema.fields);
}

fn freeField(f: *const FieldConstraint) void {
    allocator.free(f.name);
    if (f.nested_schema) |ns| {
        freeSchema(ns);
        allocator.destroy(ns);
    }
    if (f.items_schema) |is| {
        freeSchema(is);
        allocator.destroy(is);
    }
    if (f.union_types) |ut| allocator.free(ut);
}

// Error-union internals so errdefer can clean up partial allocations —
// the old optional-return version leaked the duped name, the fields array,
// prior fields, nested schemas and union types on every early null return.
// Explicit error set: the functions are mutually recursive, so inferred
// error sets would form a dependency loop.
const SchemaParseError = error{ InvalidSchema, OutOfMemory };

fn parseSchemaValue(root: std.json.Value) SchemaParseError!ModelSchema {
    if (root != .object) return error.InvalidSchema;

    const name_val = root.object.get("name") orelse return error.InvalidSchema;
    if (name_val != .string) return error.InvalidSchema;
    const name = allocator.dupe(u8, name_val.string) catch return error.OutOfMemory;
    errdefer allocator.free(name);

    const fields_val = root.object.get("fields") orelse return error.InvalidSchema;
    if (fields_val != .array) return error.InvalidSchema;

    const fields = allocator.alloc(FieldConstraint, fields_val.array.items.len) catch return error.OutOfMemory;
    errdefer allocator.free(fields);
    var parsed_fields: usize = 0;
    errdefer for (fields[0..parsed_fields]) |*f| freeField(f);

    for (fields_val.array.items, 0..) |item, i| {
        fields[i] = try parseFieldConstraint(item);
        parsed_fields = i + 1;
    }

    return ModelSchema{ .name = name, .fields = fields };
}

fn parseFieldConstraint(item: std.json.Value) SchemaParseError!FieldConstraint {
    if (item != .object) return error.InvalidSchema;

    const fname = item.object.get("name") orelse return error.InvalidSchema;
    if (fname != .string) return error.InvalidSchema;

    const ftype_str = if (item.object.get("type")) |t| (if (t == .string) t.string else "any") else "any";
    const ft = parseFieldType(ftype_str);

    var fc = FieldConstraint{
        .name = allocator.dupe(u8, fname.string) catch return error.OutOfMemory,
        .field_type = ft,
        .required = if (item.object.get("required")) |r| (if (r == .bool) r.bool else true) else true,
        .min_length = extractUsize(item.object.get("min_length")),
        .max_length = extractUsize(item.object.get("max_length")),
        .gt = if (item.object.get("gt")) |v| extractFloat(v) else null,
        .ge = if (item.object.get("ge")) |v| extractFloat(v) else null,
        .lt = if (item.object.get("lt")) |v| extractFloat(v) else null,
        .le = if (item.object.get("le")) |v| extractFloat(v) else null,
    };
    errdefer freeField(&fc);

    // Parse nested schema (for object fields with a dhi model)
    if (item.object.get("schema")) |schema_val| {
        if (parseSchemaValue(schema_val) catch null) |nested| {
            const heap_schema = allocator.create(ModelSchema) catch {
                var n = nested;
                freeSchema(&n);
                return error.OutOfMemory;
            };
            heap_schema.* = nested;
            fc.nested_schema = heap_schema;
        }
    }

    // Parse items_schema (for array fields with nested models like list[ContactInfo])
    if (item.object.get("items_schema")) |is_val| {
        if (parseSchemaValue(is_val) catch null) |nested| {
            const heap_schema = allocator.create(ModelSchema) catch {
                var n = nested;
                freeSchema(&n);
                return error.OutOfMemory;
            };
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
            const types = allocator.alloc(FieldType, ut_val.array.items.len) catch return error.OutOfMemory;
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
    return field_type_map.get(s) orelse .any;
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

fn fuzz_validateJson(_: void, smith: *std.testing.Smith) anyerror!void {
    const input = smith.in orelse return;
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
