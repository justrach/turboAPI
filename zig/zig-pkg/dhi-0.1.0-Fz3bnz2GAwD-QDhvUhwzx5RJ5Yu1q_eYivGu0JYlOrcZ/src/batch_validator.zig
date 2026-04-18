/// High-performance batch validation system
/// Designed to minimize FFI overhead by validating multiple items in a single call
const std = @import("std");

/// Field validator type enum
pub const ValidatorType = enum(u8) {
    BoundedInt,
    BoundedString,
    Email,
    None,
};

/// Schema field definition for batch validation
pub const SchemaField = extern struct {
    field_name: [*:0]const u8,
    field_name_len: u32,
    validator_type: ValidatorType,
    
    // Parameters (interpretation depends on validator_type)
    param1: i64, // For BoundedInt: min, For BoundedString: min_len
    param2: i64, // For BoundedInt: max, For BoundedString: max_len
    
    // Offset in the data structure (for direct memory access)
    offset: u32,
    data_type: DataType,
};

/// Data type for field values
pub const DataType = enum(u8) {
    Int64,
    String,
};

/// Validation result for a single item
pub const ValidationResult = extern struct {
    is_valid: u8, // 0 = invalid, 1 = valid
    error_count: u32,
    first_error_field_idx: u32, // Index of first failing field
};

/// Batch validation context
pub const BatchValidator = struct {
    allocator: std.mem.Allocator,
    schema: []const SchemaField,
    
    pub fn init(allocator: std.mem.Allocator, schema: []const SchemaField) BatchValidator {
        return .{
            .allocator = allocator,
            .schema = schema,
        };
    }
    
    /// Validate a batch of items with the given schema
    /// Returns array of ValidationResult (one per item)
    pub fn validateBatch(
        self: *BatchValidator,
        items: []const []const u8, // Array of serialized item data
        results: []ValidationResult,
    ) !usize {
        if (items.len != results.len) return error.LengthMismatch;
        
        var valid_count: usize = 0;
        
        for (items, 0..) |item_data, i| {
            const result = self.validateItem(item_data);
            results[i] = result;
            if (result.is_valid == 1) valid_count += 1;
        }
        
        return valid_count;
    }
    
    /// Validate a single item against the schema
    fn validateItem(self: *BatchValidator, item_data: []const u8) ValidationResult {
        var result = ValidationResult{
            .is_valid = 1,
            .error_count = 0,
            .first_error_field_idx = 0,
        };
        
        for (self.schema, 0..) |field, field_idx| {
            const is_valid = self.validateField(field, item_data);
            if (!is_valid) {
                result.is_valid = 0;
                result.error_count += 1;
                if (result.error_count == 1) {
                    result.first_error_field_idx = @intCast(field_idx);
                }
            }
        }
        
        return result;
    }
    
    /// Validate a single field
    fn validateField(self: *BatchValidator, field: SchemaField, item_data: []const u8) bool {
        _ = self;
        _ = item_data;
        
        // TODO: Implement proper field extraction from item_data
        // For now, this is a placeholder for the generic schema-based validator
        switch (field.validator_type) {
            .BoundedInt => {
                // TODO: Extract int value from item_data at field.offset
                // For now, placeholder
                return true;
            },
            .BoundedString => {
                // TODO: Extract string from item_data at field.offset
                return true;
            },
            .Email => {
                // TODO: Extract string and validate email
                return true;
            },
            .None => return true,
        }
    }
};

/// Optimized batch validation for common user struct pattern
/// This is a specialized fast path for the common case
pub const UserBatchValidator = struct {
    name_min: usize,
    name_max: usize,
    age_min: i64,
    age_max: i64,
    
    pub fn init(name_min: usize, name_max: usize, age_min: i64, age_max: i64) UserBatchValidator {
        return .{
            .name_min = name_min,
            .name_max = name_max,
            .age_min = age_min,
            .age_max = age_max,
        };
    }
    
    /// Validate batch of users (name, email, age)
    /// Optimized for minimal overhead
    pub fn validateBatch(
        self: *const UserBatchValidator,
        names: []const [*:0]const u8,
        emails: []const [*:0]const u8,
        ages: []const i64,
        results: []u8,
    ) usize {
        if (names.len != emails.len or names.len != ages.len or names.len != results.len) {
            return 0;
        }
        
        var valid_count: usize = 0;
        
        for (0..names.len) |i| {
            var is_valid = true;
            
            // Validate name length
            const name_len = std.mem.len(names[i]);
            if (name_len < self.name_min or name_len > self.name_max) {
                is_valid = false;
            }
            
            // Validate email (only if name is valid, for short-circuit)
            if (is_valid) {
                const email = std.mem.span(emails[i]);
                if (!validateEmail(email)) {
                    is_valid = false;
                }
            }
            
            // Validate age
            if (is_valid) {
                if (ages[i] < self.age_min or ages[i] > self.age_max) {
                    is_valid = false;
                }
            }
            
            results[i] = if (is_valid) 1 else 0;
            if (is_valid) valid_count += 1;
        }
        
        return valid_count;
    }
};

