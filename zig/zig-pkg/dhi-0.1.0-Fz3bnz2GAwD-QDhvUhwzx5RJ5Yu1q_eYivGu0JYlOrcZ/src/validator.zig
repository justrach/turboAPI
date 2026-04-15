const std = @import("std");

/// ValidationError represents a single validation failure with field path and message.
/// Represents a single validation failure with field path and message.
pub const ValidationError = struct {
    field: []const u8,
    message: []const u8,
    path: []const []const u8,
    allocator: std.mem.Allocator,

    pub fn init(allocator: std.mem.Allocator, field: []const u8, message: []const u8) !ValidationError {
        const field_copy = try allocator.dupe(u8, field);
        const message_copy = try allocator.dupe(u8, message);
        return .{
            .field = field_copy,
            .message = message_copy,
            .path = &.{},
            .allocator = allocator,
        };
    }

    pub fn initWithPath(allocator: std.mem.Allocator, field: []const u8, message: []const u8, path: []const []const u8) !ValidationError {
        const field_copy = try allocator.dupe(u8, field);
        const message_copy = try allocator.dupe(u8, message);
        const path_copy = try allocator.alloc([]const u8, path.len);
        for (path, 0..) |segment, i| {
            path_copy[i] = try allocator.dupe(u8, segment);
        }
        return .{
            .field = field_copy,
            .message = message_copy,
            .path = path_copy,
            .allocator = allocator,
        };
    }

    pub fn deinit(self: *ValidationError) void {
        self.allocator.free(self.field);
        self.allocator.free(self.message);
        for (self.path) |segment| {
            self.allocator.free(segment);
        }
        if (self.path.len > 0) self.allocator.free(self.path);
    }

    /// Format error as "field: message" or "path.to.field: message"
    pub fn format(
        self: ValidationError,
        writer: anytype,
    ) !void {

        if (self.path.len > 0) {
            for (self.path, 0..) |segment, i| {
                try writer.writeAll(segment);
                if (i < self.path.len - 1) try writer.writeAll(".");
            }
            try writer.writeAll(".");
            try writer.writeAll(self.field);
        } else {
            try writer.writeAll(self.field);
        }
        try writer.writeAll(": ");
        try writer.writeAll(self.message);
    }
};

/// ValidationErrors collects multiple validation failures.
/// Supports non-fail-fast validation — collects all errors for a single struct.
pub const ValidationErrors = struct {
    errors: std.ArrayList(ValidationError),
    allocator: std.mem.Allocator,

    pub fn init(allocator: std.mem.Allocator) ValidationErrors {
        return .{ 
            .errors = std.ArrayList(ValidationError).empty,
            .allocator = allocator,
        };
    }

    pub fn deinit(self: *ValidationErrors) void {
        for (self.errors.items) |*err| {
            err.deinit();
        }
        self.errors.deinit(self.allocator);
    }

    pub fn add(self: *ValidationErrors, field: []const u8, message: []const u8) !void {
        const err = try ValidationError.init(self.allocator, field, message);
        try self.errors.append(self.allocator, err);
    }

    pub fn addWithPath(self: *ValidationErrors, field: []const u8, message: []const u8, path: []const []const u8) !void {
        const err = try ValidationError.initWithPath(self.allocator, field, message, path);
        try self.errors.append(self.allocator, err);
    }

    pub fn hasErrors(self: ValidationErrors) bool {
        return self.errors.items.len > 0;
    }

    pub fn count(self: ValidationErrors) usize {
        return self.errors.items.len;
    }

    /// Print all errors to writer, one per line
    pub fn format(
        self: ValidationErrors,
        writer: anytype,
    ) !void {
        for (self.errors.items, 0..) |err, i| {
            try err.format(writer);
            if (i < self.errors.items.len - 1) try writer.writeAll("\n");
        }
    }
};

