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
    region: []const u8,
    access_key: []const u8,
    secret_key: []const u8,
    bucket: []const u8,
};

var global_cfg = EnvConfig{
    .endpoint = "http://localhost:4566",
    .region = "us-east-1",
    .access_key = "test",
    .secret_key = "testing",
    .bucket = "turbo-vs-fast",
};

fn getEnv(name: [:0]const u8, fallback: []const u8) []const u8 {
    const value = std.c.getenv(name);
    if (value) |ptr| return std.mem.span(ptr);
    return fallback;
}

fn loadConfig() EnvConfig {
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

fn sign(secret_key: []const u8, datestamp: []const u8, region: []const u8, service: []const u8, string_to_sign: []const u8) [64]u8 {
    const key = deriveSigningKey(secret_key, datestamp, region, service);
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
    var client = std.http.Client{ .allocator = allocator };
    defer client.deinit();

    const uri = try std.Uri.parse(url);
    var req = try client.request(method, uri, .{
        .redirect_behavior = @enumFromInt(5),
        .extra_headers = headers,
        .keep_alive = method != .HEAD,
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
) !std.ArrayList(std.http.Header) {
    const now = utcNow();
    const host = blk: {
        const uri = try std.Uri.parse(cfg.endpoint);
        const hostname = switch (uri.host orelse return error.InvalidUrl) {
            .raw => |h| h,
            .percent_encoded => |h| h,
        };
        if (uri.port) |port| {
            break :blk try std.fmt.allocPrint(allocator, "{s}:{d}", .{ hostname, port });
        }
        break :blk try allocator.dupe(u8, hostname);
    };
    defer allocator.free(host);

    var header_map = std.StringHashMap([]const u8).init(allocator);
    defer header_map.deinit();
    try header_map.put("host", host);
    try header_map.put("x-amz-content-sha256", payload_hash);
    try header_map.put("x-amz-date", &now.amz_date);
    for (extra_headers) |h| try header_map.put(h[0], h[1]);

    var keys: std.ArrayList([]const u8) = .empty;
    defer keys.deinit(allocator);
    var it = header_map.iterator();
    while (it.next()) |entry| try keys.append(allocator, entry.key_ptr.*);
    std.mem.sortUnstable([]const u8, keys.items, {}, struct {
        fn less(_: void, a: []const u8, b: []const u8) bool {
            return std.mem.lessThan(u8, a, b);
        }
    }.less);

    var canonical_headers: std.ArrayList(u8) = .empty;
    defer canonical_headers.deinit(allocator);
    for (keys.items) |k| {
        try canonical_headers.writer(allocator).print("{s}:{s}\n", .{ k, header_map.get(k).? });
    }

    const signed_headers = try std.mem.join(allocator, ";", keys.items);
    defer allocator.free(signed_headers);

    const canonical_request = try std.fmt.allocPrint(
        allocator,
        "{s}\n{s}\n{s}\n{s}\n{s}\n{s}",
        .{ method, canonical_uri, canonical_query, canonical_headers.items, signed_headers, payload_hash },
    );
    defer allocator.free(canonical_request);

    const request_hash = sha256Hex(canonical_request);
    const scope = try std.fmt.allocPrint(allocator, "{s}/{s}/s3/aws4_request", .{ &now.date_stamp, cfg.region });
    defer allocator.free(scope);
    const string_to_sign = try std.fmt.allocPrint(
        allocator,
        "AWS4-HMAC-SHA256\n{s}\n{s}\n{s}",
        .{ &now.amz_date, scope, &request_hash },
    );
    defer allocator.free(string_to_sign);

    const signature = sign(cfg.secret_key, &now.date_stamp, cfg.region, "s3", string_to_sign);
    const auth = try std.fmt.allocPrint(
        allocator,
        "AWS4-HMAC-SHA256 Credential={s}/{s}, SignedHeaders={s}, Signature={s}",
        .{ cfg.access_key, scope, signed_headers, &signature },
    );
    errdefer allocator.free(auth);

    var headers: std.ArrayList(std.http.Header) = .empty;
    errdefer {
        for (headers.items) |h| {
            if (!std.mem.eql(u8, h.name, "host") and !std.mem.eql(u8, h.name, "x-amz-content-sha256") and !std.mem.eql(u8, h.name, "x-amz-date")) allocator.free(h.value);
        }
        headers.deinit(allocator);
    }

    try headers.append(allocator, .{ .name = "host", .value = host });
    try headers.append(allocator, .{ .name = "x-amz-content-sha256", .value = payload_hash });
    try headers.append(allocator, .{ .name = "x-amz-date", .value = try allocator.dupe(u8, &now.amz_date) });
    for (extra_headers) |h| {
        try headers.append(allocator, .{ .name = h[0], .value = h[1] });
    }
    try headers.append(allocator, .{ .name = "authorization", .value = auth });
    return headers;
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

export fn handle_s3_head(req: *const Request) callconv(.c) Response {
    const cfg = loadConfig();
    const key = getParam(req, "key") orelse return jsonResponse(400, "{\"error\":\"missing key\"}");
    const canonical_uri = std.fmt.allocPrint(allocator, "/{s}/{s}", .{ cfg.bucket, key }) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(canonical_uri);
    const url = makeUrl(cfg, canonical_uri) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(url);

    var headers = buildSignedHeaders(cfg, "HEAD", canonical_uri, "", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", &.{}) catch return jsonResponse(500, "{\"error\":\"sign\"}");
    defer headers.deinit(allocator);
    var resp = doRequest(.HEAD, url, headers.items) catch return jsonResponse(502, "{\"error\":\"s3\"}");
    defer resp.deinit();
    const size = parseContentLength(resp.headers_buf) orelse 0;
    const body = std.fmt.allocPrint(allocator, "{{\"key\":\"{s}\",\"size\":{d}}}", .{ key, size }) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    return .{ .status_code = 200, .content_type = "application/json", .content_type_len = 16, .body = body.ptr, .body_len = body.len };
}

export fn handle_s3_get(req: *const Request) callconv(.c) Response {
    const cfg = loadConfig();
    const key = getParam(req, "key") orelse return jsonResponse(400, "{\"error\":\"missing key\"}");
    const canonical_uri = std.fmt.allocPrint(allocator, "/{s}/{s}", .{ cfg.bucket, key }) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(canonical_uri);
    const url = makeUrl(cfg, canonical_uri) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    defer allocator.free(url);

    var headers = buildSignedHeaders(cfg, "GET", canonical_uri, "", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", &.{}) catch return jsonResponse(500, "{\"error\":\"sign\"}");
    defer headers.deinit(allocator);
    var resp = doRequest(.GET, url, headers.items) catch return jsonResponse(502, "{\"error\":\"s3\"}");
    defer resp.deinit();
    const size = parseContentLength(resp.headers_buf) orelse resp.body.len;
    const body = std.fmt.allocPrint(allocator, "{{\"key\":\"{s}\",\"size\":{d}}}", .{ key, size }) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    return .{ .status_code = 200, .content_type = "application/json", .content_type_len = 16, .body = body.ptr, .body_len = body.len };
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

    var headers = buildSignedHeaders(cfg, "GET", canonical_uri, canonical_query, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", &.{}) catch return jsonResponse(500, "{\"error\":\"sign\"}");
    defer headers.deinit(allocator);
    var resp = doRequest(.GET, url, headers.items) catch return jsonResponse(502, "{\"error\":\"s3\"}");
    defer resp.deinit();
    const count = countTag(resp.body, "<Contents>");
    const body = std.fmt.allocPrint(allocator, "{{\"count\":{d}}}", .{count}) catch return jsonResponse(500, "{\"error\":\"oom\"}");
    return .{ .status_code = 200, .content_type = "application/json", .content_type_len = 16, .body = body.ptr, .body_len = body.len };
}

export fn turboapi_init() callconv(.c) c_int {
    global_cfg = .{
        .endpoint = getEnv("TURBO_S3_ENDPOINT", global_cfg.endpoint),
        .region = getEnv("AWS_DEFAULT_REGION", global_cfg.region),
        .access_key = getEnv("AWS_ACCESS_KEY_ID", global_cfg.access_key),
        .secret_key = getEnv("AWS_SECRET_ACCESS_KEY", global_cfg.secret_key),
        .bucket = getEnv("TURBO_S3_BUCKET", global_cfg.bucket),
    };
    std.debug.print("[native_s3] init endpoint={s} bucket={s}\n", .{ global_cfg.endpoint, global_cfg.bucket });
    return 0;
}
