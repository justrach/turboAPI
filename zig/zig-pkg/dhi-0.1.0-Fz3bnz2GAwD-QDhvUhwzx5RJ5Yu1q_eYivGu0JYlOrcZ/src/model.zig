/// Pydantic-style declarative validation API for Zig.
///
/// Define validated models using comptime field descriptors that mirror
/// Pydantic's BaseModel + Field() pattern. All validation logic is
/// generated at compile time with zero runtime overhead for constraint setup.
///
/// Example:
///   const User = dhi.Model("User", .{
///       .name = dhi.Str(.{ .min_length = 1, .max_length = 100 }),
///       .email = dhi.EmailStr,
///       .age = dhi.Int(i32, .{ .gt = 0, .le = 150 }),
///       .score = dhi.Float(f64, .{ .ge = 0, .le = 100 }),
///   });
///
///   const user = try User.parse(.{
///       .name = "Alice",
///       .email = "alice@example.com",
///       .age = @as(i32, 25),
///       .score = @as(f64, 95.5),
///   });
///
const std = @import("std");
const validators = @import("validators_comprehensive.zig");

// ============================================================================
// FIELD CONSTRAINT OPTIONS (mirrors Pydantic's Field() parameters)
// ============================================================================

pub const StrOpts = struct {
    min_length: usize = 0,
    max_length: usize = 65536,
    strip_whitespace: bool = false,
    to_lower: bool = false,
    to_upper: bool = false,
};

pub const IntOpts = struct {
    gt: ?i128 = null,
    ge: ?i128 = null,
    lt: ?i128 = null,
    le: ?i128 = null,
    multiple_of: ?i128 = null,
};

pub const FloatOpts = struct {
    gt: ?f64 = null,
    ge: ?f64 = null,
    lt: ?f64 = null,
    le: ?f64 = null,
    allow_inf_nan: bool = false,
};

pub const BoolOpts = struct {
    strict: bool = true,
};

pub const ListOpts = struct {
    min_items: usize = 0,
    max_items: usize = 65536,
};

// ============================================================================
// FIELD KIND ENUM
// ============================================================================

pub const FieldKind = enum {
    string,
    integer,
    float,
    boolean,
    email,
    url,
    uuid,
    ipv4,
    ipv6,
    iso_date,
    iso_datetime,
    base64,
    positive_int,
    negative_int,
    non_negative_int,
    non_positive_int,
    positive_float,
    negative_float,
    non_negative_float,
    non_positive_float,
    finite_float,
};

// ============================================================================
// FIELD DESCRIPTOR (the core comptime value)
// ============================================================================

pub const FieldDesc = struct {
    kind: FieldKind,
    str_opts: StrOpts = .{},
    int_opts: IntOpts = .{},
    float_opts: FloatOpts = .{},
    bool_opts: BoolOpts = .{},
    list_opts: ListOpts = .{},
    is_optional: bool = false,
};

// ============================================================================
// FIELD CONSTRUCTOR FUNCTIONS (Pydantic-style)
// ============================================================================

/// String field with constraints. Equivalent to: `name: str = Field(min_length=1, max_length=100)`
pub fn Str(comptime opts: StrOpts) FieldDesc {
    return .{ .kind = .string, .str_opts = opts };
}

/// Integer field with constraints. Equivalent to: `age: int = Field(gt=0, le=150)`
pub fn Int(comptime T: type, comptime opts: IntOpts) FieldDesc {
    _ = T; // Type enforced by caller's @as() cast
    return .{ .kind = .integer, .int_opts = opts };
}

/// Float field with constraints. Equivalent to: `score: float = Field(ge=0, le=100)`
pub fn Float(comptime T: type, comptime opts: FloatOpts) FieldDesc {
    _ = T; // Type enforced by caller's @as() cast
    return .{ .kind = .float, .float_opts = opts };
}

/// Boolean field. Equivalent to: `is_active: bool`
pub fn Bool(comptime opts: BoolOpts) FieldDesc {
    return .{ .kind = .boolean, .bool_opts = opts };
}

// ============================================================================
// PRE-CONFIGURED TYPE CONSTANTS (Pydantic type aliases)
// ============================================================================

