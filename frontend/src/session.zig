// session.zig — HMAC-based session tokens.

const std = @import("std");
const env = @import("env.zig").get;

const SessionHmac = std.crypto.auth.hmac.sha2.HmacSha256;
const SESSION_HMAC_HEX_LEN = SessionHmac.mac_length * 2;

/// Default session lifetime: 7 days.
pub const SESSION_DEFAULT_TTL: u32 = 7 * 24 * 60 * 60;

/// Parsed session extracted from a verified token.
pub const Session = struct {
    user_id: []const u8,
    expires_at: i64,
};

/// Sign a session token for `user_id` valid for `ttl_secs` seconds.
/// Reads the signing secret from `MULTICLAW_SESSION_SECRET`.
/// Returns an allocated string owned by `allocator`.
pub fn signSession(
    allocator: std.mem.Allocator,
    user_id: []const u8,
    ttl_secs: u32,
) ![]u8 {
    const secret = env("MULTICLAW_SESSION_SECRET") orelse return error.NoSessionSecret;
    const expires_at = std.time.timestamp() + @as(i64, ttl_secs);
    const msg = try std.fmt.allocPrint(allocator, "{s}.{d}", .{ user_id, expires_at });
    defer allocator.free(msg);

    var mac: [SessionHmac.mac_length]u8 = undefined;
    SessionHmac.create(&mac, msg, secret);
    const hex = std.fmt.bytesToHex(mac, .lower);

    return std.fmt.allocPrint(allocator, "{s}.{s}", .{ msg, &hex });
}

/// Verify a session token produced by `signSession`.
/// Returns null if the token is malformed, tampered with, or expired.
pub fn verifySession(token: []const u8) ?Session {
    const secret = env("MULTICLAW_SESSION_SECRET") orelse return null;

    if (token.len < SESSION_HMAC_HEX_LEN + 3) return null;

    const last_dot = std.mem.lastIndexOfScalar(u8, token, '.') orelse return null;
    const hmac_hex = token[last_dot + 1 ..];
    if (hmac_hex.len != SESSION_HMAC_HEX_LEN) return null;

    const prefix = token[0..last_dot];
    const mid_dot = std.mem.lastIndexOfScalar(u8, prefix, '.') orelse return null;
    const expires_str = prefix[mid_dot + 1 ..];
    const user_id = prefix[0..mid_dot];

    const expires_at = std.fmt.parseInt(i64, expires_str, 10) catch return null;
    if (std.time.timestamp() > expires_at) return null;

    var mac: [SessionHmac.mac_length]u8 = undefined;
    SessionHmac.create(&mac, prefix, secret);
    const expected = std.fmt.bytesToHex(mac, .lower);

    if (!std.crypto.timing_safe.eql(
        [SESSION_HMAC_HEX_LEN]u8,
        expected,
        hmac_hex[0..SESSION_HMAC_HEX_LEN].*,
    )) return null;

    return .{ .user_id = user_id, .expires_at = expires_at };
}

test "session: sign and verify roundtrip" {
    const env_mod = @import("env.zig");
    const k = "MULTICLAW_SESSION_SECRET";
    const v = "s3cr3t-test";
    env_mod.__mer_set_env(k.ptr, k.len, v.ptr, v.len);

    var buf: [1024]u8 = undefined;
    var fba = std.heap.FixedBufferAllocator.init(&buf);
    const token = try signSession(fba.allocator(), "alice", 3600);
    const session = verifySession(token) orelse return error.TestUnexpectedNull;
    try std.testing.expectEqualStrings("alice", session.user_id);
}

test "session: expired token returns null" {
    const env_mod = @import("env.zig");
    const k = "MULTICLAW_SESSION_SECRET";
    const v = "s3cr3t-test";
    env_mod.__mer_set_env(k.ptr, k.len, v.ptr, v.len);

    // Craft a token with expires_at=1 (Jan 1, 1970 — well in the past).
    const msg = "alice.1";
    var mac: [SessionHmac.mac_length]u8 = undefined;
    SessionHmac.create(&mac, msg, v);
    const hex = std.fmt.bytesToHex(mac, .lower);
    var token_buf: [256]u8 = undefined;
    const token = try std.fmt.bufPrint(&token_buf, "{s}.{s}", .{ msg, &hex });
    try std.testing.expect(verifySession(token) == null);
}

test "session: tampered HMAC returns null" {
    const env_mod = @import("env.zig");
    const k = "MULTICLAW_SESSION_SECRET";
    const v = "s3cr3t-test";
    env_mod.__mer_set_env(k.ptr, k.len, v.ptr, v.len);

    var buf: [1024]u8 = undefined;
    var fba = std.heap.FixedBufferAllocator.init(&buf);
    const token = try signSession(fba.allocator(), "alice", 3600);
    // Flip the last byte of the HMAC hex portion.
    var tampered: [256]u8 = undefined;
    @memcpy(tampered[0..token.len], token);
    tampered[token.len - 1] ^= 1;
    try std.testing.expect(verifySession(tampered[0..token.len]) == null);
}
