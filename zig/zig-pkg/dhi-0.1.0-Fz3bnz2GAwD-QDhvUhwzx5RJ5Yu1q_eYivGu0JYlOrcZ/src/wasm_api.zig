const std = @import("std");
const validators = @import("validators_comprehensive.zig");
const simd = @import("simd_validators.zig");
const ultra = @import("ultra_validator.zig");
const simd_string = @import("simd_string.zig");

// WASM exports for JavaScript
// All functions use simple types that work across WASM boundary

// String validators
export fn validate_email(ptr: [*]const u8, len: usize) bool {
    const email = ptr[0..len];
    return validators.validateEmail(email);
}

export fn validate_url(ptr: [*]const u8, len: usize) bool {
    const url = ptr[0..len];
    return validators.validateUrl(url);
}

export fn validate_uuid(ptr: [*]const u8, len: usize) bool {
    const uuid = ptr[0..len];
    return validators.validateUuid(uuid);
}

export fn validate_ipv4(ptr: [*]const u8, len: usize) bool {
    const ip = ptr[0..len];
    return validators.validateIpv4(ip);
}

export fn validate_string_length(_: [*]const u8, len: usize, min: usize, max: usize) bool {
    return len >= min and len <= max;
}

export fn validate_iso_date(ptr: [*]const u8, len: usize) bool {
    const date = ptr[0..len];
    return validators.validateIsoDate(date);
}

export fn validate_iso_datetime(ptr: [*]const u8, len: usize) bool {
    const datetime = ptr[0..len];
    return validators.validateIsoDatetime(datetime);
}

export fn validate_base64(ptr: [*]const u8, len: usize) bool {
    const data = ptr[0..len];
    return validators.validateBase64(data);
}

// Additional string validators
export fn validate_starts_with(str_ptr: [*]const u8, str_len: usize, prefix_ptr: [*]const u8, prefix_len: usize) bool {
    const str = str_ptr[0..str_len];
    const prefix = prefix_ptr[0..prefix_len];
    return validators.validateStartsWith(str, prefix);
}

export fn validate_ends_with(str_ptr: [*]const u8, str_len: usize, suffix_ptr: [*]const u8, suffix_len: usize) bool {
    const str = str_ptr[0..str_len];
    const suffix = suffix_ptr[0..suffix_len];
    return validators.validateEndsWith(str, suffix);
}

export fn validate_contains(str_ptr: [*]const u8, str_len: usize, substring_ptr: [*]const u8, substring_len: usize) bool {
    const str = str_ptr[0..str_len];
    const substring = substring_ptr[0..substring_len];
    return validators.validateContains(str, substring);
}

// Number validators (i64 - requires BigInt in JS)
export fn validate_int(value: i64, min: i64, max: i64) bool {
    return value >= min and value <= max;
}

// 🚀 FAST i32 variant - works with regular JS numbers (no BigInt needed!)
export fn validate_int_i32(value: i32, min: i32, max: i32) bool {
    return value >= min and value <= max;
}

// 🚀 FAST i32 comparison variants (no BigInt needed!)
export fn validate_int_gt_i32(value: i32, min: i32) bool {
    return value > min;
}

export fn validate_int_gte_i32(value: i32, min: i32) bool {
    return value >= min;
}

export fn validate_int_lt_i32(value: i32, max: i32) bool {
    return value < max;
}

export fn validate_int_lte_i32(value: i32, max: i32) bool {
    return value <= max;
}

export fn validate_int_positive_i32(value: i32) bool {
    return value > 0;
}

export fn validate_int_negative_i32(value: i32) bool {
    return value < 0;
}

export fn validate_int_nonnegative_i32(value: i32) bool {
    return value >= 0;
}

export fn validate_int_nonpositive_i32(value: i32) bool {
    return value <= 0;
}

export fn validate_int_multiple_of_i32(value: i32, divisor: i32) bool {
    if (divisor == 0) return false;
    return @mod(value, divisor) == 0;
}

export fn validate_int_gt(value: i64, min: i64) bool {
    return validators.validateGt(i64, value, min);
}