/// BoundedInt creates a validated integer type with compile-time bounds.
/// Creates a validated integer type with compile-time bounds (ge=min, le=max).
///
/// Example:
///   const Age = BoundedInt(u8, 0, 130);
///   const age = try Age.init(27);  // OK
///   const bad = try Age.init(200); // error.OutOfRange
pub fn BoundedInt(comptime T: type, comptime min: T, comptime max: T) type {
    return struct {
        const Self = @This();
        value: T,

        pub fn init(v: T) !Self {
            if (v < min or v > max) return error.OutOfRange;
            return .{ .value = v };
        }

        pub fn validate(v: T, errors: *ValidationErrors, field_name: []const u8) !T {
            if (v < min or v > max) {
                const msg = try std.fmt.allocPrint(
                    errors.allocator,
                    "Value {d} must be >= {d} and <= {d}",
                    .{ v, min, max },
                );
                defer errors.allocator.free(msg);
                try errors.add(field_name, msg);
                return error.ValidationFailed;
            }
            return v;
        }

        pub fn bounds() struct { min: T, max: T } {
            return .{ .min = min, .max = max };
        }
    };
}

/// BoundedString creates a validated string type with length constraints.
/// Creates a validated string type with length constraints (min_length, max_length).
///
/// Example:
///   const Name = BoundedString(1, 40);
///   const name = try Name.init("Rach");  // OK
///   const bad = try Name.init("");       // error.TooShort
pub fn BoundedString(comptime min_len: usize, comptime max_len: usize) type {
    return struct {
        const Self = @This();
        slice: []const u8,

        pub fn init(s: []const u8) !Self {
            if (s.len < min_len) return error.TooShort;
            if (s.len > max_len) return error.TooLong;
            return .{ .slice = s };
        }

        pub fn validate(s: []const u8, errors: *ValidationErrors, field_name: []const u8) ![]const u8 {
            if (s.len < min_len) {
                const msg = try std.fmt.allocPrint(
                    errors.allocator,
                    "String length {d} must be >= {d}",
                    .{ s.len, min_len },
                );
                defer errors.allocator.free(msg);
                try errors.add(field_name, msg);
                return error.ValidationFailed;
            }
            if (s.len > max_len) {
                const msg = try std.fmt.allocPrint(
                    errors.allocator,
                    "String length {d} must be <= {d}",
                    .{ s.len, max_len },
                );
                defer errors.allocator.free(msg);
                try errors.add(field_name, msg);
                return error.ValidationFailed;
            }
            return s;
        }

        pub fn bounds() struct { min_len: usize, max_len: usize } {
            return .{ .min_len = min_len, .max_len = max_len };
        }
    };
}

/// Email validates email format using a simplified RFC 5322 check.
/// Validates email format using a simplified RFC 5322 check.
pub const Email = struct {
    value: []const u8,

    pub fn init(s: []const u8) !Email {
        if (!isValidEmail(s)) return error.InvalidEmail;
        return .{ .value = s };
    }

    pub fn validate(s: []const u8, errors: *ValidationErrors, field_name: []const u8) ![]const u8 {
        if (!isValidEmail(s)) {
            try errors.add(field_name, "Invalid email format (expected: local@domain)");
            return error.ValidationFailed;
        }
        return s;
    }

    fn isValidEmail(s: []const u8) bool {
        // Simplified check: has exactly one @, non-empty local and domain parts
        var at_count: usize = 0;
        var at_pos: usize = 0;
        for (s, 0..) |c, i| {
            if (c == '@') {
                at_count += 1;
                at_pos = i;
            }
        }
        if (at_count != 1) return false;
        if (at_pos == 0 or at_pos == s.len - 1) return false;
        
        // Check for at least one dot in domain
        const domain = s[at_pos + 1 ..];
        const has_dot = std.mem.indexOf(u8, domain, ".") != null;
        return has_dot;
    }
};