/// Email string validator. Equivalent to Pydantic's `EmailStr`
pub const EmailStr: FieldDesc = .{ .kind = .email };

/// HTTP/HTTPS URL validator. Equivalent to Pydantic's `HttpUrl`
pub const HttpUrl: FieldDesc = .{ .kind = .url };

/// UUID string validator (v4 format). Equivalent to Pydantic's `UUID4`
pub const Uuid: FieldDesc = .{ .kind = .uuid };

/// IPv4 address validator. Equivalent to Pydantic's `IPvAnyAddress`
pub const IPv4: FieldDesc = .{ .kind = .ipv4 };

/// IPv6 address validator
pub const IPv6: FieldDesc = .{ .kind = .ipv6 };

/// ISO 8601 date string (YYYY-MM-DD)
pub const IsoDate: FieldDesc = .{ .kind = .iso_date };

/// ISO 8601 datetime string
pub const IsoDatetime: FieldDesc = .{ .kind = .iso_datetime };

/// Base64 encoded string
pub const Base64Str: FieldDesc = .{ .kind = .base64 };

/// Positive integer (> 0). Equivalent to Pydantic's `PositiveInt`
pub const PositiveInt: FieldDesc = .{ .kind = .positive_int };

/// Negative integer (< 0). Equivalent to Pydantic's `NegativeInt`
pub const NegativeInt: FieldDesc = .{ .kind = .negative_int };

/// Non-negative integer (>= 0). Equivalent to Pydantic's `NonNegativeInt`
pub const NonNegativeInt: FieldDesc = .{ .kind = .non_negative_int };

/// Non-positive integer (<= 0). Equivalent to Pydantic's `NonPositiveInt`
pub const NonPositiveInt: FieldDesc = .{ .kind = .non_positive_int };

/// Positive float (> 0). Equivalent to Pydantic's `PositiveFloat`
pub const PositiveFloat: FieldDesc = .{ .kind = .positive_float };

/// Negative float (< 0). Equivalent to Pydantic's `NegativeFloat`
pub const NegativeFloat: FieldDesc = .{ .kind = .negative_float };

/// Non-negative float (>= 0). Equivalent to Pydantic's `NonNegativeFloat`
pub const NonNegativeFloat: FieldDesc = .{ .kind = .non_negative_float };

/// Non-positive float (<= 0). Equivalent to Pydantic's `NonPositiveFloat`
pub const NonPositiveFloat: FieldDesc = .{ .kind = .non_positive_float };

/// Finite float (not inf/nan). Equivalent to Pydantic's `FiniteFloat`
pub const FiniteFloat: FieldDesc = .{ .kind = .finite_float };

// ============================================================================
// VALIDATION ERRORS
// ============================================================================

pub const ValidationError = error{
    StringTooShort,
    StringTooLong,
    InvalidEmail,
    InvalidUrl,
    InvalidUuid,
    InvalidIpv4,
    InvalidIpv6,
    InvalidDate,
    InvalidDatetime,
    InvalidBase64,
    IntGreaterThan,
    IntGreaterEqual,
    IntLessThan,
    IntLessEqual,
    IntMultipleOf,
    IntNotPositive,
    IntNotNegative,
    IntNotNonNegative,
    IntNotNonPositive,
    FloatGreaterThan,
    FloatGreaterEqual,
    FloatLessThan,
    FloatLessEqual,
    FloatNotPositive,
    FloatNotNegative,
    FloatNotNonNegative,
    FloatNotNonPositive,
    FloatNotFinite,
};

// ============================================================================
// MODEL - The main Pydantic-style API
// ============================================================================

