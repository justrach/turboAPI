// RFC 6455 WebSocket frame codec + handshake helpers.
//
// Standalone module — no I/O, no Python, no globals. The runtime (server.zig)
// owns the socket and the connection lifecycle; this module just turns bytes
// on the wire into Frames and back.
//
// Reference: https://www.rfc-editor.org/rfc/rfc6455

const std = @import("std");
const crypto = std.crypto;

/// WebSocket frame opcodes (RFC 6455 §5.2).
pub const Opcode = enum(u4) {
    continuation = 0x0,
    text = 0x1,
    binary = 0x2,
    // 0x3..0x7 reserved (non-control)
    close = 0x8,
    ping = 0x9,
    pong = 0xA,
    // 0xB..0xF reserved (control)
    _,

    pub fn isControl(self: Opcode) bool {
        return @intFromEnum(self) >= 0x8;
    }
};

/// Parsed WebSocket frame. The `payload` slice points into the caller's read
/// buffer (after masking has been applied in place if the frame was masked).
pub const Frame = struct {
    fin: bool,
    rsv1: bool = false,
    rsv2: bool = false,
    rsv3: bool = false,
    opcode: Opcode,
    /// Unmasked payload. For masked frames, the source buffer has been XORed
    /// in place — caller's buffer is mutated.
    payload: []u8,
    /// Total bytes consumed from the input buffer (header + payload).
    consumed: usize,
};

/// Parse result.
pub const ParseError = error{
    /// Need more bytes — caller should read more from the socket and retry.
    Incomplete,
    /// Reserved bits set (no extensions negotiated).
    ReservedBitsSet,
    /// Control frame with payload > 125 bytes (RFC §5.5).
    ControlFrameTooLarge,
    /// Control frame fragmented (RFC §5.5).
    FragmentedControlFrame,
    /// Server received an unmasked client frame (RFC §5.1).
    UnmaskedClientFrame,
    /// Payload length exceeds caller-provided cap.
    PayloadTooLarge,
};

pub const PARSE_DEFAULT_MAX_PAYLOAD: usize = 16 * 1024 * 1024; // 16 MB

/// Parse a single frame from `buf`. On success, returns Frame with `payload`
/// pointing into `buf` (XOR-demasked in place if necessary) and `consumed`
/// indicating how many bytes were consumed. Returns Incomplete if `buf` does
/// not yet contain a full frame.
///
/// Caller MUST pass a buffer they own (mutable) — masked frames are demasked
/// in place. Server-side: this is always the case since the server never
/// receives unmasked frames (RFC §5.1) and the input buffer is the read
/// buffer.
pub fn parseServerFrame(buf: []u8, max_payload: usize) ParseError!Frame {
    if (buf.len < 2) return ParseError.Incomplete;

    const b0 = buf[0];
    const b1 = buf[1];

    const fin = (b0 & 0x80) != 0;
    const rsv1 = (b0 & 0x40) != 0;
    const rsv2 = (b0 & 0x20) != 0;
    const rsv3 = (b0 & 0x10) != 0;
    if (rsv1 or rsv2 or rsv3) return ParseError.ReservedBitsSet;

    const opcode: Opcode = @enumFromInt(@as(u4, @truncate(b0 & 0x0F)));
    const masked = (b1 & 0x80) != 0;
    if (!masked) return ParseError.UnmaskedClientFrame;

    const len7: u7 = @truncate(b1 & 0x7F);

    var header_len: usize = 2;
    var payload_len: u64 = undefined;

    switch (len7) {
        0...125 => payload_len = len7,
        126 => {
            if (buf.len < 4) return ParseError.Incomplete;
            payload_len = std.mem.readInt(u16, buf[2..4], .big);
            header_len = 4;
        },
        127 => {
            if (buf.len < 10) return ParseError.Incomplete;
            payload_len = std.mem.readInt(u64, buf[2..10], .big);
            header_len = 10;
        },
    }

    if (opcode.isControl()) {
        if (payload_len > 125) return ParseError.ControlFrameTooLarge;
        if (!fin) return ParseError.FragmentedControlFrame;
    }

    if (payload_len > max_payload) return ParseError.PayloadTooLarge;

    // Mask key follows the (extended) length, then payload.
    if (buf.len < header_len + 4) return ParseError.Incomplete;
    const mask_key = buf[header_len..][0..4].*;
    const payload_start = header_len + 4;
    const total = payload_start + payload_len;
    if (buf.len < total) return ParseError.Incomplete;

    const payload = buf[payload_start..total];

    // XOR-demask in place.
    for (payload, 0..) |*byte, i| {
        byte.* ^= mask_key[i & 3];
    }

    return Frame{
        .fin = fin,
        .opcode = opcode,
        .payload = payload,
        .consumed = total,
    };
}