export fn validate_int_gte(value: i64, min: i64) bool {
    return validators.validateGte(i64, value, min);
}

export fn validate_int_lt(value: i64, max: i64) bool {
    return validators.validateLt(i64, value, max);
}

export fn validate_int_lte(value: i64, max: i64) bool {
    return validators.validateLte(i64, value, max);
}

export fn validate_int_positive(value: i64) bool {
    return validators.validatePositive(i64, value);
}

export fn validate_int_non_negative(value: i64) bool {
    return validators.validateNonNegative(i64, value);
}

export fn validate_int_multiple_of(value: i64, divisor: i64) bool {
    return validators.validateMultipleOf(i64, value, divisor);
}

export fn validate_float_gt(value: f64, min: f64) bool {
    return validators.validateGt(f64, value, min);
}

export fn validate_float_finite(value: f64) bool {
    return validators.validateFinite(value);
}

// Additional number validators
export fn validate_int_negative(value: i64) bool {
    return validators.validateNegative(i64, value);
}

export fn validate_int_nonpositive(value: i64) bool {
    return validators.validateNonPositive(i64, value);
}

export fn validate_float_negative(value: f64) bool {
    return validators.validateNegative(f64, value);
}

export fn validate_float_nonpositive(value: f64) bool {
    return validators.validateNonPositive(f64, value);
}

export fn validate_float_gte(value: f64, min: f64) bool {
    return validators.validateGte(f64, value, min);
}

export fn validate_float_lt(value: f64, max: f64) bool {
    return validators.validateLt(f64, value, max);
}

export fn validate_float_lte(value: f64, max: f64) bool {
    return validators.validateLte(f64, value, max);
}

export fn validate_float_multiple_of(value: f64, divisor: f64) bool {
    return validators.validateMultipleOf(f64, value, divisor);
}

// ULTRA-FAST: Batch string length validation (no encoding needed!)
export fn validate_string_lengths_batch(
    count: u32,
    lengths_ptr: [*]const u32,
    min: u32,
    max: u32,
    results_ptr: [*]u8
) void {
    const lengths = lengths_ptr[0..count];
    const results = results_ptr[0..count];
    
    var i: usize = 0;
    while (i < count) : (i += 1) {
        results[i] = if (lengths[i] >= min and lengths[i] <= max) 1 else 0;
    }
}

// ULTRA-FAST: Batch number validation
export fn validate_numbers_batch(
    count: u32,
    numbers_ptr: [*]const f64,
    min: f64,
    max: f64,
    results_ptr: [*]u8
) void {
    const numbers = numbers_ptr[0..count];
    const results = results_ptr[0..count];
    
    var i: usize = 0;
    while (i < count) : (i += 1) {
        const n = numbers[i];
        results[i] = if (n >= min and n <= max) 1 else 0;
    }
}

// Batch validation - validates multiple items at once
// Returns a pointer to boolean array
export fn validate_batch(
    items_ptr: [*]const u8,
    items_len: usize,
    num_items: usize,
    validator_type: u8,
    _: i64,
    _: i64,
) ?[*]u8 {
    // Allocate result array
    const results = std.heap.wasm_allocator.alloc(u8, num_items) catch return null;
    
    // For now, simple implementation - can be optimized further
    var offset: usize = 0;
    for (0..num_items) |i| {
        // Read string length (4 bytes)
        if (offset + 4 > items_len) break;
        const str_len = @as(u32, @bitCast([4]u8{
            items_ptr[offset],
            items_ptr[offset + 1],
            items_ptr[offset + 2],
            items_ptr[offset + 3],
        }));
        offset += 4;
        
        if (offset + str_len > items_len) break;
        const str = items_ptr[offset..offset + str_len];
        offset += str_len;
        
        // Validate based on type
        results[i] = switch (validator_type) {
            0 => if (validators.validateEmail(str)) 1 else 0,
            1 => if (validators.validateUrl(str)) 1 else 0,
            2 => if (validators.validateUuid(str)) 1 else 0,
            else => 0,
        };
    }
    
    return results.ptr;
}