/// Fast email validation
inline fn validateEmail(email: []const u8) bool {
    const at_pos = std.mem.indexOf(u8, email, "@") orelse return false;
    if (at_pos == 0) return false; // No local part
    
    const domain = email[at_pos + 1..];
    if (domain.len == 0) return false; // No domain
    if (std.mem.indexOf(u8, domain, ".") == null) return false; // No TLD
    
    return true;
}

/// SIMD-optimized batch integer validation (when available)
pub fn validateIntBatchSIMD(
    values: []const i64,
    min: i64,
    max: i64,
    results: []u8,
) usize {
    if (values.len != results.len) return 0;
    
    var valid_count: usize = 0;
    
    // TODO: Use SIMD when available (Zig 0.12+ has better SIMD support)
    // For now, use simple loop with potential for auto-vectorization
    for (values, 0..) |value, i| {
        const is_valid = value >= min and value <= max;
        results[i] = if (is_valid) 1 else 0;
        if (is_valid) valid_count += 1;
    }
    
    return valid_count;
}

/// Batch string length validation
pub fn validateStringLengthBatch(
    strings: []const [*:0]const u8,
    min_len: usize,
    max_len: usize,
    results: []u8,
) usize {
    if (strings.len != results.len) return 0;
    
    var valid_count: usize = 0;
    
    for (strings, 0..) |str, i| {
        const len = std.mem.len(str);
        const is_valid = len >= min_len and len <= max_len;
        results[i] = if (is_valid) 1 else 0;
        if (is_valid) valid_count += 1;
    }
    
    return valid_count;
}

/// Batch email validation
pub fn validateEmailBatch(
    emails: []const [*:0]const u8,
    results: []u8,
) usize {
    if (emails.len != results.len) return 0;
    
    var valid_count: usize = 0;
    
    for (emails, 0..) |email_ptr, i| {
        const email = std.mem.span(email_ptr);
        const is_valid = validateEmail(email);
        results[i] = if (is_valid) 1 else 0;
        if (is_valid) valid_count += 1;
    }
    
    return valid_count;
}

test "UserBatchValidator basic" {
    const validator = UserBatchValidator.init(1, 100, 18, 120);
    
    const names = [_][*:0]const u8{ "Alice", "Bob", "" }; // Last one invalid
    const emails = [_][*:0]const u8{ "alice@example.com", "bob@example.com", "invalid" };
    const ages = [_]i64{ 25, 30, 15 }; // Last one invalid
    var results: [3]u8 = undefined;
    
    const valid_count = validator.validateBatch(&names, &emails, &ages, &results);
    
    try std.testing.expectEqual(@as(usize, 2), valid_count);
    try std.testing.expectEqual(@as(u8, 1), results[0]);
    try std.testing.expectEqual(@as(u8, 1), results[1]);
    try std.testing.expectEqual(@as(u8, 0), results[2]);
}

test "validateIntBatchSIMD" {
    const values = [_]i64{ 25, 30, 150, 18, 90 };
    var results: [5]u8 = undefined;
    
    const valid_count = validateIntBatchSIMD(&values, 18, 90, &results);
    
    try std.testing.expectEqual(@as(usize, 4), valid_count);
    try std.testing.expectEqual(@as(u8, 1), results[0]);
    try std.testing.expectEqual(@as(u8, 1), results[1]);
    try std.testing.expectEqual(@as(u8, 0), results[2]); // 150 out of range
    try std.testing.expectEqual(@as(u8, 1), results[3]);
    try std.testing.expectEqual(@as(u8, 1), results[4]);
}
