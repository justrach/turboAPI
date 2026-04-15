const std = @import("std");
const lib = @import("lib.zig");

const openssl = lib.openssl;

const posix = std.posix;

const Conn = lib.Conn;
const Allocator = std.mem.Allocator;

const DEFAULT_HOST = "127.0.0.1";

pub const Stream = if (lib.has_openssl) TLSStream else PlainStream;

const TLSStream = struct {
    valid: bool,
    ssl: ?*openssl.SSL,
    socket: posix.socket_t,

    pub fn connect(allocator: Allocator, opts: Conn.Opts, ctx_: ?*openssl.SSL_CTX) !Stream {
        const plain = try PlainStream.connect(allocator, opts, null);
        errdefer plain.close();

        const sock_fd = plain.socket;

        var ssl: ?*openssl.SSL = null;
        if (ctx_) |ctx| {
            // PostgreSQL TLS starts off as a plain connection which we upgrade
            try writeSocket(sock_fd, &.{ 0, 0, 0, 8, 4, 210, 22, 47 });
            var buf = [1]u8{0};
            _ = try readSocket(sock_fd, &buf);
            if (buf[0] != 'S') {
                return error.SSLNotSupportedByServer;
            }

            ssl = openssl.SSL_new(ctx) orelse return error.SSLNewFailed;
            errdefer openssl.SSL_free(ssl);

            if (opts.host) |host| {
                if (isHostName(host)) {
                    // don't send this for an ip address
                    var owned = false;
                    const h = opts._hostz orelse blk: {
                        owned = true;
                        break :blk try allocator.dupeZ(u8, host);
                    };

                    defer if (owned) {
                        allocator.free(h);
                    };

                    if (openssl.SSL_set_tlsext_host_name(ssl, h.ptr) != 1) {
                        return error.SSLHostNameFailed;
                    }
                }
                switch (opts.tls) {
                    .verify_full => openssl.SSL_set_verify(ssl, openssl.SSL_VERIFY_PEER, null),
                    else => {},
                }
            }

            if (openssl.SSL_set_fd(ssl, if (@import("builtin").os.tag == .windows) @intCast(@intFromPtr(sock_fd)) else sock_fd) != 1) {
                return error.SSLSetFdFailed;
            }

            {
                const ret = openssl.SSL_connect(ssl);
                if (ret != 1) {
                    const verification_code = openssl.SSL_get_verify_result(ssl);
                    if (comptime lib._stderr_tls) {
                        lib.printSSLError();
                    }
                    if (verification_code != openssl.X509_V_OK) {
                        if (comptime lib._stderr_tls) {
                            std.debug.print("ssl verification error: {s}\n", .{openssl.X509_verify_cert_error_string(verification_code)});
                        }
                        return error.SSLCertificationVerificationError;
                    }
                    return error.SSLConnectFailed;
                }
            }
        }

        return .{
            .ssl = ssl,
            .valid = true,
            .socket = sock_fd,
        };
    }

    pub fn close(self: *Stream) void {
        if (self.ssl) |ssl| {
            if (self.valid) {
                _ = openssl.SSL_shutdown(ssl);
                self.valid = false;
            }
            openssl.SSL_free(ssl);
        }
        _ = std.c.close(self.socket);
    }

    pub fn writeAll(self: *Stream, data: []const u8) !void {
        if (self.ssl) |ssl| {
            const result = openssl.SSL_write(ssl, data.ptr, @intCast(data.len));
            if (result <= 0) {
                self.valid = false;
                return error.SSLWriteFailed;
            }
            return;
        }
        return writeSocket(self.socket, data);
    }

    pub fn read(self: *Stream, buf: []u8) !usize {
        if (self.ssl) |ssl| {
            var read_len: usize = undefined;
            const result = openssl.SSL_read_ex(ssl, buf.ptr, @intCast(buf.len), &read_len);
            if (result <= 0) {
                self.valid = false;
                return error.SSLReadFailed;
            }
            return read_len;
        }

        return readSocket(self.socket, buf);
    }
};