// Optimized batch validation - validates multiple fields across multiple items
// Format: [num_fields][field1_type][field1_param1][field1_param2]...[num_items][item_data...]
// Returns pointer to boolean array (one bool per item)
export fn validate_batch_optimized(
    spec_ptr: [*]const u8,
    spec_len: usize,
    items_ptr: [*]const u8,
    items_len: usize,
) ?[*]u8 {
    _ = spec_len;
    
    // Parse field specs
    var offset: usize = 0;
    const num_fields = spec_ptr[offset];
    offset += 1;
    
    // Allocate space for field specs
    const field_specs = std.heap.wasm_allocator.alloc(FieldSpec, num_fields) catch return null;
    defer std.heap.wasm_allocator.free(field_specs);
    
    // Parse each field spec
    for (0..num_fields) |i| {
        field_specs[i].validator_type = spec_ptr[offset];
        offset += 1;
        field_specs[i].param1 = @as(i32, @bitCast([4]u8{
            spec_ptr[offset],
            spec_ptr[offset + 1],
            spec_ptr[offset + 2],
            spec_ptr[offset + 3],
        }));
        offset += 4;
        field_specs[i].param2 = @as(i32, @bitCast([4]u8{
            spec_ptr[offset],
            spec_ptr[offset + 1],
            spec_ptr[offset + 2],
            spec_ptr[offset + 3],
        }));
        offset += 4;
    }
    
    // Parse item count
    const item_count = @as(u32, @bitCast([4]u8{
        items_ptr[0],
        items_ptr[1],
        items_ptr[2],
        items_ptr[3],
    }));
    
    // Allocate results
    const results = std.heap.wasm_allocator.alloc(u8, item_count) catch return null;
    
    // Initialize all to valid
    for (0..item_count) |i| {
        results[i] = 1;
    }
    
    // Validate each item
    var item_offset: usize = 4;
    for (0..item_count) |item_idx| {
        // For each field in this item
        for (field_specs) |spec| {
            // Read field data length
            if (item_offset + 4 > items_len) break;
            const field_len = @as(u32, @bitCast([4]u8{
                items_ptr[item_offset],
                items_ptr[item_offset + 1],
                items_ptr[item_offset + 2],
                items_ptr[item_offset + 3],
            }));
            item_offset += 4;
            
            if (item_offset + field_len > items_len) break;
            const field_data = items_ptr[item_offset..item_offset + field_len];
            item_offset += field_len;
            
            // Validate field (early exit on failure)
            const is_valid = validateField(field_data, spec);
            if (!is_valid) {
                results[item_idx] = 0;
                // Skip remaining fields for this item
                break;
            }
        }
    }
    
    return results.ptr;
}

const FieldSpec = struct {
    validator_type: u8,
    param1: i32,
    param2: i32,
};

inline fn validateField(data: []const u8, spec: FieldSpec) bool {
    return switch (spec.validator_type) {
        0 => validators.validateEmail(data),
        1 => validators.validateUrl(data),
        2 => validators.validateUuid(data),
        3 => validators.validateIpv4(data),
        4 => validators.validateIsoDate(data),
        5 => validators.validateIsoDatetime(data),
        6 => validators.validateBase64(data),
        7 => data.len >= @as(usize, @intCast(spec.param1)) and data.len <= @as(usize, @intCast(spec.param2)),
        8 => blk: { // positive number
            const num = std.fmt.parseInt(i64, data, 10) catch break :blk false;
            break :blk validators.validatePositive(i64, num);
        },
        else => false,
    };
}

// Memory allocation for JavaScript
export fn alloc(size: usize) ?[*]u8 {
    const slice = std.heap.wasm_allocator.alloc(u8, size) catch return null;
    return slice.ptr;
}

export fn dealloc(ptr: [*]u8, size: usize) void {
    const slice = ptr[0..size];
    std.heap.wasm_allocator.free(slice);
}

// 🚀 ULTRA-FAST EXPORTS: Maximum performance SIMD validations

/// Ultra-fast email validation using SIMD
export fn validate_email_ultra(ptr: [*]const u8, len: usize) bool {
    const email = ptr[0..len];
    return simd.validateEmailFast(email);
}

