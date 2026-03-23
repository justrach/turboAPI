const std = @import("std");

const allocator = std.heap.c_allocator;
const HmacSha256 = std.crypto.auth.hmac.sha2.HmacSha256;
const Sha256 = std.crypto.hash.sha2.Sha256;

const Request = extern struct {
    method: [*c]const u8,
    method_len: usize,
    path: [*c]const u8,
    path_len: usize,
    query_string: [*c]const u8,
    query_len: usize,
    body: [*c]const u8,
    body_len: usize,
    header_names: [*c]const [*c]const u8,
    header_name_lens: [*c]const usize,
    header_values: [*c]const [*c]const u8,
    header_value_lens: [*c]const usize,
    header_count: usize,
    param_names: [*c]const [*c]const u8,
    param_name_lens: [*c]const usize,
    param_values: [*c]const [*c]const u8,
    param_value_lens: [*c]const usize,
    param_count: usize,
};

const Response = extern struct {
    status_code: u16,
    content_type: [*c]const u8,
    content_type_len: usize,
    body: [*c]const u8,
    body_len: usize,
};

const EnvConfig = struct {
    endpoint: []const u8,
    host: []const u8,
    region: []const u8,
    access_key: []const u8,
    secret_key: []const u8,
    bucket: []const u8,
};

var global_cfg = EnvConfig{
    .endpoint = "http://localhost:4566",
    .host = "localhost:4566",
    .region = "us-east-1",
    .access_key = "test",
    .secret_key = "testing",
    .bucket = "turbo-vs-fast",
};
var global_host_buf: [128]u8 = undefined;
var global_cfg_loaded = false;

threadlocal var tls_client: ?std.http.Client = null;
threadlocal var tls_signing_cache = SigningCache{};

const SigningCache = struct {
    valid: bool = false,
    date_stamp: [8]u8 = [_]u8{0} ** 8,
    signing_key: [32]u8 = [_]u8{0} ** 32,
};

const SignedHeaders = struct {
    headers: [4]std.http.Header,
    len: usize,
    amz_date: [16]u8,
    authorization: [256]u8,

    fn slice(self: *const SignedHeaders) []const std.http.Header {
        return self.headers[0..self.len];
    }
};

const FixedPath = struct {
    buf: [512]u8 = undefined,
    len: usize = 0,

    fn slice(self: *const FixedPath) []const u8 {
        return self.buf[0..self.len];
    }
};

const FixedJson = struct {
    buf: [128]u8 = undefined,
    len: usize = 0,

    fn slice(self: *const FixedJson) []const u8 {
        return self.buf[0..self.len];
    }
};

fn getEnv(name: [:0]const u8, fallback: []const u8) []const u8 {
    const value = std.c.getenv(name);
    if (value) |ptr| return std.mem.span(ptr);
    return fallback;
}

fn loadConfig() EnvConfig {
    if (!global_cfg_loaded) {
        global_cfg.endpoint = getEnv("BENCH_S3_ENDPOINT", global_cfg.endpoint);
        global_cfg.region = getEnv("AWS_REGION", global_cfg.region);
        global_cfg.access_key = getEnv("AWS_ACCESS_KEY_ID", global_cfg.access_key);
        global_cfg.secret_key = getEnv("AWS_SECRET_ACCESS_KEY", global_cfg.secret_key);
        global_cfg.bucket = getEnv("BENCH_S3_BUCKET", global_cfg.bucket);

        const uri = std.Uri.parse(global_cfg.endpoint) catch unreachable;
        const hostname = switch (uri.host orelse unreachable) {
            .raw => |h| h,
            .percent_encoded => |h| h,
        };
        global_cfg.host = if (uri.port) |port|
            std.fmt.bufPrint(&global_host_buf, "{s}:{d}", .{ hostname, port }) catch unreachable
        else
            hostname;
        global_cfg_loaded = true;
    }
    return global_cfg;
}

fn getParam(req: *const Request, wanted: []const u8) ?[]const u8 {
    var i: usize = 0;
    while (i < req.param_count) : (i += 1) {
        const name = req.param_names[i][0..req.param_name_lens[i]];
        if (std.mem.eql(u8, name, wanted)) {
            return req.param_values[i][0..req.param_value_lens[i]];
        }
    }
    return null;
}