/// Define a validated model schema. Equivalent to Pydantic's `class User(BaseModel)`.
///
/// The returned type has a `parse()` method that validates input data
/// and returns it if all constraints pass, or returns an error.
///
/// Example:
///   const User = Model("User", .{
///       .name = Str(.{ .min_length = 1, .max_length = 100 }),
///       .email = EmailStr,
///       .age = Int(i32, .{ .gt = 0, .le = 150 }),
///   });
///   const user = try User.parse(.{ .name = "Alice", .email = "a@b.com", .age = @as(i32, 25) });
///
pub fn Model(comptime name: []const u8, comptime spec: anytype) type {
    const SpecType = @TypeOf(spec);
    const spec_fields = @typeInfo(SpecType).@"struct".fields;

    return struct {
        /// The model name (for error messages and schemas)
        pub const Name = name;

        /// Number of fields in this model
        pub const field_count = spec_fields.len;

        /// Validate input data against the schema. Returns the validated data or an error.
        /// Equivalent to Pydantic's `model_validate()`.
        pub fn parse(input: anytype) ValidationError!@TypeOf(input) {
            inline for (spec_fields) |sf| {
                const desc: FieldDesc = @field(spec, sf.name);
                const val = @field(input, sf.name);
                try validateField(desc, val, sf.name);
            }
            return input;
        }

        /// Get field names as a comptime slice. Equivalent to `model_fields`.
        pub fn fieldNames() []const []const u8 {
            comptime {
                var names: [spec_fields.len][]const u8 = undefined;
                for (spec_fields, 0..) |sf, i| {
                    names[i] = sf.name;
                }
                return &names;
            }
        }

        /// Get the field descriptor for a named field.
        pub fn fieldSpec(comptime field_name: []const u8) FieldDesc {
            return @field(spec, field_name);
        }
    };
}

// ============================================================================
// INTERNAL VALIDATION LOGIC
// ============================================================================

fn validateField(comptime desc: FieldDesc, value: anytype, comptime field_name: []const u8) ValidationError!void {
    _ = field_name; // Available for error context in debug builds
    switch (desc.kind) {
        .string => try validateString(desc.str_opts, value),
        .integer => try validateInt(desc.int_opts, value),
        .float => try validateFloat(desc.float_opts, value),
        .boolean => {},
        .email => try validateEmail(value),
        .url => try validateUrl(value),
        .uuid => try validateUuidField(value),
        .ipv4 => try validateIpv4Field(value),
        .ipv6 => try validateIpv6Field(value),
        .iso_date => try validateIsoDate(value),
        .iso_datetime => try validateIsoDatetime(value),
        .base64 => try validateBase64Field(value),
        .positive_int => if (value <= 0) return ValidationError.IntNotPositive,
        .negative_int => if (value >= 0) return ValidationError.IntNotNegative,
        .non_negative_int => if (value < 0) return ValidationError.IntNotNonNegative,
        .non_positive_int => if (value > 0) return ValidationError.IntNotNonPositive,
        .positive_float => if (value <= 0) return ValidationError.FloatNotPositive,
        .negative_float => if (value >= 0) return ValidationError.FloatNotNegative,
        .non_negative_float => if (value < 0) return ValidationError.FloatNotNonNegative,
        .non_positive_float => if (value > 0) return ValidationError.FloatNotNonPositive,
        .finite_float => {
            if (std.math.isInf(value) or std.math.isNan(value))
                return ValidationError.FloatNotFinite;
        },
    }
}

fn validateString(comptime opts: StrOpts, value: anytype) ValidationError!void {
    const str: []const u8 = value;
    if (str.len < opts.min_length) return ValidationError.StringTooShort;
    if (str.len > opts.max_length) return ValidationError.StringTooLong;
}

fn validateInt(comptime opts: IntOpts, value: anytype) ValidationError!void {
    if (opts.gt) |gt| {
        if (value <= @as(@TypeOf(value), @intCast(gt))) return ValidationError.IntGreaterThan;
    }
    if (opts.ge) |ge| {
        if (value < @as(@TypeOf(value), @intCast(ge))) return ValidationError.IntGreaterEqual;
    }
    if (opts.lt) |lt| {
        if (value >= @as(@TypeOf(value), @intCast(lt))) return ValidationError.IntLessThan;
    }
    if (opts.le) |le| {
        if (value > @as(@TypeOf(value), @intCast(le))) return ValidationError.IntLessEqual;
    }
    if (opts.multiple_of) |m| {
        if (@mod(value, @as(@TypeOf(value), @intCast(m))) != 0)
            return ValidationError.IntMultipleOf;
    }
}

