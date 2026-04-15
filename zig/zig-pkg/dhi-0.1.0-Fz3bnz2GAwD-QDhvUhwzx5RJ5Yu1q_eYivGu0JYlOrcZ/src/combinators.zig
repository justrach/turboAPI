const std = @import("std");
const validator = @import("validator");

/// Optional wraps a type T and allows null/missing values.
/// Wraps a type T and allows null/missing values.
///
/// Example:
///   const MaybeAge = Optional(validator.BoundedInt(u8, 0, 130));
///   const age1 = try MaybeAge.init(27);      // Some(27)
///   const age2 = try MaybeAge.init(null);    // None
pub fn Optional(comptime T: type) type {
    return struct {
        const Self = @This();
        value: ?T,

        pub fn init(v: ?T) !Self {
            return .{ .value = v };
        }

        pub fn initSome(v: T) !Self {
            return .{ .value = v };
        }

        pub fn initNone() Self {
            return .{ .value = null };
        }

        pub fn isSome(self: Self) bool {
            return self.value != null;
        }

        pub fn isNone(self: Self) bool {
            return self.value == null;
        }

        pub fn unwrap(self: Self) ?T {
            return self.value;
        }

        pub fn unwrapOr(self: Self, default: T) T {
            return self.value orelse default;
        }
    };
}

/// Default wraps a type T and provides a default value if validation fails or value is missing.
/// Wraps a type T and provides a default value if validation fails or value is missing.
///
/// Example:
///   const AgeWithDefault = Default(u8, 18);
///   const age = AgeWithDefault.init(null);  // Returns 18
pub fn Default(comptime T: type, comptime default_value: T) type {
    return struct {
        const Self = @This();
        value: T,

        pub fn init(v: ?T) Self {
            return .{ .value = v orelse default_value };
        }

        pub fn initOrDefault(v: T) Self {
            return .{ .value = v };
        }

        pub fn getDefault() T {
            return default_value;
        }
    };
}

/// Transform wraps a type and applies a transformation function.
/// Useful for coercion, normalization, etc.
///
/// Example:
///   const Lowercase = Transform([]const u8, toLowerCase);
pub fn Transform(comptime T: type, comptime transformFn: fn (T) T) type {
    return struct {
        const Self = @This();
        value: T,

        pub fn init(v: T) Self {
            return .{ .value = transformFn(v) };
        }

        pub fn transform(v: T) T {
            return transformFn(v);
        }
    };
}

/// OneOf validates that a value is one of a set of allowed values.
/// Validates that a value is one of a set of allowed values.
///
/// Example:
///   const Status = OneOf([]const u8, &.{"active", "pending", "closed"});
pub fn OneOf(comptime T: type, comptime allowed: []const T) type {
    return struct {
        const Self = @This();
        value: T,

        pub fn init(v: T) !Self {
            for (allowed) |allowed_val| {
                if (std.meta.eql(v, allowed_val)) {
                    return .{ .value = v };
                }
            }
            return error.InvalidValue;
        }

        pub fn validate(v: T, errors: *validator.ValidationErrors, field_name: []const u8) !T {
            for (allowed) |allowed_val| {
                if (std.meta.eql(v, allowed_val)) {
                    return v;
                }
            }
            try errors.add(field_name, "Value not in allowed set");
            return error.ValidationFailed;
        }

        pub fn getAllowed() []const T {
            return allowed;
        }
    };
}

/// AllOf requires a value to satisfy multiple validators.
/// Useful for composing validation rules.
pub fn AllOf(comptime validators_list: anytype) type {
    return struct {
        const Self = @This();

        pub fn validate(v: anytype, errors: *validator.ValidationErrors, field_name: []const u8) !@TypeOf(v) {
            inline for (validators_list) |ValidatorType| {
                _ = ValidatorType.validate(v, errors, field_name) catch {};
            }
            if (errors.hasErrors()) {
                return error.ValidationFailed;
            }
            return v;
        }
    };
}

/// Range creates a validator for numeric ranges (similar to BoundedInt but more flexible).
pub fn Range(comptime T: type, comptime min: ?T, comptime max: ?T) type {
    return struct {
        const Self = @This();
        value: T,

        pub fn init(v: T) !Self {
            if (min) |min_val| {
                if (v < min_val) return error.BelowMinimum;
            }
            if (max) |max_val| {
                if (v > max_val) return error.AboveMaximum;
            }
            return .{ .value = v };
        }

        pub fn validate(v: T, errors: *validator.ValidationErrors, field_name: []const u8) !T {
            if (min) |min_val| {
                if (v < min_val) {
                    const msg = try std.fmt.allocPrint(
                        errors.allocator,
                        "Value {d} must be >= {d}",
                        .{ v, min_val },
                    );
                    defer errors.allocator.free(msg);
                    try errors.add(field_name, msg);
                    return error.ValidationFailed;
                }
            }
            if (max) |max_val| {
                if (v > max_val) {
                    const msg = try std.fmt.allocPrint(
                        errors.allocator,
                        "Value {d} must be <= {d}",
                        .{ v, max_val },
                    );
                    defer errors.allocator.free(msg);
                    try errors.add(field_name, msg);
                    return error.ValidationFailed;
                }
            }
            return v;
        }

        pub fn bounds() struct { min: ?T, max: ?T } {
            return .{ .min = min, .max = max };
        }
    };
}

// ============================================================================
// Tests
// ============================================================================

test "Optional - some value" {
    const MaybeInt = Optional(u32);
    const val = try MaybeInt.initSome(42);
    try std.testing.expect(val.isSome());
    try std.testing.expectEqual(@as(u32, 42), val.unwrap().?);
}

test "Optional - none value" {
    const MaybeInt = Optional(u32);
    const val = MaybeInt.initNone();
    try std.testing.expect(val.isNone());
    try std.testing.expectEqual(@as(?u32, null), val.unwrap());
}

test "Default - with value" {
    const AgeWithDefault = Default(u8, 18);
    const age = AgeWithDefault.init(25);
    try std.testing.expectEqual(@as(u8, 25), age.value);
}

test "Default - without value" {
    const AgeWithDefault = Default(u8, 18);
    const age = AgeWithDefault.init(null);
    try std.testing.expectEqual(@as(u8, 18), age.value);
}

test "OneOf - valid value" {
    const Status = OneOf(u8, &.{ 1, 2, 3 });
    const status = try Status.init(2);
    try std.testing.expectEqual(@as(u8, 2), status.value);
}

test "OneOf - invalid value" {
    const Status = OneOf(u8, &.{ 1, 2, 3 });
    const result = Status.init(5);
    try std.testing.expectError(error.InvalidValue, result);
}

test "Range - within bounds" {
    const Score = Range(f32, 0.0, 100.0);
    const score = try Score.init(75.5);
    try std.testing.expectEqual(@as(f32, 75.5), score.value);
}

test "Range - below minimum" {
    const Score = Range(f32, 0.0, 100.0);
    const result = Score.init(-5.0);
    try std.testing.expectError(error.BelowMinimum, result);
}

test "Range - above maximum" {
    const Score = Range(f32, 0.0, 100.0);
    const result = Score.init(105.0);
    try std.testing.expectError(error.AboveMaximum, result);
}

test "Range - no minimum" {
    const Score = Range(i32, null, 100);
    const score = try Score.init(-50);
    try std.testing.expectEqual(@as(i32, -50), score.value);
}

test "Range - no maximum" {
    const Score = Range(i32, 0, null);
    const score = try Score.init(1000);
    try std.testing.expectEqual(@as(i32, 1000), score.value);
}