/// SIMD batch string length validation (8x parallelism)
export fn validate_string_lengths_simd(
    strings_ptr: [*]const [*]const u8,
    lengths_ptr: [*]const usize,
    count: usize,
    min: usize,
    max: usize,
    results_ptr: [*]bool
) void {
    const strings = strings_ptr[0..count];
    const lengths = lengths_ptr[0..count];
    const results = results_ptr[0..count];
    
    // Create string slices from pointers and lengths
    var string_slices = std.heap.wasm_allocator.alloc([]const u8, count) catch return;
    defer std.heap.wasm_allocator.free(string_slices);
    
    for (0..count) |i| {
        string_slices[i] = strings[i][0..lengths[i]];
    }
    
    simd.validateLengthBatch(string_slices, min, max, results);
}

/// MEGA-SIMD integer range validation (4x parallelism) - requires BigInt
export fn validate_int_range_simd(
    values_ptr: [*]const i64,
    count: usize,
    min: i64,
    max: i64,
    results_ptr: [*]u8
) void {
    const values = values_ptr[0..count];
    const results = results_ptr[0..count];
    simd.validateIntRangeBatch(values, min, max, results);
}

/// 🚀 FAST i32 SIMD batch validation - works with regular JS numbers!
export fn validate_int_range_simd_i32(
    values_ptr: [*]const i32,
    count: usize,
    min: i32,
    max: i32,
    results_ptr: [*]u8
) void {
    const values = values_ptr[0..count];
    const results = results_ptr[0..count];

    var i: usize = 0;
    // SIMD processing - 8 ints at once (i32 allows 8-wide SIMD)
    while (i + 8 <= count) : (i += 8) {
        const vals: @Vector(8, i32) = values[i..][0..8].*;
        const min_vec = @as(@Vector(8, i32), @splat(min));
        const max_vec = @as(@Vector(8, i32), @splat(max));

        const min_valid = vals >= min_vec;
        const max_valid = vals <= max_vec;

        // Combine results
        var mask: u8 = 0;
        inline for (0..8) |idx| {
            if (min_valid[idx] and max_valid[idx]) {
                mask |= (@as(u8, 1) << @intCast(idx));
            }
        }

        inline for (0..8) |j| {
            results[i + j] = @intFromBool(((mask >> @intCast(j)) & 1) == 1);
        }
    }

    // Handle remaining
    while (i < count) : (i += 1) {
        results[i] = @intFromBool(values[i] >= min and values[i] <= max);
    }
}

/// Zero-allocation email validation (returns error code)
export fn validate_email_zero_alloc(ptr: [*]const u8, len: usize) u8 {
    const email = ptr[0..len];
    const result = ultra.validateEmailUltra(email);
    return @as(u8, @intFromBool(result.is_valid)) | (result.error_code << 1);
}

/// Zero-allocation string length validation
export fn validate_string_length_zero_alloc(len: usize, min: usize, max: usize) u8 {
    // Direct length check (no function call needed)
    const too_short = @intFromBool(len < min);
    const too_long = @intFromBool(len > max);
    const error_code = too_short * ultra.ErrorCode.TOO_SHORT + too_long * ultra.ErrorCode.TOO_LONG;
    const is_valid = error_code == 0;
    
    return @as(u8, @intFromBool(is_valid)) | (@as(u8, @intCast(error_code)) << 1);
}

/// Zero-allocation integer range validation
export fn validate_int_range_zero_alloc(value: i64, min: i64, max: i64) u8 {
    const result = ultra.validateIntRangeUltra(value, min, max);
    return @as(u8, @intFromBool(result.is_valid)) | (result.error_code << 1);
}

/// 🌟 ULTIMATE SIMD USER BATCH VALIDATION
export fn validate_user_batch_ultra(
    names_ptr: [*]const [*:0]const u8,
    emails_ptr: [*]const [*:0]const u8,
    ages_ptr: [*]const i64,
    count: usize,
    name_min: usize,
    name_max: usize,
    age_min: i64,
    age_max: i64,
    results_ptr: [*]u8
) usize {
    const names = names_ptr[0..count];
    const emails = emails_ptr[0..count];
    const ages = ages_ptr[0..count];
    const results = results_ptr[0..count];
    
    return simd.validateUserBatchUltra(names, emails, ages, results, name_min, name_max, age_min, age_max);
}