fn utcNow() struct { amz_date: [16]u8, date_stamp: [8]u8 } {
    const ts = std.time.timestamp();
    const epoch: i64 = 86400;
    const days: i64 = @divFloor(ts, epoch);
    const secs_of_day: i64 = @mod(ts, epoch);

    const z = days + 719468;
    const era = @divFloor(z, 146097);
    const doe = z - era * 146097;
    const yoe = @divFloor(doe - @divFloor(doe, 1460) + @divFloor(doe, 36524) - @divFloor(doe, 146096), 365);
    const y = yoe + era * 400;
    const doy = doe - (365 * yoe + @divFloor(yoe, 4) - @divFloor(yoe, 100));
    const mp = @divFloor(5 * doy + 2, 153);
    const d = doy - @divFloor(153 * mp + 2, 5) + 1;
    const month_delta: i64 = if (mp < 10) 3 else -9;
    const m = mp + month_delta;
    const year_delta: i64 = if (m <= 2) 1 else 0;
    const year = y + year_delta;

    const hour: i64 = @divFloor(secs_of_day, 3600);
    const minute: i64 = @divFloor(@mod(secs_of_day, 3600), 60);
    const second: i64 = @mod(secs_of_day, 60);

    var amz_date: [16]u8 = undefined;
    var date_stamp: [8]u8 = undefined;
    write4(amz_date[0..4], year);
    write2(amz_date[4..6], m);
    write2(amz_date[6..8], d);
    amz_date[8] = 'T';
    write2(amz_date[9..11], hour);
    write2(amz_date[11..13], minute);
    write2(amz_date[13..15], second);
    amz_date[15] = 'Z';
    write4(date_stamp[0..4], year);
    write2(date_stamp[4..6], m);
    write2(date_stamp[6..8], d);
    return .{ .amz_date = amz_date, .date_stamp = date_stamp };
}

fn write2(dst: []u8, n: i64) void {
    dst[0] = @as(u8, @intCast('0' + @as(u8, @intCast(@mod(@divFloor(n, 10), 10)))));
    dst[1] = @as(u8, @intCast('0' + @as(u8, @intCast(@mod(n, 10)))));
}

fn write4(dst: []u8, n: i64) void {
    dst[0] = @as(u8, @intCast('0' + @as(u8, @intCast(@mod(@divFloor(n, 1000), 10)))));
    dst[1] = @as(u8, @intCast('0' + @as(u8, @intCast(@mod(@divFloor(n, 100), 10)))));
    dst[2] = @as(u8, @intCast('0' + @as(u8, @intCast(@mod(@divFloor(n, 10), 10)))));
    dst[3] = @as(u8, @intCast('0' + @as(u8, @intCast(@mod(n, 10)))));
}

fn sha256Hex(data: []const u8) [64]u8 {
    var hash: [32]u8 = undefined;
    Sha256.hash(data, &hash, .{});
    return std.fmt.bytesToHex(hash, .lower);
}

fn getClient() *std.http.Client {
    if (tls_client == null) {
        tls_client = std.http.Client{ .allocator = allocator };
    }
    return &tls_client.?;
}

fn deriveSigningKey(secret_key: []const u8, datestamp: []const u8, region: []const u8, service: []const u8) [32]u8 {
    var aws4_key_buf: [256]u8 = undefined;
    const prefix = "AWS4";
    @memcpy(aws4_key_buf[0..prefix.len], prefix);
    @memcpy(aws4_key_buf[prefix.len..][0..secret_key.len], secret_key);
    const aws4_key = aws4_key_buf[0 .. prefix.len + secret_key.len];

    var k_date: [32]u8 = undefined;
    HmacSha256.create(&k_date, datestamp, aws4_key);
    var k_region: [32]u8 = undefined;
    HmacSha256.create(&k_region, region, &k_date);
    var k_service: [32]u8 = undefined;
    HmacSha256.create(&k_service, service, &k_region);
    var k_signing: [32]u8 = undefined;
    HmacSha256.create(&k_signing, "aws4_request", &k_service);
    return k_signing;
}