/// Pattern validates strings against a regex pattern (conceptual - requires regex lib).
/// Validates strings against a regex pattern (conceptual — requires regex lib).
///
/// Note: Zig doesn't have std.regex yet. This is a placeholder for when you add
/// a regex library like https://github.com/tiehuis/zig-regex or similar.
pub fn Pattern(comptime pattern: []const u8) type {
    return struct {
        const Self = @This();
        value: []const u8,

        pub fn init(s: []const u8) !Self {
            return .{ .value = s };
        }

        pub fn validate(s: []const u8, errors: *ValidationErrors, field_name: []const u8) ![]const u8 {
            // TODO: Implement regex matching
            _ = errors;
            _ = field_name;
            return s;
        }

        pub fn getPattern() []const u8 {
            return pattern;
        }
    };
}

/// ValidationResult represents the outcome of validation.
/// Contains either a valid value or a list of errors.
pub fn ValidationResult(comptime T: type) type {
    return union(enum) {
        valid: T,
        invalid: ValidationErrors,

        pub fn isValid(self: @This()) bool {
            return self == .valid;
        }

        pub fn value(self: @This()) ?T {
            return switch (self) {
                .valid => |v| v,
                .invalid => null,
            };
        }

        pub fn errors(self: @This()) ?ValidationErrors {
            return switch (self) {
                .valid => null,
                .invalid => |e| e,
            };
        }

        pub fn deinit(self: *@This()) void {
            switch (self.*) {
                .valid => {},
                .invalid => |*e| e.deinit(),
            }
        }
    };
}

/// validateStruct uses @typeInfo to validate struct fields based on naming conventions.
/// Uses @typeInfo to validate struct fields based on naming conventions.
///
/// Field naming conventions:
///   - "*_ne": Non-empty string (min_length=1)
///   - "*_email": Email format
///   - Can be extended with more conventions
///
/// Example:
///   const User = struct {
///       name_ne: []const u8,
///       email: []const u8,
///       age: u8,
///   };
pub fn validateStruct(comptime T: type, val: T, errors: *ValidationErrors) !void {
    const info = @typeInfo(T);
    if (info != .@"struct") @compileError("validateStruct expects a struct");

    inline for (info.@"struct".fields) |f| {
        const field_val = @field(val, f.name);

        // Convention: fields ending with "_ne" must be non-empty strings
        if (std.mem.endsWith(u8, f.name, "_ne")) {
            if (@TypeOf(field_val) == []const u8 and field_val.len == 0) {
                try errors.add(f.name, "Field cannot be empty");
            }
        }

        // Convention: fields named "email" or ending with "_email" must be valid emails
        if (std.mem.eql(u8, f.name, "email") or std.mem.endsWith(u8, f.name, "_email")) {
            if (@TypeOf(field_val) == []const u8) {
                _ = Email.validate(field_val, errors, f.name) catch {};
            }
        }

        // TODO: Add more conventions (min/max, regex, etc.)
    }
}

/// deriveValidator generates a validation function for a struct at comptime.
/// This is a more advanced pattern that can be extended with field tags or attributes.
pub fn deriveValidator(comptime T: type) type {
    return struct {
        pub fn validate(val: anytype, allocator: std.mem.Allocator) !ValidationResult(T) {
            var errors = ValidationErrors.init(allocator);

            // Use @typeInfo to walk fields and apply validation rules
            validateStruct(T, val, &errors) catch {
                // Validation failed, but errors are already collected
            };

            if (errors.hasErrors()) {
                return ValidationResult(T){ .invalid = errors };
            } else {
                errors.deinit();
                return ValidationResult(T){ .valid = val };
            }
        }
    };
}

// ============================================================================
// Tests
// ============================================================================

test "BoundedInt - valid range" {
    const Age = BoundedInt(u8, 0, 130);
    const age = try Age.init(27);
    try std.testing.expectEqual(@as(u8, 27), age.value);
}

test "BoundedInt - out of range" {
    const Age = BoundedInt(u8, 0, 130);
    const result = Age.init(200);
    try std.testing.expectError(error.OutOfRange, result);
}

