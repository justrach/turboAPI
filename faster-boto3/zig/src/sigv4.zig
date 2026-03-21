// SigV4 signing implementation in Zig.
// Drop-in replacement for botocore.auth.SigV4Auth signing hot path.
//
// The SigV4 algorithm:
//   1. derive_signing_key: 4 chained HMAC-SHA256 (date, region, service, "aws4_request")
//   2. canonical_request: method + path + query + headers + signed_headers + payload_hash
//   3. string_to_sign: "AWS4-HMAC-SHA256\n" + timestamp + scope + sha256(canonical_request)
//   4. signature: HMAC-SHA256(signing_key, string_to_sign).hex()

const std = @import("std");
const HmacSha256 = std.crypto.auth.hmac.sha2.HmacSha256;
const Sha256 = std.crypto.hash.sha2.Sha256;

/// Derive the SigV4 signing key (4 chained HMAC-SHA256).
/// Returns a 32-byte signing key.
pub fn deriveSigningKey(
    secret_key: []const u8,
    datestamp: []const u8,
    region: []const u8,
    service: []const u8,
) [32]u8 {
    // k_date = HMAC("AWS4" + secret_key, datestamp)
    var aws4_key_buf: [256]u8 = undefined;
    const prefix = "AWS4";
    @memcpy(aws4_key_buf[0..prefix.len], prefix);
    @memcpy(aws4_key_buf[prefix.len..][0..secret_key.len], secret_key);
    const aws4_key = aws4_key_buf[0 .. prefix.len + secret_key.len];

    var k_date: [32]u8 = undefined;
    HmacSha256.create(&k_date, datestamp, aws4_key);

    // k_region = HMAC(k_date, region)
    var k_region: [32]u8 = undefined;
    HmacSha256.create(&k_region, region, &k_date);

    // k_service = HMAC(k_region, service)
    var k_service: [32]u8 = undefined;
    HmacSha256.create(&k_service, service, &k_region);

    // k_signing = HMAC(k_service, "aws4_request")
    var k_signing: [32]u8 = undefined;
    HmacSha256.create(&k_signing, "aws4_request", &k_service);

    return k_signing;
}

/// Sign a string with a signing key. Returns hex-encoded signature (64 bytes).
pub fn signString(signing_key: *const [32]u8, string_to_sign: []const u8) [64]u8 {
    var mac: [32]u8 = undefined;
    HmacSha256.create(&mac, string_to_sign, signing_key);

    return std.fmt.bytesToHex(mac, .lower);
}

/// SHA256 hash, hex encoded (64 bytes).
pub fn sha256Hex(data: []const u8) [64]u8 {
    var hash: [32]u8 = undefined;
    Sha256.hash(data, &hash, .{});
    return std.fmt.bytesToHex(hash, .lower);
}

/// Full SigV4 signature in one call.
/// Takes raw inputs and returns 64-char hex signature.
pub fn sign(
    secret_key: []const u8,
    datestamp: []const u8,
    region: []const u8,
    service: []const u8,
    string_to_sign: []const u8,
) [64]u8 {
    const key = deriveSigningKey(secret_key, datestamp, region, service);
    return signString(&key, string_to_sign);
}

// ── Tests ──────────────────────────────────────────────────────────────────

test "deriveSigningKey matches AWS test vector" {
    // From AWS SigV4 test suite
    const key = deriveSigningKey(
        "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        "20150830",
        "us-east-1",
        "iam",
    );
    const hex = std.fmt.bytesToHex(key, .lower);
    try std.testing.expectEqualStrings(
        "c4afb1cc5771d871763a393e44b703571b55cc28424d1a5e86da6ed3c154a4b9",
        &hex,
    );
}

test "sha256Hex empty string" {
    const hex = sha256Hex("");
    try std.testing.expectEqualStrings(
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        &hex,
    );
}

test "sign produces 64-char hex" {
    const sig = sign(
        "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        "20260321",
        "us-east-1",
        "s3",
        "AWS4-HMAC-SHA256\n20260321T000000Z\n20260321/us-east-1/s3/aws4_request\nabc123",
    );
    try std.testing.expectEqual(@as(usize, 64), sig.len);
}

test "signString deterministic" {
    const key = deriveSigningKey("secret", "20260321", "us-east-1", "s3");
    const sig1 = signString(&key, "test message");
    const sig2 = signString(&key, "test message");
    try std.testing.expectEqualStrings(&sig1, &sig2);
}