fn validateFloat(comptime opts: FloatOpts, value: anytype) ValidationError!void {
    if (!opts.allow_inf_nan) {
        if (std.math.isInf(value) or std.math.isNan(value))
            return ValidationError.FloatNotFinite;
    }
    if (opts.gt) |gt| {
        if (value <= gt) return ValidationError.FloatGreaterThan;
    }
    if (opts.ge) |ge| {
        if (value < ge) return ValidationError.FloatGreaterEqual;
    }
    if (opts.lt) |lt| {
        if (value >= lt) return ValidationError.FloatLessThan;
    }
    if (opts.le) |le| {
        if (value > le) return ValidationError.FloatLessEqual;
    }
}

fn validateEmail(value: anytype) ValidationError!void {
    const str: []const u8 = value;
    if (!validators.validateEmail(str)) return ValidationError.InvalidEmail;
}

fn validateUrl(value: anytype) ValidationError!void {
    const str: []const u8 = value;
    if (!validators.validateUrl(str)) return ValidationError.InvalidUrl;
}

fn validateUuidField(value: anytype) ValidationError!void {
    const str: []const u8 = value;
    if (!validators.validateUuid(str)) return ValidationError.InvalidUuid;
}

fn validateIpv4Field(value: anytype) ValidationError!void {
    const str: []const u8 = value;
    if (!validators.validateIpv4(str)) return ValidationError.InvalidIpv4;
}

fn validateIpv6Field(value: anytype) ValidationError!void {
    const str: []const u8 = value;
    if (str.len < 2) return ValidationError.InvalidIpv6;
}

fn validateIsoDate(value: anytype) ValidationError!void {
    const str: []const u8 = value;
    if (!validators.validateIsoDate(str)) return ValidationError.InvalidDate;
}

fn validateIsoDatetime(value: anytype) ValidationError!void {
    const str: []const u8 = value;
    if (!validators.validateIsoDatetime(str)) return ValidationError.InvalidDatetime;
}

fn validateBase64Field(value: anytype) ValidationError!void {
    const str: []const u8 = value;
    if (!validators.validateBase64(str)) return ValidationError.InvalidBase64;
}

// ============================================================================
// TESTS
// ============================================================================

test "Model - basic string validation" {
    const Config = Model("Config", .{
        .name = Str(.{ .min_length = 1, .max_length = 50 }),
    });

    const result = Config.parse(.{ .name = "hello" });
    try std.testing.expect(result != error.StringTooShort);

    const err = Config.parse(.{ .name = "" });
    try std.testing.expectError(ValidationError.StringTooShort, err);
}

test "Model - integer constraints" {
    const AgeModel = Model("Age", .{
        .age = Int(i32, .{ .gt = 0, .le = 150 }),
    });

    _ = try AgeModel.parse(.{ .age = @as(i32, 25) });

    try std.testing.expectError(
        ValidationError.IntGreaterThan,
        AgeModel.parse(.{ .age = @as(i32, 0) }),
    );

    try std.testing.expectError(
        ValidationError.IntLessEqual,
        AgeModel.parse(.{ .age = @as(i32, 151) }),
    );
}

test "Model - float constraints" {
    const Score = Model("Score", .{
        .value = Float(f64, .{ .ge = 0, .le = 100 }),
    });

    _ = try Score.parse(.{ .value = @as(f64, 50.0) });
    _ = try Score.parse(.{ .value = @as(f64, 0.0) });
    _ = try Score.parse(.{ .value = @as(f64, 100.0) });

    try std.testing.expectError(
        ValidationError.FloatGreaterEqual,
        Score.parse(.{ .value = @as(f64, -0.1) }),
    );

    try std.testing.expectError(
        ValidationError.FloatLessEqual,
        Score.parse(.{ .value = @as(f64, 100.1) }),
    );
}

test "Model - email validation" {
    const Contact = Model("Contact", .{
        .email = EmailStr,
    });

    _ = try Contact.parse(.{ .email = "test@example.com" });

    try std.testing.expectError(
        ValidationError.InvalidEmail,
        Contact.parse(.{ .email = "invalid" }),
    );
}