test "BoundedInt - validate with errors" {
    const Age = BoundedInt(u8, 18, 90);
    var errors = ValidationErrors.init(std.testing.allocator);
    defer errors.deinit();

    _ = Age.validate(15, &errors, "age") catch {};
    try std.testing.expect(errors.hasErrors());
    try std.testing.expectEqual(@as(usize, 1), errors.count());
}

test "BoundedString - valid length" {
    const Name = BoundedString(1, 40);
    const name = try Name.init("Rach");
    try std.testing.expectEqualStrings("Rach", name.slice);
}

test "BoundedString - too short" {
    const Name = BoundedString(1, 40);
    const result = Name.init("");
    try std.testing.expectError(error.TooShort, result);
}

test "BoundedString - too long" {
    const Name = BoundedString(1, 10);
    const result = Name.init("ThisIsWayTooLongForTheLimit");
    try std.testing.expectError(error.TooLong, result);
}

test "Email - valid format" {
    const email = try Email.init("rach@example.com");
    try std.testing.expectEqualStrings("rach@example.com", email.value);
}

test "Email - invalid format (no @)" {
    const result = Email.init("notanemail");
    try std.testing.expectError(error.InvalidEmail, result);
}

test "Email - invalid format (no domain)" {
    const result = Email.init("rach@");
    try std.testing.expectError(error.InvalidEmail, result);
}

test "ValidationError - format with path" {
    var err = try ValidationError.initWithPath(
        std.testing.allocator,
        "age",
        "Must be >= 18",
        &.{ "user", "profile" },
    );
    defer err.deinit();

    var buf: [100]u8 = undefined;
    const formatted = try std.fmt.bufPrint(&buf, "{f}", .{err});
    try std.testing.expectEqualStrings("user.profile.age: Must be >= 18", formatted);
}

test "ValidationErrors - collect multiple" {
    var errors = ValidationErrors.init(std.testing.allocator);
    defer errors.deinit();

    try errors.add("age", "Must be >= 18");
    try errors.add("email", "Invalid format");

    try std.testing.expectEqual(@as(usize, 2), errors.count());
    try std.testing.expect(errors.hasErrors());
}

test "ValidationResult - valid case" {
    const Result = ValidationResult(u32);
    const result = Result{ .valid = 42 };

    try std.testing.expect(result.isValid());
    try std.testing.expectEqual(@as(u32, 42), result.value().?);
}

test "ValidationResult - invalid case" {
    const Result = ValidationResult(u32);
    var errors = ValidationErrors.init(std.testing.allocator);
    try errors.add("value", "Too large");

    var result = Result{ .invalid = errors };
    defer result.deinit();

    try std.testing.expect(!result.isValid());
    try std.testing.expectEqual(@as(?u32, null), result.value());
}

test "validateStruct - non-empty convention" {
    const User = struct {
        name_ne: []const u8,
        age: u8,
    };

    var errors = ValidationErrors.init(std.testing.allocator);
    defer errors.deinit();

    const user = User{ .name_ne = "", .age = 27 };
    try validateStruct(User, user, &errors);

    try std.testing.expect(errors.hasErrors());
    try std.testing.expectEqual(@as(usize, 1), errors.count());
}

test "validateStruct - email convention" {
    const User = struct {
        email: []const u8,
        age: u8,
    };

    var errors = ValidationErrors.init(std.testing.allocator);
    defer errors.deinit();

    const user = User{ .email = "not-an-email", .age = 27 };
    try validateStruct(User, user, &errors);

    try std.testing.expect(errors.hasErrors());
}

test "deriveValidator - happy path" {
    const User = struct {
        name: []const u8,
        age: u8,
    };

    const Validator = deriveValidator(User);
    const user = User{ .name = "Rach", .age = 27 };

    var result = try Validator.validate(user, std.testing.allocator);
    defer result.deinit();

    try std.testing.expect(result.isValid());
}