const PlainStream = struct {
    socket: posix.socket_t,

    pub fn connect(_: Allocator, opts: Conn.Opts, _: anytype) !PlainStream {
        const sock_fd = blk: {
            const host = opts.host orelse DEFAULT_HOST;
            if (host.len > 0 and host[0] == '/') {
                if (comptime std.Io.net.has_unix_sockets == false or std.posix.AF == void) {
                    return error.UnixPathNotSupported;
                }
                break :blk try connectUnixSocket(host);
            }
            const port = opts.port orelse 5432;
            break :blk try tcpConnectToHost(host, port);
        };
        errdefer _ = std.c.close(sock_fd);

        return .{
            .socket = sock_fd,
        };
    }

    pub fn close(self: *const PlainStream) void {
        _ = std.c.close(self.socket);
    }

    pub fn writeAll(self: *const PlainStream, data: []const u8) !void {
        return writeSocket(self.socket, data);
    }

    pub fn read(self: *const PlainStream, buf: []u8) !usize {
        return readSocket(self.socket, buf);
    }
};

fn readSocket(fd: posix.socket_t, buf: []u8) !usize {
    const n = posix.read(fd, buf) catch return error.ConnectionResetByPeer;
    if (n == 0) return error.ConnectionResetByPeer;
    return n;
}

fn writeSocket(fd: posix.socket_t, data: []const u8) !void {
    var remaining = data;
    while (remaining.len > 0) {
        const n = write(fd, remaining.ptr, remaining.len);
        if (n <= 0) return error.BrokenPipe;
        remaining = remaining[@intCast(n)..];
    }
}

fn isHostName(host: []const u8) bool {
    if (std.mem.indexOfScalar(u8, host, ':') != null) {
        // IPv6
        return false;
    }
    return std.mem.indexOfNone(u8, host, "0123456789.") != null;
}

const builtin = @import("builtin");

extern "c" fn socket(domain: c_int, socket_type: c_int, protocol: c_int) c_int;
extern "c" fn connect(sockfd: c_int, addr: *const anyopaque, addrlen: u32) c_int;
extern "c" fn write(fd: c_int, buf: [*]const u8, nbytes: usize) isize;

const SockaddrUn = switch (builtin.os.tag) {
    .driverkit, .ios, .maccatalyst, .macos, .tvos, .visionos, .watchos => extern struct {
        len: u8 = 0,
        family: u8 = 1,
        path: [104]u8 = [_]u8{0} ** 104,
    },
    else => extern struct {
        family: u16 = 1,
        path: [108]u8 = [_]u8{0} ** 108,
    },
};

fn connectUnixSocket(path: []const u8) !posix.socket_t {
    const fd = socket(std.c.AF.UNIX, std.c.SOCK.STREAM, 0);
    if (fd < 0) return error.SystemResources;
    errdefer _ = std.c.close(fd);
    var addr: SockaddrUn = .{};
    if (path.len >= addr.path.len) return error.NameTooLong;
    if (comptime builtin.os.tag.isDarwin()) addr.len = @as(u8, @sizeOf(SockaddrUn));
    @memcpy(addr.path[0..path.len], path);
    if (connect(fd, &addr, @sizeOf(SockaddrUn)) < 0) return error.ConnectionRefused;
    return fd;
}

fn tcpConnectToHost(host: []const u8, port: u16) !posix.socket_t {
    var host_buf: [1025]u8 = std.mem.zeroes([1025]u8);
    if (host.len > 1024) return error.NameTooLong;
    @memcpy(host_buf[0..host.len], host);
    var port_buf: [8]u8 = undefined;
    const port_str = std.fmt.bufPrintZ(&port_buf, "{d}", .{port}) catch unreachable;
    const hints = std.c.addrinfo{
        .flags = .{},
        .family = std.c.AF.UNSPEC,
        .socktype = std.c.SOCK.STREAM,
        .protocol = 0,
        .addrlen = 0,
        .canonname = null,
        .addr = null,
        .next = null,
    };
    var result: ?*std.c.addrinfo = null;
    if (@intFromEnum(std.c.getaddrinfo(host_buf[0..host.len :0].ptr, port_str.ptr, &hints, &result)) != 0)
        return error.UnknownHostName;
    defer std.c.freeaddrinfo(result.?);
    var it = result;
    while (it) |info| : (it = info.next) {
        const addr = info.addr orelse continue;
        const fd = socket(@intCast(info.family), @intCast(info.socktype), @intCast(info.protocol));
        if (fd < 0) continue;
        if (connect(fd, addr, @intCast(info.addrlen)) >= 0) return fd;
        _ = std.c.close(fd);
    }
    return error.ConnectionRefused;
}
