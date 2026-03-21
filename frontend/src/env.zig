//! env.zig — cross-platform environment variable store.
//!
//! Native:  loadDotenv() parses `.env` at startup; get() checks the table
//!          then falls back to std.posix.getenv so child processes still work.
//!
//! wasm32:  worker.js calls __mer_set_env() for each Cloudflare secret binding
//!          before dispatching the first request; get() reads from the table.

const std = @import("std");
const builtin = @import("builtin");

// ── In-memory table ──────────────────────────────────────────────────────────

const MAX_ENTRIES = 64;

const Entry = struct { key: []const u8, val: []const u8 };

var table: [MAX_ENTRIES]Entry = undefined;
var table_len: usize = 0;

fn tableGet(name: []const u8) ?[]const u8 {
    for (table[0..table_len]) |e| {
        if (std.mem.eql(u8, e.key, name)) return e.val;
    }
    return null;
}

fn tableSet(key: []const u8, val: []const u8) void {
    for (table[0..table_len]) |*e| {
        if (std.mem.eql(u8, e.key, key)) {
            e.val = val;
            return;
        }
    }
    if (table_len < MAX_ENTRIES) {
        table[table_len] = .{ .key = key, .val = val };
        table_len += 1;
    }
}

// ── Public get ───────────────────────────────────────────────────────────────

/// Read an env var. Checks the in-memory table first, then std.posix.getenv on native.
pub fn get(name: []const u8) ?[]const u8 {
    if (tableGet(name)) |v| return v;
    if (builtin.target.cpu.arch != .wasm32) {
        return std.posix.getenv(name);
    }
    return null;
}

// ── Native: .env file loading ─────────────────────────────────────────────────

/// Parse `.env` from cwd and populate the in-memory table.
/// Call once at startup, before spawning request-handler threads.
/// Missing file is silently ignored — no error returned.
///
/// Supports:
///   KEY=value
///   export KEY=value
///   KEY="quoted value"
///   # comments
pub fn loadDotenv(allocator: std.mem.Allocator) void {
    if (builtin.target.cpu.arch == .wasm32) return;

    const file = std.fs.cwd().openFile(".env", .{}) catch return;
    defer file.close();

    // Intentionally leaked — table holds slices into this buffer for process lifetime.
    const content = file.readToEndAlloc(allocator, 64 * 1024) catch return;

    var lines = std.mem.splitScalar(u8, content, '\n');
    while (lines.next()) |raw| {
        const line = std.mem.trim(u8, raw, " \t\r");
        if (line.len == 0 or line[0] == '#') continue;
        var rest = line;
        if (std.mem.startsWith(u8, rest, "export ")) rest = rest["export ".len..];
        const eq = std.mem.indexOfScalar(u8, rest, '=') orelse continue;
        const key = std.mem.trim(u8, rest[0..eq], " \t");
        var val = std.mem.trim(u8, rest[eq + 1 ..], " \t");
        if (val.len >= 2) {
            const q = val[0];
            if ((q == '"' or q == '\'') and val[val.len - 1] == q) {
                val = val[1 .. val.len - 1];
            }
        }
        if (key.len == 0) continue;
        tableSet(key, val);
    }
}

// ── wasm32: Cloudflare Workers injection ──────────────────────────────────────

// Bump allocator for copying string data from WASM memory passed by worker.js.
// The alloc()/dealloc() calls in JS free the originals; we keep copies here.
var string_buf: [4096]u8 = undefined;
var string_pos: usize = 0;

fn bumpAlloc(n: usize) ?[]u8 {
    if (string_pos + n > string_buf.len) return null;
    const s = string_buf[string_pos..][0..n];
    string_pos += n;
    return s;
}

/// Inject a single environment variable from worker.js.
///
/// In worker.js, call once per Cloudflare secret binding before handling requests:
///
///   for (const [key, val] of Object.entries(env)) {
///     if (typeof val !== 'string') continue;
///     const kb = enc.encode(key), vb = enc.encode(val);
///     const kp = wasm.alloc(kb.length), vp = wasm.alloc(vb.length);
///     mem.set(kb, kp); mem.set(vb, vp);
///     wasm.__mer_set_env(kp, kb.length, vp, vb.length);
///     wasm.dealloc(kp, kb.length); wasm.dealloc(vp, vb.length);
///   }
pub export fn __mer_set_env(
    key_ptr: [*]const u8,
    key_len: usize,
    val_ptr: [*]const u8,
    val_len: usize,
) void {
    // Copy into string_buf so JS can dealloc the originals safely.
    const key_copy = bumpAlloc(key_len) orelse return;
    @memcpy(key_copy, key_ptr[0..key_len]);
    const val_copy = bumpAlloc(val_len) orelse return;
    @memcpy(val_copy, val_ptr[0..val_len]);
    tableSet(key_copy, val_copy);
}