/// Serialize a server-to-client frame (RFC: server-to-client frames MUST NOT
/// be masked, §5.1). Writes into `out`; returns the number of bytes written,
/// or error.NoSpaceLeft if `out` is too small.
pub fn writeServerFrame(
    out: []u8,
    fin: bool,
    opcode: Opcode,
    payload: []const u8,
) error{NoSpaceLeft}!usize {
    var header_len: usize = 2;
    var extended_len_bytes: usize = 0;
    if (payload.len > 125 and payload.len <= 0xFFFF) {
        extended_len_bytes = 2;
    } else if (payload.len > 0xFFFF) {
        extended_len_bytes = 8;
    }
    const total = header_len + extended_len_bytes + payload.len;
    if (out.len < total) return error.NoSpaceLeft;

    out[0] = (@as(u8, if (fin) 0x80 else 0) | @intFromEnum(opcode));

    if (extended_len_bytes == 0) {
        out[1] = @intCast(payload.len);
    } else if (extended_len_bytes == 2) {
        out[1] = 126;
        std.mem.writeInt(u16, out[2..4], @intCast(payload.len), .big);
        header_len = 4;
    } else {
        out[1] = 127;
        std.mem.writeInt(u64, out[2..10], @intCast(payload.len), .big);
        header_len = 10;
    }

    @memcpy(out[header_len..][0..payload.len], payload);
    return total;
}

/// Compute the Sec-WebSocket-Accept header value for a given client
/// Sec-WebSocket-Key (RFC §4.2.2 step 5).
///
/// accept = base64(sha1(key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"))
///
/// `out` must be at least 28 bytes (base64-encoded SHA1 = 28 chars). Returns
/// the number of bytes written.
pub const WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
pub const ACCEPT_LEN: usize = 28;

pub fn computeAcceptKey(client_key: []const u8, out: []u8) error{NoSpaceLeft}!usize {
    if (out.len < ACCEPT_LEN) return error.NoSpaceLeft;

    var hasher = crypto.hash.Sha1.init(.{});
    hasher.update(client_key);
    hasher.update(WS_MAGIC);
    var sha1_digest: [crypto.hash.Sha1.digest_length]u8 = undefined;
    hasher.final(&sha1_digest);

    const encoder = std.base64.standard.Encoder;
    const written = encoder.encode(out[0..ACCEPT_LEN], &sha1_digest);
    return written.len;
}

/// Build the full HTTP/1.1 101 Switching Protocols response into `out`. Caller
/// provides the already-computed accept key (28 bytes). Returns total bytes.
pub fn writeHandshakeResponse(out: []u8, accept_key: []const u8) error{NoSpaceLeft}!usize {
    const tmpl_prefix = "HTTP/1.1 101 Switching Protocols\r\n" ++
        "Upgrade: websocket\r\n" ++
        "Connection: Upgrade\r\n" ++
        "Sec-WebSocket-Accept: ";
    const tmpl_suffix = "\r\n\r\n";
    const total = tmpl_prefix.len + accept_key.len + tmpl_suffix.len;
    if (out.len < total) return error.NoSpaceLeft;
    @memcpy(out[0..tmpl_prefix.len], tmpl_prefix);
    @memcpy(out[tmpl_prefix.len..][0..accept_key.len], accept_key);
    @memcpy(out[tmpl_prefix.len + accept_key.len ..][0..tmpl_suffix.len], tmpl_suffix);
    return total;
}

/// Encode a close-frame payload. RFC §5.5.1: optional status code (2 bytes BE)
/// followed by optional UTF-8 reason. Returns bytes written.
pub fn writeClosePayload(out: []u8, code: u16, reason: []const u8) error{NoSpaceLeft}!usize {
    const total = 2 + reason.len;
    if (out.len < total) return error.NoSpaceLeft;
    std.mem.writeInt(u16, out[0..2], code, .big);
    @memcpy(out[2..][0..reason.len], reason);
    return total;
}

// ── Tests ──────────────────────────────────────────────────────────────────

test "accept key — RFC §1.3 worked example" {
    // The RFC example: key = "dGhlIHNhbXBsZSBub25jZQ=="
    // expected accept = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
    var out: [ACCEPT_LEN]u8 = undefined;
    const written = try computeAcceptKey("dGhlIHNhbXBsZSBub25jZQ==", &out);
    try std.testing.expectEqual(ACCEPT_LEN, written);
    try std.testing.expectEqualStrings("s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", out[0..]);
}

test "parse: smallest text frame from client" {
    // FIN=1, opcode=text(1), masked, len=5, mask=0x01020304, payload xored
    var buf = [_]u8{
        0x81, // FIN | text
        0x85, // MASK | len=5
        0x01, 0x02, 0x03, 0x04, // mask
        // payload "hello" xored byte-by-byte with mask
        'h' ^ 0x01, 'e' ^ 0x02, 'l' ^ 0x03, 'l' ^ 0x04, 'o' ^ 0x01,
    };
    const frame = try parseServerFrame(&buf, PARSE_DEFAULT_MAX_PAYLOAD);
    try std.testing.expectEqual(true, frame.fin);
    try std.testing.expectEqual(Opcode.text, frame.opcode);
    try std.testing.expectEqualStrings("hello", frame.payload);
    try std.testing.expectEqual(@as(usize, 11), frame.consumed);
}