/// 💥 TURBO MODE i32: Maximum speed with regular JS numbers (no BigInt!)
export fn validate_turbo_mode_i32(
    count: u32,
    string_lengths_ptr: [*]const u32,
    numbers_ptr: [*]const i32,
    min_len: u32,
    max_len: u32,
    min_num: i32,
    max_num: i32,
    results_ptr: [*]u8
) u32 {
    const string_lengths = string_lengths_ptr[0..count];
    const numbers = numbers_ptr[0..count];
    const results = results_ptr[0..count];

    var valid_count: u32 = 0;
    var i: usize = 0;

    // SIMD processing - 8 items at once (i32 allows full 8-wide SIMD!)
    while (i + 8 <= count) : (i += 8) {
        var str_lengths: @Vector(8, u32) = undefined;
        var nums: @Vector(8, i32) = undefined;

        inline for (0..8) |j| {
            str_lengths[j] = string_lengths[i + j];
            nums[j] = numbers[i + j];
        }

        const min_len_vec = @as(@Vector(8, u32), @splat(min_len));
        const max_len_vec = @as(@Vector(8, u32), @splat(max_len));
        const str_min_valid = str_lengths >= min_len_vec;
        const str_max_valid = str_lengths <= max_len_vec;

        const min_num_vec = @as(@Vector(8, i32), @splat(min_num));
        const max_num_vec = @as(@Vector(8, i32), @splat(max_num));
        const num_min_valid = nums >= min_num_vec;
        const num_max_valid = nums <= max_num_vec;

        // Combine all results
        inline for (0..8) |j| {
            const str_ok = str_min_valid[j] and str_max_valid[j];
            const num_ok = num_min_valid[j] and num_max_valid[j];
            const is_valid = str_ok and num_ok;
            results[i + j] = @intFromBool(is_valid);
            valid_count += @intFromBool(is_valid);
        }
    }

    // Handle remaining items
    while (i < count) : (i += 1) {
        const str_valid = string_lengths[i] >= min_len and string_lengths[i] <= max_len;
        const num_valid = numbers[i] >= min_num and numbers[i] <= max_num;
        const is_valid = str_valid and num_valid;
        results[i] = @intFromBool(is_valid);
        valid_count += @intFromBool(is_valid);
    }

    return valid_count;
}

// ============================================================================
// 🚀 SIMD V2: Next-gen validators using Muła algorithm & parallel char classes
// ============================================================================

/// SIMD substring search using Muła algorithm (60% faster than std.mem.indexOf)
export fn validate_contains_simd(
    str_ptr: [*]const u8,
    str_len: usize,
    substr_ptr: [*]const u8,
    substr_len: usize,
) bool {
    const str = str_ptr[0..str_len];
    const substr = substr_ptr[0..substr_len];
    return simd_string.simdContains(str, substr);
}

/// SIMD startsWith check (16-byte parallel comparison)
export fn validate_starts_with_simd(
    str_ptr: [*]const u8,
    str_len: usize,
    prefix_ptr: [*]const u8,
    prefix_len: usize,
) bool {
    const str = str_ptr[0..str_len];
    const prefix = prefix_ptr[0..prefix_len];
    return simd_string.simdStartsWith(str, prefix);
}

/// SIMD endsWith check
export fn validate_ends_with_simd(
    str_ptr: [*]const u8,
    str_len: usize,
    suffix_ptr: [*]const u8,
    suffix_len: usize,
) bool {
    const str = str_ptr[0..str_len];
    const suffix = suffix_ptr[0..suffix_len];
    return simd_string.simdEndsWith(str, suffix);
}

/// SIMD UUID validation (32-byte parallel hex check)
export fn validate_uuid_simd(ptr: [*]const u8, len: usize) bool {
    const uuid = ptr[0..len];
    return simd_string.simdValidateUuid(uuid);
}

/// SIMD email validation (parallel character class checking)
export fn validate_email_simd(ptr: [*]const u8, len: usize) bool {
    const email = ptr[0..len];
    return simd_string.simdValidateEmail(email);
}