fn getSigningKey(secret_key: []const u8, datestamp: []const u8, region: []const u8, service: []const u8) [32]u8 {
    if (
        tls_signing_cache.valid and
        std.mem.eql(u8, tls_signing_cache.date_stamp[0..], datestamp)
    ) {
        return tls_signing_cache.signing_key;
    }
    const key = deriveSigningKey(secret_key, datestamp, region, service);
    tls_signing_cache.valid = true;
    @memcpy(tls_signing_cache.date_stamp[0..], datestamp[0..8]);
    tls_signing_cache.signing_key = key;
    return key;
}

fn sign(secret_key: []const u8, datestamp: []const u8, region: []const u8, service: []const u8, string_to_sign: []const u8) [64]u8 {
    const key = getSigningKey(secret_key, datestamp, region, service);
    var mac: [32]u8 = undefined;
    HmacSha256.create(&mac, string_to_sign, &key);
    return std.fmt.bytesToHex(mac, .lower);
}

const HttpResp = struct {
    status: u16,
    headers_buf: []u8,
    body: []u8,

    fn deinit(self: *HttpResp) void {
        allocator.free(self.headers_buf);
        allocator.free(self.body);
    }
};

fn doRequest(method: std.http.Method, url: []const u8, headers: []const std.http.Header) !HttpResp {
    const client = getClient();

    const uri = try std.Uri.parse(url);
    var req = try client.request(method, uri, .{
        .redirect_behavior = @enumFromInt(5),
        .extra_headers = headers,
        .keep_alive = true,
    });
    defer req.deinit();

    try req.sendBodiless();
    var head_buf: [16384]u8 = undefined;
    var response = try req.receiveHead(&head_buf);

    var body = std.Io.Writer.Allocating.init(allocator);
    defer if (body.toOwnedSlice()) |slice| allocator.free(slice) else |_| {};
    if (method != .HEAD and response.head.status != .no_content and response.head.status != .not_modified) {
        var reader = response.request.reader.bodyReader(&.{}, response.head.transfer_encoding, response.head.content_length);
        _ = try reader.streamRemaining(&body.writer);
    } else {
        response.request.reader.state = .ready;
    }

    var hdr_out: std.ArrayList(u8) = .empty;
    defer hdr_out.deinit(allocator);
    var hdr_iter = response.head.iterateHeaders();
    while (hdr_iter.next()) |h| {
        try hdr_out.appendSlice(allocator, h.name);
        try hdr_out.appendSlice(allocator, ": ");
        try hdr_out.appendSlice(allocator, h.value);
        try hdr_out.appendSlice(allocator, "\r\n");
    }

    return .{
        .status = @intFromEnum(response.head.status),
        .headers_buf = try hdr_out.toOwnedSlice(allocator),
        .body = try body.toOwnedSlice(),
    };
}

