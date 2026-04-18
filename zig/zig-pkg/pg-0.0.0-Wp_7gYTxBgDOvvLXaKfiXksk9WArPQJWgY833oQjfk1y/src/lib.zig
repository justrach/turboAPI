// Exposed within this library
const std = @import("std");

pub const openssl = @cImport({
    @cInclude("openssl/ssl.h");
    @cInclude("openssl/err.h");
});

const build_config = @import("config");

pub const log = std.log.scoped(.pg);

pub const types = @import("types.zig");
pub const proto = @import("proto.zig");
pub const auth = @import("auth.zig");
pub const Conn = @import("conn.zig").Conn;
pub const Stmt = @import("stmt.zig").Stmt;
pub const Pool = @import("pool.zig").Pool;
pub const Stream = @import("stream.zig").Stream;
pub const metrics = @import("metrics.zig");
pub const has_openssl = build_config.openssl;
pub const SSLCtx = if (has_openssl) openssl.SSL_CTX else void;
pub const default_column_names = build_config.column_names;

const result = @import("result.zig");
pub const Row = result.Row;
pub const RowUnsafe = result.RowUnsafe;
pub const Result = result.Result;
pub const Iterator = result.Iterator;
pub const IteratorUnsafe = result.IteratorUnsafe;
pub const QueryRow = result.QueryRow;
pub const QueryRowUnsafe = result.QueryRowUnsafe;
pub const Mapper = result.Mapper;

const reader = @import("reader.zig");
pub const Reader = reader.Reader;
pub const Message = reader.Message;

pub const testing = @import("t.zig");

const root = @import("root");
const _assert = blk: {
    if (@hasDecl(root, "pg_assert")) {
        break :blk root.pg_assert;
    }
    switch (@import("builtin").mode) {
        .ReleaseFast, .ReleaseSmall => break :blk false,
        else => break :blk true,
    }
};

pub const _stderr_tls = blk: {
    if (@hasDecl(root, "pg_stderr_tls")) {
        break :blk root.pg_stderr_tls;
    }
    break :blk false;
};

pub fn assert(ok: bool) void {
    if (comptime _assert) {
        std.debug.assert(ok);
    }
}

pub fn verifyDecodeType(comptime fail_mode: FailMode, comptime T: type, comptime expected_oids: []const i32, actual: i32) !void {
    if (comptime fail_mode == .safe) {
        if (isExpectedId(expected_oids, actual)) {
            return;
        }
        return error.InvalidType;
    }

    if (comptime _assert == false) {
        return;
    }

    if (isExpectedId(expected_oids, actual)) {
        return;
    }

    log.warn("PostgreSQL value of type {s} cannot be read into a " ++ @typeName(T) ++ ". " ++
        "pg.zig has strict type checking when reading value.", .{types.oidToString(actual)});
    unreachable;
}

fn isExpectedId(comptime expected_oids: []const i32, actual: i32) bool {
    inline for (expected_oids) |expected_oid| {
        if (expected_oid == actual) {
            return true;
        }
    }
    return false;
}

pub fn verifyNotNull(comptime fail_mode: FailMode, comptime T: type, is_null: bool) !void {
    if (comptime fail_mode == .safe) {
        if (is_null == false) {
            return;
        }
        return error.UnexpectedNull;
    }

    if (comptime _assert == false) {
        return;
    }

    if (is_null == false) {
        return;
    }

    log.warn("PostgreSQL null column cannot be read into non-optional type (" ++ @typeName(T) ++ "). " ++
        "pg.zig has strict type checking when reading value.", .{});
    unreachable;
}

pub fn verifyColumnName(comptime fail_mode: FailMode, name: []const u8, valid: bool) !void {
    if (comptime fail_mode == .safe) {
        if (valid) {
            return;
        }
        return error.UnknownColumnName;
    }

    if (comptime _assert == false) {
        return;
    }

    if (valid) {
        return;
    }

    log.warn("Unknown column name '{s}'", .{name});
    unreachable;
}

pub const ParsedOpts = struct {
    opts: Pool.Opts,
    arena: std.heap.ArenaAllocator,

    pub fn deinit(self: *ParsedOpts) void {
        self.arena.deinit();
    }
};

pub fn parseOpts(uri: std.Uri, allocator: std.mem.Allocator) !ParsedOpts {
    if (!std.mem.eql(u8, uri.scheme, "postgresql") and !std.mem.eql(u8, uri.scheme, "postgres")) {
        return error.InvalidUriScheme;
    }

    var arena = std.heap.ArenaAllocator.init(allocator);
    errdefer arena.deinit();
    const aa = arena.allocator();

    var tls: Conn.Opts.TLS = .off;
    var tcp_user_timeout: ?u32 = null;
    if (uri.query) |qry| {
        const query_string = try qry.toRawMaybeAlloc(aa);
        var it = std.mem.splitScalar(u8, query_string, '&');
        while (it.next()) |param| {
            var it2 = std.mem.splitScalar(u8, param, '=');
            const key = it2.first();
            const val = it2.rest();
            if (std.mem.eql(u8, key, "tcp_user_timeout")) {
                tcp_user_timeout = try std.fmt.parseInt(u32, val, 10);
            } else if (std.mem.eql(u8, key, "sslmode")) {
                if (std.mem.eql(u8, val, "require")) {
                    tls = .require;
                } else if (std.mem.eql(u8, val, "verify-full")) {
                    tls = .{ .verify_full = null };
                } else if (std.mem.eql(u8, val, "disable") == false) {
                    return error.UnsupportedSSLModeValue;
                }
            } else {
                return error.UnsupportedConnectionParam;
            }
        }
    }

    const path = std.mem.trimLeft(u8, try uri.path.toRawMaybeAlloc(aa), "/");
    const host = if (uri.host) |host| try host.toRawMaybeAlloc(aa) else null;
    const username = if (uri.user) |user| try user.toRawMaybeAlloc(aa) else "postgres";
    const password = if (uri.password) |password| try password.toRawMaybeAlloc(aa) else null;

    // don't use `aa` after this point, we're about to copy `arena` and any usage
    // of `aa` will leak

    return .{ .arena = arena, .opts = .{
        .size = 0,
        .timeout = 0,
        .auth = .{
            .username = username,
            .password = password,
            .database = if (path.len == 0) null else path,
            .timeout = tcp_user_timeout orelse 10_000,
        },
        .connect = .{
            .tls = tls,
            .port = uri.port orelse null,
            .host = host,
        },
    } };
}