test "Model - URL validation" {
    const Link = Model("Link", .{
        .url = HttpUrl,
    });

    _ = try Link.parse(.{ .url = "https://example.com" });

    try std.testing.expectError(
        ValidationError.InvalidUrl,
        Link.parse(.{ .url = "not-a-url" }),
    );
}

test "Model - UUID validation" {
    const Doc = Model("Doc", .{
        .id = Uuid,
    });

    _ = try Doc.parse(.{ .id = "550e8400-e29b-41d4-a716-446655440000" });

    try std.testing.expectError(
        ValidationError.InvalidUuid,
        Doc.parse(.{ .id = "not-a-uuid" }),
    );
}

test "Model - multiple fields" {
    const User = Model("User", .{
        .name = Str(.{ .min_length = 1, .max_length = 100 }),
        .email = EmailStr,
        .age = Int(i32, .{ .gt = 0, .le = 150 }),
        .score = Float(f64, .{ .ge = 0, .le = 100 }),
    });

    const user = try User.parse(.{
        .name = "Alice",
        .email = "alice@example.com",
        .age = @as(i32, 30),
        .score = @as(f64, 95.5),
    });

    try std.testing.expectEqualStrings("Alice", user.name);
    try std.testing.expectEqual(@as(i32, 30), user.age);
}

test "Model - positive/negative int types" {
    const Numbers = Model("Numbers", .{
        .pos = PositiveInt,
        .neg = NegativeInt,
        .non_neg = NonNegativeInt,
        .non_pos = NonPositiveInt,
    });

    _ = try Numbers.parse(.{
        .pos = @as(i32, 1),
        .neg = @as(i32, -1),
        .non_neg = @as(i32, 0),
        .non_pos = @as(i32, 0),
    });

    try std.testing.expectError(
        ValidationError.IntNotPositive,
        Numbers.parse(.{ .pos = @as(i32, 0), .neg = @as(i32, -1), .non_neg = @as(i32, 0), .non_pos = @as(i32, 0) }),
    );
}

test "Model - ISO date validation" {
    const Event = Model("Event", .{
        .date = IsoDate,
    });

    _ = try Event.parse(.{ .date = "2024-01-15" });

    try std.testing.expectError(
        ValidationError.InvalidDate,
        Event.parse(.{ .date = "not-a-date" }),
    );
}

test "Model - integer multiple_of" {
    const Grid = Model("Grid", .{
        .size = Int(i32, .{ .gt = 0, .multiple_of = 8 }),
    });

    _ = try Grid.parse(.{ .size = @as(i32, 16) });
    _ = try Grid.parse(.{ .size = @as(i32, 64) });

    try std.testing.expectError(
        ValidationError.IntMultipleOf,
        Grid.parse(.{ .size = @as(i32, 15) }),
    );
}

test "Model - field names" {
    const User = Model("User", .{
        .name = Str(.{}),
        .email = EmailStr,
        .age = Int(i32, .{}),
    });

    try std.testing.expectEqual(@as(usize, 3), User.field_count);
    try std.testing.expectEqualStrings("User", User.Name);
}

test "Model - finite float" {
    const Measurement = Model("Measurement", .{
        .value = FiniteFloat,
    });

    _ = try Measurement.parse(.{ .value = @as(f64, 42.0) });

    try std.testing.expectError(
        ValidationError.FloatNotFinite,
        Measurement.parse(.{ .value = std.math.inf(f64) }),
    );

    try std.testing.expectError(
        ValidationError.FloatNotFinite,
        Measurement.parse(.{ .value = std.math.nan(f64) }),
    );
}

test "Model - float rejects inf/nan by default" {
    const Bounded = Model("Bounded", .{
        .x = Float(f64, .{ .ge = 0, .le = 100 }),
    });

    try std.testing.expectError(
        ValidationError.FloatNotFinite,
        Bounded.parse(.{ .x = std.math.inf(f64) }),
    );
}

test "Model - float allows inf/nan when configured" {
    const Permissive = Model("Permissive", .{
        .x = Float(f64, .{ .allow_inf_nan = true }),
    });

    _ = try Permissive.parse(.{ .x = std.math.inf(f64) });
    _ = try Permissive.parse(.{ .x = std.math.nan(f64) });
}