fn buildSignedHeaders(
    cfg: EnvConfig,
    method: []const u8,
    canonical_uri: []const u8,
    canonical_query: []const u8,
    payload_hash: []const u8,
    extra_headers: []const [2][]const u8,
) !SignedHeaders {
    const now = utcNow();

    const signed_headers = if (extra_headers.len == 0)
        "host;x-amz-content-sha256;x-amz-date"
    else if (std.mem.eql(u8, extra_headers[0][0], "range"))
        "host;range;x-amz-content-sha256;x-amz-date"
    else if (std.mem.eql(u8, extra_headers[0][0], "x-amz-copy-source"))
        "host;x-amz-content-sha256;x-amz-copy-source;x-amz-date"
    else
        return error.UnsupportedHeaderSet;

    var canonical_headers_buf: [512]u8 = undefined;
    const canonical_headers = if (extra_headers.len == 0)
        try std.fmt.bufPrint(
            &canonical_headers_buf,
            "host:{s}\nx-amz-content-sha256:{s}\nx-amz-date:{s}\n",
            .{ cfg.host, payload_hash, &now.amz_date },
        )
    else
        try std.fmt.bufPrint(
            &canonical_headers_buf,
            "host:{s}\n{s}:{s}\nx-amz-content-sha256:{s}\nx-amz-date:{s}\n",
            .{ cfg.host, extra_headers[0][0], extra_headers[0][1], payload_hash, &now.amz_date },
        );

    var canonical_request_buf: [1024]u8 = undefined;
    const canonical_request = try std.fmt.bufPrint(
        &canonical_request_buf,
        "{s}\n{s}\n{s}\n{s}\n{s}\n{s}",
        .{ method, canonical_uri, canonical_query, canonical_headers, signed_headers, payload_hash },
    );

    const request_hash = sha256Hex(canonical_request);

    var scope_buf: [128]u8 = undefined;
    const scope = try std.fmt.bufPrint(&scope_buf, "{s}/{s}/s3/aws4_request", .{ &now.date_stamp, cfg.region });

    var string_to_sign_buf: [512]u8 = undefined;
    const string_to_sign = try std.fmt.bufPrint(
        &string_to_sign_buf,
        "AWS4-HMAC-SHA256\n{s}\n{s}\n{s}",
        .{ &now.amz_date, scope, &request_hash },
    );

    const signature = sign(cfg.secret_key, &now.date_stamp, cfg.region, "s3", string_to_sign);

    var out = SignedHeaders{
        .headers = undefined,
        .len = 0,
        .amz_date = now.amz_date,
        .authorization = undefined,
    };
    const auth = try std.fmt.bufPrint(
        &out.authorization,
        "AWS4-HMAC-SHA256 Credential={s}/{s}, SignedHeaders={s}, Signature={s}",
        .{ cfg.access_key, scope, signed_headers, &signature },
    );

    out.headers[out.len] = .{ .name = "x-amz-content-sha256", .value = payload_hash };
    out.len += 1;
    out.headers[out.len] = .{ .name = "x-amz-date", .value = out.amz_date[0..] };
    out.len += 1;
    if (extra_headers.len == 1) {
        out.headers[out.len] = .{ .name = extra_headers[0][0], .value = extra_headers[0][1] };
        out.len += 1;
    }
    out.headers[out.len] = .{ .name = "authorization", .value = auth };
    out.len += 1;
    return out;
}

fn jsonResponse(status: u16, body: []const u8) Response {
    const duped = allocator.dupe(u8, body) catch body;
    return .{
        .status_code = status,
        .content_type = "application/json",
        .content_type_len = 16,
        .body = duped.ptr,
        .body_len = duped.len,
    };
}

fn ensureOk(resp: *const HttpResp) ?Response {
    if (resp.status < 400) return null;
    const body = std.fmt.allocPrint(
        allocator,
        "{{\"error\":\"s3\",\"status\":{d}}}",
        .{resp.status},
    ) catch return jsonResponse(502, "{\"error\":\"s3\"}");
    return .{
        .status_code = if (resp.status > 599) 502 else resp.status,
        .content_type = "application/json",
        .content_type_len = 16,
        .body = body.ptr,
        .body_len = body.len,
    };
}

fn parseContentLength(headers: []const u8) ?usize {
    var lines = std.mem.splitSequence(u8, headers, "\r\n");
    while (lines.next()) |line| {
        if (std.ascii.startsWithIgnoreCase(line, "content-length: ")) {
            return std.fmt.parseInt(usize, line["content-length: ".len..], 10) catch null;
        }
    }
    return null;
}

fn parseContentRangeTotal(headers: []const u8) ?usize {
    var lines = std.mem.splitSequence(u8, headers, "\r\n");
    while (lines.next()) |line| {
        if (std.ascii.startsWithIgnoreCase(line, "content-range: ")) {
            const value = line["content-range: ".len..];
            const slash = std.mem.lastIndexOfScalar(u8, value, '/') orelse return null;
            return std.fmt.parseInt(usize, value[slash + 1 ..], 10) catch null;
        }
    }
    return null;
}

fn parseBatchCount(req: *const Request, fallback: usize) usize {
    const raw = getParam(req, "count") orelse return fallback;
    const parsed = std.fmt.parseInt(usize, raw, 10) catch return fallback;
    return @max(@as(usize, 1), @min(parsed, 64));
}