pub fn initializeSSLContext(config: Conn.Opts.TLS) !*SSLCtx {
    // OpenSSL documentation says these are implicitly called, and only need to
    // be called if you're doing something special

    // if (openssl.OPENSSL_init_ssl(openssl.OPENSSL_INIT_LOAD_SSL_STRINGS | openssl.OPENSSL_INIT_LOAD_CRYPTO_STRINGS, null) != 1) {
    //     return error.OpenSSLInitSslFailed;
    // }

    // if (openssl.OPENSSL_init_crypto(openssl.OPENSSL_INIT_ADD_ALL_CIPHERS | openssl.OPENSSL_INIT_ADD_ALL_DIGESTS | openssl.OPENSSL_INIT_LOAD_CRYPTO_STRINGS, null) != 1) {
    //     return error.OpenSSLInitCryptoFailed;
    // }

    const ctx = openssl.SSL_CTX_new(openssl.TLS_client_method()) orelse {
        return error.SSLContextNew;
    };
    errdefer openssl.SSL_CTX_free(ctx);

    if (openssl.SSL_CTX_set_min_proto_version(ctx, openssl.TLS1_2_VERSION) != 1) {
        return error.SSLMinVersion;
    }

    _ = openssl.SSL_CTX_set_mode(ctx, openssl.SSL_MODE_AUTO_RETRY);

    switch (config) {
        .off, .require => {},
        .verify_full => |path_to_root| {
            if (path_to_root) |p| {
                var pathz: [std.fs.max_path_bytes + 1]u8 = undefined;
                @memcpy(pathz[0..p.len], p);
                pathz[p.len] = 0;
                if (openssl.SSL_CTX_load_verify_locations(ctx, pathz[0 .. p.len + 1].ptr, null) != 1) {
                    if (comptime _stderr_tls) {
                        printSSLError();
                    }
                    return error.SSLVerifyPaths;
                }
            } else {
                if (openssl.SSL_CTX_set_default_verify_paths(ctx) != 1) {
                    if (comptime _stderr_tls) {
                        printSSLError();
                    }
                    return error.SSLDefaultVerifyPaths;
                }
            }
            openssl.SSL_CTX_set_verify(ctx, openssl.SSL_VERIFY_PEER, null);
        },
    }

    return ctx;
}

pub fn freeSSLContext(ctx: ?*SSLCtx) void {
    if (comptime has_openssl == false) {
        return;
    }

    if (ctx) |c| {
        openssl.SSL_CTX_free(c);
    }
}

pub fn printSSLError() void {
    if (comptime has_openssl == false) {
        return;
    }

    const bio = openssl.BIO_new(openssl.BIO_s_mem());
    defer _ = openssl.BIO_free(bio);
    openssl.ERR_print_errors(bio);
    var buf: [*]u8 = undefined;
    const len: usize = @intCast(openssl.BIO_get_mem_data(bio, &buf));
    if (len > 0) {
        std.debug.print("{s}\n", .{buf[0..len]});
    }
}

pub const Binary = struct {
    data: []const u8,
};

const TestCase = struct {
    uri: []const u8,
    expected_opts: Pool.Opts,
};

pub const FailMode = enum {
    safe,
    unsafe,
};

pub const TypeError = error{
    InvalidType,
    UnexpectedNull,
    UnknownColumnName,
};

const valid_tcs: [2]TestCase = .{
    .{ .uri = "postgresql:///", .expected_opts = .{ .size = 0, .auth = .{ .username = "postgres" }, .connect = .{}, .timeout = 0 } },
    .{ .uri = "postgresql://user:pass@somehost:1234/somedb?tcp_user_timeout=5678", .expected_opts = .{ .size = 0, .auth = .{
        .username = "user",
        .password = "pass",
        .database = "somedb",
        .timeout = 5678,
    }, .connect = .{
        .host = "somehost",
        .port = 1234,
    }, .timeout = 0 } },
};

test "URI: parse valid" {
    const a = std.testing.allocator;
    for (valid_tcs) |tc| {
        var po = parseOpts(try std.Uri.parse(tc.uri), a) catch |e| {
            std.log.err("failed to parse URI {s}", .{tc.uri});
            return e;
        };
        defer po.deinit();
        try std.testing.expectEqualDeep(tc.expected_opts, po.opts);
    }
}

test "URI: invalid scheme" {
    try std.testing.expectError(error.InvalidUriScheme, parseOpts(try std.Uri.parse("foobar:///"), std.testing.allocator));
}

test "URI: invalid params" {
    try std.testing.expectError(error.UnsupportedConnectionParam, parseOpts(try std.Uri.parse("postgresql:///?bar=baz"), std.testing.allocator));
}