/// SIMD URL validation (protocol prefix + domain check)
export fn validate_url_simd(ptr: [*]const u8, len: usize) bool {
    const url = ptr[0..len];
    return simd_string.simdValidateUrl(url);
}

/// SIMD IPv4 validation (parallel digit/dot class check)
export fn validate_ipv4_simd(ptr: [*]const u8, len: usize) bool {
    const ip = ptr[0..len];
    return simd_string.simdValidateIpv4(ip);
}

/// SIMD Base64 validation (parallel character class check)
export fn validate_base64_simd(ptr: [*]const u8, len: usize) bool {
    const data = ptr[0..len];
    return simd_string.simdValidateBase64(data);
}

/// SIMD ISO date validation (parallel digit check)
export fn validate_iso_date_simd(ptr: [*]const u8, len: usize) bool {
    const date = ptr[0..len];
    return simd_string.simdValidateIsoDate(date);
}

/// SIMD string indexOf (returns index or max_usize for not found)
export fn simd_index_of(
    str_ptr: [*]const u8,
    str_len: usize,
    needle_ptr: [*]const u8,
    needle_len: usize,
) usize {
    const str = str_ptr[0..str_len];
    const needle = needle_ptr[0..needle_len];
    return simd_string.simdIndexOf(str, needle) orelse std.math.maxInt(usize);
}

/// 💥 TURBO MODE: Maximum speed validation (no error tracking)
export fn validate_turbo_mode(
    count: u32,
    string_lengths_ptr: [*]const u32,
    numbers_ptr: [*]const i64,
    min_len: u32,
    max_len: u32,
    min_num: i64,
    max_num: i64,
    results_ptr: [*]u8
) u32 {
    const string_lengths = string_lengths_ptr[0..count];
    const numbers = numbers_ptr[0..count];
    const results = results_ptr[0..count];
    
    var valid_count: u32 = 0;
    var i: usize = 0;
    
    // SIMD processing - 8 items at once
    while (i + 8 <= count) : (i += 8) {
        // String length validation
        var str_lengths: @Vector(8, u32) = undefined;
        var nums: @Vector(8, i64) = undefined;
        
        inline for (0..8) |j| {
            str_lengths[j] = string_lengths[i + j];
            nums[j] = numbers[i + j];
        }
        
        const min_len_vec = @as(@Vector(8, u32), @splat(min_len));
        const max_len_vec = @as(@Vector(8, u32), @splat(max_len));
        const str_min_valid = str_lengths >= min_len_vec;
        const str_max_valid = str_lengths <= max_len_vec;
        
        const min_num_vec = @as(@Vector(8, i64), @splat(min_num));
        const max_num_vec = @as(@Vector(8, i64), @splat(max_num));
        const num_min_valid = nums >= min_num_vec;
        const num_max_valid = nums <= max_num_vec;
        
        // Process vector results with scalar logic
        var str_mask: u8 = 0;
        var num_mask: u8 = 0;
        inline for (0..8) |idx| {
            if (str_min_valid[idx] and str_max_valid[idx]) {
                str_mask |= (@as(u8, 1) << @intCast(idx));
            }
            if (num_min_valid[idx] and num_max_valid[idx]) {
                num_mask |= (@as(u8, 1) << @intCast(idx));
            }
        }
        
        inline for (0..8) |j| {
            const str_ok = ((str_mask >> @intCast(j)) & 1) == 1;
            const num_ok = ((num_mask >> @intCast(j)) & 1) == 1;
            const is_valid = str_ok and num_ok;
            results[i + j] = @intFromBool(is_valid);
            valid_count += @intFromBool(is_valid);
        }
    }
    
    // Handle remaining items
    while (i < count) : (i += 1) {
        const str_valid = string_lengths[i] >= min_len and string_lengths[i] <= max_len;
        const num_valid = numbers[i] >= min_num and numbers[i] <= max_num;
        const is_valid = str_valid and num_valid;
        results[i] = @intFromBool(is_valid);
        valid_count += @intFromBool(is_valid);
    }
    
    return valid_count;
}