fn countTag(body: []const u8, needle: []const u8) usize {
    var count: usize = 0;
    var idx: usize = 0;
    while (std.mem.indexOfPos(u8, body, idx, needle)) |pos| {
        count += 1;
        idx = pos + needle.len;
    }
    return count;
}

fn makeUrl(cfg: EnvConfig, suffix: []const u8) ![]u8 {
    return std.fmt.allocPrint(allocator, "{s}{s}", .{ cfg.endpoint, suffix });
}

fn makeObjectPath(cfg: EnvConfig, key: []const u8) !FixedPath {
    var out = FixedPath{};
    out.len = (try std.fmt.bufPrint(&out.buf, "/{s}/{s}", .{ cfg.bucket, key })).len;
    return out;
}

fn makeObjectUrl(cfg: EnvConfig, path: []const u8) !FixedPath {
    var out = FixedPath{};
    out.len = (try std.fmt.bufPrint(&out.buf, "{s}{s}", .{ cfg.endpoint, path })).len;
    return out;
}

fn makeKeySizeJson(key: []const u8, size: usize) !FixedJson {
    var out = FixedJson{};
    out.len = (try std.fmt.bufPrint(&out.buf, "{{\"key\":\"{s}\",\"size\":{d}}}", .{ key, size })).len;
    return out;
}