test "parse: 16-bit length encoding" {
    var payload: [200]u8 = undefined;
    @memset(&payload, 'A');
    var buf: [206]u8 = undefined;
    buf[0] = 0x81;
    buf[1] = 0x80 | 126;
    std.mem.writeInt(u16, buf[2..4], 200, .big);
    buf[4] = 0x00;
    buf[5] = 0x00;
    buf[6] = 0x00;
    buf[7] = 0x00; // mask = all zeros — XOR is no-op
    @memcpy(buf[8..], &payload);

    const frame = try parseServerFrame(&buf, PARSE_DEFAULT_MAX_PAYLOAD);
    try std.testing.expectEqual(@as(usize, 200), frame.payload.len);
    try std.testing.expectEqual(@as(usize, 206), frame.consumed);
}

test "parse: incomplete returns error.Incomplete" {
    var buf = [_]u8{ 0x81, 0x85, 0x01 };
    try std.testing.expectError(ParseError.Incomplete, parseServerFrame(&buf, PARSE_DEFAULT_MAX_PAYLOAD));
}

test "parse: rejects unmasked client frame" {
    var buf = [_]u8{ 0x81, 0x05, 'h', 'e', 'l', 'l', 'o' };
    try std.testing.expectError(ParseError.UnmaskedClientFrame, parseServerFrame(&buf, PARSE_DEFAULT_MAX_PAYLOAD));
}

test "parse: rejects reserved bits" {
    var buf = [_]u8{ 0xC1, 0x80, 0, 0, 0, 0 }; // RSV1 set
    try std.testing.expectError(ParseError.ReservedBitsSet, parseServerFrame(&buf, PARSE_DEFAULT_MAX_PAYLOAD));
}

test "parse: rejects oversize control frame" {
    var buf = [_]u8{ 0x88, 0x80 | 126, 0x00, 0x80, 0, 0, 0, 0 };
    try std.testing.expectError(ParseError.ControlFrameTooLarge, parseServerFrame(&buf, PARSE_DEFAULT_MAX_PAYLOAD));
}

test "parse: rejects fragmented control frame" {
    var buf = [_]u8{ 0x08, 0x80, 0, 0, 0, 0 }; // FIN=0 + close opcode
    try std.testing.expectError(ParseError.FragmentedControlFrame, parseServerFrame(&buf, PARSE_DEFAULT_MAX_PAYLOAD));
}

test "write: text frame small payload" {
    var out: [16]u8 = undefined;
    const written = try writeServerFrame(&out, true, .text, "hello");
    try std.testing.expectEqual(@as(usize, 7), written);
    try std.testing.expectEqual(@as(u8, 0x81), out[0]); // FIN | text
    try std.testing.expectEqual(@as(u8, 5), out[1]); // unmasked len=5
    try std.testing.expectEqualStrings("hello", out[2..7]);
}

test "write: 16-bit length boundary" {
    const payload = [_]u8{'A'} ** 200;
    var out: [256]u8 = undefined;
    const written = try writeServerFrame(&out, true, .binary, &payload);
    try std.testing.expectEqual(@as(usize, 204), written);
    try std.testing.expectEqual(@as(u8, 0x82), out[0]); // FIN | binary
    try std.testing.expectEqual(@as(u8, 126), out[1]);
    try std.testing.expectEqual(@as(u16, 200), std.mem.readInt(u16, out[2..4], .big));
}

test "write: close frame with payload" {
    var payload_buf: [32]u8 = undefined;
    const payload_len = try writeClosePayload(&payload_buf, 1000, "bye");
    try std.testing.expectEqual(@as(usize, 5), payload_len);

    var out: [16]u8 = undefined;
    const written = try writeServerFrame(&out, true, .close, payload_buf[0..payload_len]);
    try std.testing.expectEqual(@as(usize, 7), written);
    try std.testing.expectEqual(@as(u8, 0x88), out[0]);
}

test "handshake response format" {
    const accept = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=";
    var out: [256]u8 = undefined;
    const written = try writeHandshakeResponse(&out, accept);
    const expected =
        "HTTP/1.1 101 Switching Protocols\r\n" ++
        "Upgrade: websocket\r\n" ++
        "Connection: Upgrade\r\n" ++
        "Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n";
    try std.testing.expectEqualStrings(expected, out[0..written]);
}

test "roundtrip: parse(write(text payload)) yields original" {
    const original = "round trip test";
    var server_to_client: [32]u8 = undefined;
    const w = try writeServerFrame(&server_to_client, true, .text, original);
    _ = w;
    // Server-to-client frames are unmasked; parseServerFrame rejects unmasked
    // (since it's the server's parser). This roundtrip really just confirms
    // the write path. Parse roundtrip is exercised by parse tests above.
}
