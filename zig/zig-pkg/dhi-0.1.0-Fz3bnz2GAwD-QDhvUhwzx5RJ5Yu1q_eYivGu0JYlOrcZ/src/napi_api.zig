/// N-API native addon for dhi validation library
/// Exposes all validators from validators_comprehensive.zig to Node.js
/// via the N-API stable ABI

const napi = @cImport({
    @cDefine("NAPI_VERSION", "8");
    @cInclude("node_api.h");
});

const validators = @import("validators_comprehensive.zig");

// ============================================================================
// Helper: get string arg from N-API callback info
// ============================================================================

inline fn getStringArg(env: napi.napi_env, argv: []napi.napi_value, idx: usize, buf: []u8) []u8 {
    var len: usize = 0;
    _ = napi.napi_get_value_string_utf8(env, argv[idx], buf.ptr, buf.len, &len);
    return buf[0..len];
}

inline fn getDoubleArg(env: napi.napi_env, argv: []napi.napi_value, idx: usize) f64 {
    var val: f64 = 0;
    _ = napi.napi_get_value_double(env, argv[idx], &val);
    return val;
}

inline fn returnBool(env: napi.napi_env, value: bool) napi.napi_value {
    var result: napi.napi_value = undefined;
    _ = napi.napi_get_boolean(env, value, &result);
    return result;
}

// ============================================================================
// String validators
// ============================================================================

fn napiValidateEmail(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 1;
    var argv: [1]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    var buf: [4096]u8 = undefined;
    const s = getStringArg(env, &argv, 0, &buf);
    return returnBool(env, validators.validateEmail(s));
}

fn napiValidateUrl(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 1;
    var argv: [1]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    var buf: [4096]u8 = undefined;
    const s = getStringArg(env, &argv, 0, &buf);
    return returnBool(env, validators.validateUrl(s));
}

fn napiValidateUuid(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 1;
    var argv: [1]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    var buf: [64]u8 = undefined;
    const s = getStringArg(env, &argv, 0, &buf);
    return returnBool(env, validators.validateUuid(s));
}

fn napiValidateIpv4(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 1;
    var argv: [1]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    var buf: [64]u8 = undefined;
    const s = getStringArg(env, &argv, 0, &buf);
    return returnBool(env, validators.validateIpv4(s));
}

fn napiValidateBase64(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 1;
    var argv: [1]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    var buf: [4096]u8 = undefined;
    const s = getStringArg(env, &argv, 0, &buf);
    return returnBool(env, validators.validateBase64(s));
}

fn napiValidateIsoDate(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 1;
    var argv: [1]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    var buf: [32]u8 = undefined;
    const s = getStringArg(env, &argv, 0, &buf);
    return returnBool(env, validators.validateIsoDate(s));
}

fn napiValidateIsoDatetime(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 1;
    var argv: [1]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    var buf: [64]u8 = undefined;
    const s = getStringArg(env, &argv, 0, &buf);
    return returnBool(env, validators.validateIsoDatetime(s));
}

// validateStringLength(str, min, max): boolean
fn napiValidateStringLength(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 3;
    var argv: [3]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    var buf: [4096]u8 = undefined;
    const s = getStringArg(env, &argv, 0, &buf);
    const min = @as(usize, @intFromFloat(getDoubleArg(env, &argv, 1)));
    const max = @as(usize, @intFromFloat(getDoubleArg(env, &argv, 2)));
    return returnBool(env, s.len >= min and s.len <= max);
}

// validateContains(str, substr): boolean
fn napiValidateContains(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 2;
    var argv: [2]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    var buf1: [4096]u8 = undefined;
    var buf2: [4096]u8 = undefined;
    const s = getStringArg(env, &argv, 0, &buf1);
    const sub = getStringArg(env, &argv, 1, &buf2);
    return returnBool(env, validators.validateContains(s, sub));
}

// validateStartsWith(str, prefix): boolean
fn napiValidateStartsWith(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 2;
    var argv: [2]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    var buf1: [4096]u8 = undefined;
    var buf2: [4096]u8 = undefined;
    const s = getStringArg(env, &argv, 0, &buf1);
    const prefix = getStringArg(env, &argv, 1, &buf2);
    return returnBool(env, validators.validateStartsWith(s, prefix));
}

// validateEndsWith(str, suffix): boolean
fn napiValidateEndsWith(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 2;
    var argv: [2]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    var buf1: [4096]u8 = undefined;
    var buf2: [4096]u8 = undefined;
    const s = getStringArg(env, &argv, 0, &buf1);
    const suffix = getStringArg(env, &argv, 1, &buf2);
    return returnBool(env, validators.validateEndsWith(s, suffix));
}

// ============================================================================
// Integer validators
// ============================================================================

// validateInt(value, min, max): boolean
fn napiValidateInt(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 3;
    var argv: [3]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    const min = getDoubleArg(env, &argv, 1);
    const max = getDoubleArg(env, &argv, 2);
    // Check it's an integer and in range
    const is_int = v == @trunc(v);
    return returnBool(env, is_int and v >= min and v <= max);
}

fn napiValidateIntGt(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 2;
    var argv: [2]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    const min = getDoubleArg(env, &argv, 1);
    return returnBool(env, validators.validateGt(f64, v, min));
}