export fn handle_s3_head(req: *const Request) callconv(.c) Response {
    const cfg = loadConfig();
    const key = getParam(req, "key") orelse return jsonResponse(400, "{\"error\":\"missing key\"}");
    const canonical_uri = makeObjectPath(cfg, key) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    const url = makeObjectUrl(cfg, canonical_uri.slice()) catch return jsonResponse(500, "{\"error\":\"oom\"}");

    const headers = buildSignedHeaders(cfg, "HEAD", canonical_uri.slice(), "", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", &.{}) catch return jsonResponse(500, "{\"error\":\"sign\"}");
    var resp = doRequest(.HEAD, url.slice(), headers.slice()) catch return jsonResponse(502, "{\"error\":\"s3\"}");
    defer resp.deinit();
    if (ensureOk(&resp)) |err_resp| return err_resp;
    const size = parseContentLength(resp.headers_buf) orelse resp.body.len;
    const body = makeKeySizeJson(key, size) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    return jsonResponse(200, body.slice());
}

export fn handle_s3_head_bucket(_: *const Request) callconv(.c) Response {
    const cfg = loadConfig();
    const canonical_uri = std.fmt.allocPrint(allocator, "/{s}", .{cfg.bucket}) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(canonical_uri);
    const url = makeUrl(cfg, canonical_uri) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(url);

    const headers = buildSignedHeaders(cfg, "HEAD", canonical_uri, "", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", &.{}) catch return jsonResponse(500, "{\"error\":\"sign\"}");
    var resp = doRequest(.HEAD, url, headers.slice()) catch return jsonResponse(502, "{\"error\":\"s3\"}");
    defer resp.deinit();
    if (ensureOk(&resp)) |err_resp| return err_resp;
    const body = std.fmt.allocPrint(allocator, "{{\"bucket\":\"{s}\",\"status\":{d}}}", .{ cfg.bucket, resp.status }) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    return .{ .status_code = 200, .content_type = "application/json", .content_type_len = 16, .body = body.ptr, .body_len = body.len };
}

export fn handle_s3_get(req: *const Request) callconv(.c) Response {
    const cfg = loadConfig();
    const key = getParam(req, "key") orelse return jsonResponse(400, "{\"error\":\"missing key\"}");
    const canonical_uri = makeObjectPath(cfg, key) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    const url = makeObjectUrl(cfg, canonical_uri.slice()) catch return jsonResponse(500, "{\"error\":\"oom\"}");

    const headers = buildSignedHeaders(cfg, "GET", canonical_uri.slice(), "", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", &.{}) catch return jsonResponse(500, "{\"error\":\"sign\"}");
    var resp = doRequest(.GET, url.slice(), headers.slice()) catch return jsonResponse(502, "{\"error\":\"s3\"}");
    defer resp.deinit();
    if (ensureOk(&resp)) |err_resp| return err_resp;
    const size = parseContentLength(resp.headers_buf) orelse resp.body.len;
    const body = makeKeySizeJson(key, size) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    return jsonResponse(200, body.slice());
}

export fn handle_s3_list(_: *const Request) callconv(.c) Response {
    const cfg = loadConfig();
    const canonical_uri = std.fmt.allocPrint(allocator, "/{s}", .{cfg.bucket}) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(canonical_uri);
    const canonical_query = "list-type=2&max-keys=20";
    const suffix = std.fmt.allocPrint(allocator, "{s}?{s}", .{ canonical_uri, canonical_query }) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(suffix);
    const url = makeUrl(cfg, suffix) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(url);

    const headers = buildSignedHeaders(cfg, "GET", canonical_uri, canonical_query, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", &.{}) catch return jsonResponse(500, "{\"error\":\"sign\"}");
    var resp = doRequest(.GET, url, headers.slice()) catch return jsonResponse(502, "{\"error\":\"s3\"}");
    defer resp.deinit();
    if (ensureOk(&resp)) |err_resp| return err_resp;
    const count = countTag(resp.body, "<Contents>");
    const body = std.fmt.allocPrint(allocator, "{{\"count\":{d}}}", .{count}) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    return .{ .status_code = 200, .content_type = "application/json", .content_type_len = 16, .body = body.ptr, .body_len = body.len };
}

export fn handle_s3_batch_head(req: *const Request) callconv(.c) Response {
    const cfg = loadConfig();
    const count = parseBatchCount(req, 8);
    var total_size: usize = 0;
    var index: usize = 0;

    while (index < count) : (index += 1) {
        const key = std.fmt.allocPrint(allocator, "batch/item-{d:0>3}", .{index}) catch return jsonResponse(500, "{\"error\":\"oom\"}");
        defer allocator.free(key);
        const canonical_uri = std.fmt.allocPrint(allocator, "/{s}/{s}", .{ cfg.bucket, key }) catch return jsonResponse(500, "{\"error\":\"oom\"}");
        defer allocator.free(canonical_uri);
        const url = makeUrl(cfg, canonical_uri) catch return jsonResponse(500, "{\"error\":\"oom\"}");
        defer allocator.free(url);

        const headers = buildSignedHeaders(cfg, "HEAD", canonical_uri, "", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", &.{}) catch return jsonResponse(500, "{\"error\":\"sign\"}");
        var resp = doRequest(.HEAD, url, headers.slice()) catch return jsonResponse(502, "{\"error\":\"s3\"}");
        defer resp.deinit();
        if (ensureOk(&resp)) |err_resp| return err_resp;
        total_size += parseContentLength(resp.headers_buf) orelse resp.body.len;
    }

    const body = std.fmt.allocPrint(allocator, "{{\"count\":{d},\"total_size\":{d}}}", .{ count, total_size }) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    return .{ .status_code = 200, .content_type = "application/json", .content_type_len = 16, .body = body.ptr, .body_len = body.len };
}

export fn handle_s3_list_buckets(_: *const Request) callconv(.c) Response {
    const cfg = loadConfig();
    const url = makeUrl(cfg, "/") catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(url);

    const headers = buildSignedHeaders(cfg, "GET", "/", "", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", &.{}) catch return jsonResponse(500, "{\"error\":\"sign\"}");
    var resp = doRequest(.GET, url, headers.slice()) catch return jsonResponse(502, "{\"error\":\"s3\"}");
    defer resp.deinit();
    if (ensureOk(&resp)) |err_resp| return err_resp;
    const count = countTag(resp.body, "<Bucket>");
    const body = std.fmt.allocPrint(allocator, "{{\"count\":{d}}}", .{count}) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    return .{ .status_code = 200, .content_type = "application/json", .content_type_len = 16, .body = body.ptr, .body_len = body.len };
}

export fn handle_s3_bucket_location(_: *const Request) callconv(.c) Response {
    const cfg = loadConfig();
    const canonical_uri = std.fmt.allocPrint(allocator, "/{s}", .{cfg.bucket}) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(canonical_uri);
    const suffix = std.fmt.allocPrint(allocator, "{s}?location", .{canonical_uri}) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(suffix);
    const url = makeUrl(cfg, suffix) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(url);

    const headers = buildSignedHeaders(cfg, "GET", canonical_uri, "location=", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", &.{}) catch return jsonResponse(500, "{\"error\":\"sign\"}");
    var resp = doRequest(.GET, url, headers.slice()) catch return jsonResponse(502, "{\"error\":\"s3\"}");
    defer resp.deinit();
    if (ensureOk(&resp)) |err_resp| return err_resp;
    const body = std.fmt.allocPrint(allocator, "{{\"bucket\":\"{s}\",\"status\":{d}}}", .{ cfg.bucket, resp.status }) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    return .{ .status_code = 200, .content_type = "application/json", .content_type_len = 16, .body = body.ptr, .body_len = body.len };
}

export fn handle_s3_delete(req: *const Request) callconv(.c) Response {
    const cfg = loadConfig();
    const key = getParam(req, "key") orelse return jsonResponse(400, "{\"error\":\"missing key\"}");
    const canonical_uri = std.fmt.allocPrint(allocator, "/{s}/{s}", .{ cfg.bucket, key }) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(canonical_uri);
    const url = makeUrl(cfg, canonical_uri) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(url);

    const headers = buildSignedHeaders(cfg, "DELETE", canonical_uri, "", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", &.{}) catch return jsonResponse(500, "{\"error\":\"sign\"}");
    var resp = doRequest(.DELETE, url, headers.slice()) catch return jsonResponse(502, "{\"error\":\"s3\"}");
    defer resp.deinit();
    if (ensureOk(&resp)) |err_resp| return err_resp;
    const body = std.fmt.allocPrint(allocator, "{{\"key\":\"{s}\",\"deleted\":true}}", .{key}) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    return .{ .status_code = 200, .content_type = "application/json", .content_type_len = 16, .body = body.ptr, .body_len = body.len };
}

export fn handle_s3_copy(req: *const Request) callconv(.c) Response {
    const cfg = loadConfig();
    const src = getParam(req, "src") orelse return jsonResponse(400, "{\"error\":\"missing src\"}");
    const dst = getParam(req, "dst") orelse return jsonResponse(400, "{\"error\":\"missing dst\"}");
    const canonical_uri = std.fmt.allocPrint(allocator, "/{s}/{s}", .{ cfg.bucket, dst }) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(canonical_uri);
    const url = makeUrl(cfg, canonical_uri) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(url);
    const copy_source = std.fmt.allocPrint(allocator, "/{s}/{s}", .{ cfg.bucket, src }) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(copy_source);

    const headers = buildSignedHeaders(cfg, "PUT", canonical_uri, "", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", &.{.{ "x-amz-copy-source", copy_source }}) catch return jsonResponse(500, "{\"error\":\"sign\"}");
    var resp = doRequest(.PUT, url, headers.slice()) catch return jsonResponse(502, "{\"error\":\"s3\"}");
    defer resp.deinit();
    if (ensureOk(&resp)) |err_resp| return err_resp;
    const body = std.fmt.allocPrint(allocator, "{{\"src\":\"{s}\",\"dst\":\"{s}\",\"status\":{d}}}", .{ src, dst, resp.status }) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    return .{ .status_code = 200, .content_type = "application/json", .content_type_len = 16, .body = body.ptr, .body_len = body.len };
}

export fn turboapi_init() callconv(.c) c_int {
    global_cfg = .{
        .endpoint = getEnv("TURBO_S3_ENDPOINT", global_cfg.endpoint),
        .host = global_cfg.host,
        .region = getEnv("AWS_DEFAULT_REGION", global_cfg.region),
        .access_key = getEnv("AWS_ACCESS_KEY_ID", global_cfg.access_key),
        .secret_key = getEnv("AWS_SECRET_ACCESS_KEY", global_cfg.secret_key),
        .bucket = getEnv("TURBO_S3_BUCKET", global_cfg.bucket),
    };
    global_cfg_loaded = false;
    _ = loadConfig();
    std.debug.print("[native_s3] init endpoint={s} bucket={s}\n", .{ global_cfg.endpoint, global_cfg.bucket });
    return 0;
}