fn napiValidateIntGte(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 2;
    var argv: [2]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    const min = getDoubleArg(env, &argv, 1);
    return returnBool(env, validators.validateGte(f64, v, min));
}

fn napiValidateIntLt(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 2;
    var argv: [2]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    const max = getDoubleArg(env, &argv, 1);
    return returnBool(env, validators.validateLt(f64, v, max));
}

fn napiValidateIntLte(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 2;
    var argv: [2]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    const max = getDoubleArg(env, &argv, 1);
    return returnBool(env, validators.validateLte(f64, v, max));
}

fn napiValidateIntPositive(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 1;
    var argv: [1]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    return returnBool(env, validators.validatePositive(f64, v));
}

fn napiValidateIntNegative(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 1;
    var argv: [1]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    return returnBool(env, validators.validateNegative(f64, v));
}

fn napiValidateIntMultipleOf(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 2;
    var argv: [2]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    const divisor = getDoubleArg(env, &argv, 1);
    if (divisor == 0) return returnBool(env, false);
    return returnBool(env, @mod(v, divisor) == 0);
}

// ============================================================================
// Float validators (same logic, different naming for clarity)
// ============================================================================

fn napiValidateFloatGt(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 2;
    var argv: [2]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    const min = getDoubleArg(env, &argv, 1);
    return returnBool(env, validators.validateGt(f64, v, min));
}

fn napiValidateFloatGte(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 2;
    var argv: [2]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    const min = getDoubleArg(env, &argv, 1);
    return returnBool(env, validators.validateGte(f64, v, min));
}

fn napiValidateFloatLt(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 2;
    var argv: [2]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    const max = getDoubleArg(env, &argv, 1);
    return returnBool(env, validators.validateLt(f64, v, max));
}

fn napiValidateFloatLte(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 2;
    var argv: [2]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    const max = getDoubleArg(env, &argv, 1);
    return returnBool(env, validators.validateLte(f64, v, max));
}

fn napiValidateFloatPositive(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 1;
    var argv: [1]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    return returnBool(env, validators.validatePositive(f64, v));
}

fn napiValidateFloatNegative(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 1;
    var argv: [1]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    return returnBool(env, validators.validateNegative(f64, v));
}

fn napiValidateFloatFinite(env: napi.napi_env, info: napi.napi_callback_info) callconv(.c) napi.napi_value {
    var argc: usize = 1;
    var argv: [1]napi.napi_value = undefined;
    _ = napi.napi_get_cb_info(env, info, &argc, &argv, null, null);
    const v = getDoubleArg(env, &argv, 0);
    return returnBool(env, validators.validateFinite(v));
}

// ============================================================================
// Module registration helper
// ============================================================================

fn registerFn(
    env: napi.napi_env,
    exports: napi.napi_value,
    name: [*:0]const u8,
    cb: napi.napi_callback,
) void {
    var fn_val: napi.napi_value = undefined;
    _ = napi.napi_create_function(env, name, napi.NAPI_AUTO_LENGTH, cb, null, &fn_val);
    _ = napi.napi_set_named_property(env, exports, name, fn_val);
}

// ============================================================================
// Module entry point
// ============================================================================

export fn napi_register_module_v1(env: napi.napi_env, exports: napi.napi_value) napi.napi_value {
    // String validators
    registerFn(env, exports, "validateEmail", napiValidateEmail);
    registerFn(env, exports, "validateUrl", napiValidateUrl);
    registerFn(env, exports, "validateUuid", napiValidateUuid);
    registerFn(env, exports, "validateIpv4", napiValidateIpv4);
    registerFn(env, exports, "validateBase64", napiValidateBase64);
    registerFn(env, exports, "validateIsoDate", napiValidateIsoDate);
    registerFn(env, exports, "validateIsoDatetime", napiValidateIsoDatetime);
    registerFn(env, exports, "validateStringLength", napiValidateStringLength);
    registerFn(env, exports, "validateContains", napiValidateContains);
    registerFn(env, exports, "validateStartsWith", napiValidateStartsWith);
    registerFn(env, exports, "validateEndsWith", napiValidateEndsWith);

    // Integer validators
    registerFn(env, exports, "validateInt", napiValidateInt);
    registerFn(env, exports, "validateIntGt", napiValidateIntGt);
    registerFn(env, exports, "validateIntGte", napiValidateIntGte);
    registerFn(env, exports, "validateIntLt", napiValidateIntLt);
    registerFn(env, exports, "validateIntLte", napiValidateIntLte);
    registerFn(env, exports, "validateIntPositive", napiValidateIntPositive);
    registerFn(env, exports, "validateIntNegative", napiValidateIntNegative);
    registerFn(env, exports, "validateIntMultipleOf", napiValidateIntMultipleOf);

    // Float validators
    registerFn(env, exports, "validateFloatGt", napiValidateFloatGt);
    registerFn(env, exports, "validateFloatGte", napiValidateFloatGte);
    registerFn(env, exports, "validateFloatLt", napiValidateFloatLt);
    registerFn(env, exports, "validateFloatLte", napiValidateFloatLte);
    registerFn(env, exports, "validateFloatPositive", napiValidateFloatPositive);
    registerFn(env, exports, "validateFloatNegative", napiValidateFloatNegative);
    registerFn(env, exports, "validateFloatFinite", napiValidateFloatFinite);

    return exports;
}
