const std = @import("std");

pub const FormField = struct {
    name: []const u8,
    value: []const u8,
};

pub const FileField = struct {
    name: []const u8,
    filename: []const u8,
    content_type: []const u8,
    body: []const u8,
};

pub const MultipartResult = struct {
    fields: []FormField,
    files: []FileField,

    pub fn deinit(self: *const MultipartResult, alloc: std.mem.Allocator) void {
        alloc.free(self.fields);
        alloc.free(self.files);
    }
};

pub const UrlencodedResult = struct {
    fields: []FormField,

    pub fn deinit(self: *const UrlencodedResult, alloc: std.mem.Allocator) void {
        for (self.fields) |f| {
            alloc.free(f.name);
            alloc.free(f.value);
        }
        alloc.free(self.fields);
    }
};

pub fn extractBoundary(content_type: []const u8) ?[]const u8 {
    const marker: []const u8 = "boundary=";
    const idx = std.mem.indexOf(u8, content_type, marker) orelse return null;
    var boundary = content_type[idx + marker.len ..];

    if (boundary.len > 1 and boundary[0] == '"') {
        boundary = boundary[1..];
        const end_quote = std.mem.indexOfScalar(u8, boundary, '"') orelse boundary.len;
        boundary = boundary[0..end_quote];
    } else {
        const semi = std.mem.indexOfScalar(u8, boundary, ';') orelse boundary.len;
        boundary = boundary[0..semi];
        boundary = std.mem.trim(u8, boundary, " \t");
    }

    if (boundary.len == 0) return null;
    return boundary;
}

pub fn parseMultipart(alloc: std.mem.Allocator, body: []const u8, boundary: []const u8) !MultipartResult {
    var fields: std.ArrayListUnmanaged(FormField) = .empty;
    var files: std.ArrayListUnmanaged(FileField) = .empty;
    errdefer {
        fields.deinit(alloc);
        files.deinit(alloc);
    }

    var delim_buf: [128]u8 = undefined;
    if (boundary.len + 2 > delim_buf.len) return error.BoundaryTooLong;
    @memcpy(delim_buf[0..2], "--");
    @memcpy(delim_buf[2 .. boundary.len + 2], boundary);
    const delim: []const u8 = delim_buf[0 .. boundary.len + 2];

    var pos: usize = 0;

    const first_delim = std.mem.indexOf(u8, body, delim) orelse return MultipartResult{ .fields = fields.items, .files = files.items };
    pos = first_delim + delim.len;
    pos += std.mem.indexOf(u8, body[pos..], "\r\n") orelse 2;
    pos += 2;

    while (pos < body.len) {
        if (pos + delim.len + 2 <= body.len) {
            const candidate = body[pos .. pos + delim.len];
            if (std.mem.eql(u8, candidate, delim)) {
                if (pos + delim.len + 2 <= body.len and
                    body[pos + delim.len] == '-' and body[pos + delim.len + 1] == '-')
                {
                    break;
                }
                pos += delim.len;
                if (pos + 2 <= body.len and body[pos] == '\r' and body[pos + 1] == '\n') {
                    pos += 2;
                }
                continue;
            }
        }

        const header_end = std.mem.indexOf(u8, body[pos..], "\r\n\r\n") orelse break;
        const part_headers = body[pos .. pos + header_end];
        const part_body_start = pos + header_end + 4;

        const next_delim = std.mem.indexOf(u8, body[part_body_start..], delim) orelse break;
        var part_body = body[part_body_start .. part_body_start + next_delim];
        if (part_body.len >= 2 and part_body[part_body.len - 2] == '\r' and part_body[part_body.len - 1] == '\n') {
            part_body = part_body[0 .. part_body.len - 2];
        }

        pos = part_body_start + next_delim + delim.len;
        if (pos + 2 <= body.len and body[pos] == '\r' and body[pos + 1] == '\n') {
            pos += 2;
        }

        var field_name: []const u8 = "";
        var filename: ?[]const u8 = null;
        var ct: []const u8 = "application/octet-stream";

        var hdr_pos: usize = 0;
        while (hdr_pos < part_headers.len) {
            const line_end = std.mem.indexOf(u8, part_headers[hdr_pos..], "\r\n") orelse part_headers.len - hdr_pos;
            const line = part_headers[hdr_pos .. hdr_pos + line_end];
            hdr_pos += line_end + 2;

            const colon = std.mem.indexOfScalar(u8, line, ':') orelse continue;
            const hname = std.mem.trim(u8, line[0..colon], " \t");
            const hvalue = std.mem.trim(u8, line[colon + 1 ..], " \t");

            if (std.ascii.eqlIgnoreCase(hname, "content-disposition")) {
                const name_marker: []const u8 = "name=\"";
                if (std.mem.indexOf(u8, hvalue, name_marker)) |ni| {
                    const start = ni + name_marker.len;
                    const end_quote = std.mem.indexOfScalar(u8, hvalue[start..], '"') orelse hvalue.len - start;
                    field_name = hvalue[start .. start + end_quote];
                }
                const filename_marker: []const u8 = "filename=\"";
                if (std.mem.indexOf(u8, hvalue, filename_marker)) |fi| {
                    const start = fi + filename_marker.len;
                    const end_quote = std.mem.indexOfScalar(u8, hvalue[start..], '"') orelse hvalue.len - start;
                    filename = hvalue[start .. start + end_quote];
                }
            } else if (std.ascii.eqlIgnoreCase(hname, "content-type")) {
                ct = hvalue;
            }
        }

        if (filename) |fn_val| {
            try files.append(alloc, .{
                .name = field_name,
                .filename = fn_val,
                .content_type = ct,
                .body = part_body,
            });
        } else {
            try fields.append(alloc, .{
                .name = field_name,
                .value = part_body,
            });
        }
    }

    return MultipartResult{
        .fields = fields.items,
        .files = files.items,
    };
}

fn hexVal(c: u8) ?u8 {
    return switch (c) {
        '0'...'9' => c - '0',
        'a'...'f' => c - 'a' + 10,
        'A'...'F' => c - 'A' + 10,
        else => null,
    };
}

pub fn parseUrlencoded(alloc: std.mem.Allocator, body: []const u8) !UrlencodedResult {
    var fields: std.ArrayListUnmanaged(FormField) = .empty;
    errdefer fields.deinit(alloc);

    if (body.len == 0) return UrlencodedResult{ .fields = fields.items };

    var pos: usize = 0;
    while (pos < body.len) {
        const amp = std.mem.indexOfScalar(u8, body[pos..], '&') orelse body.len - pos;
        const pair = body[pos .. pos + amp];
        pos += amp + 1;

        if (pair.len == 0) continue;

        const eq = std.mem.indexOfScalar(u8, pair, '=') orelse pair.len;
        const key_raw = pair[0..eq];
        const val_raw = if (eq < pair.len) pair[eq + 1 ..] else pair[0..0];

        const decoded_key = try percentDecodeAlloc(alloc, key_raw);
        const decoded_val = try percentDecodeAlloc(alloc, val_raw);

        try fields.append(alloc, .{ .name = decoded_key, .value = decoded_val });
    }

    return UrlencodedResult{ .fields = fields.items };
}

pub fn percentDecodeAlloc(alloc: std.mem.Allocator, src: []const u8) ![]const u8 {
    var result: std.ArrayListUnmanaged(u8) = .empty;
    defer result.deinit(alloc);
    try result.ensureTotalCapacity(alloc, src.len);

    var i: usize = 0;
    while (i < src.len) : (i += 1) {
        if (src[i] == '%' and i + 2 < src.len) {
            const hi = hexVal(src[i + 1]) orelse {
                result.appendAssumeCapacity(src[i]);
                continue;
            };
            const lo = hexVal(src[i + 2]) orelse {
                result.appendAssumeCapacity(src[i]);
                continue;
            };
            result.appendAssumeCapacity(hi << 4 | lo);
            i += 2;
        } else if (src[i] == '+') {
            result.appendAssumeCapacity(' ');
        } else {
            result.appendAssumeCapacity(src[i]);
        }
    }

    return result.toOwnedSlice(alloc);
}

fn percentDecodeInPlace(src: []const u8, dst: []u8) []const u8 {
    var si: usize = 0;
    var di: usize = 0;
    while (si < src.len) : (si += 1) {
        if (src[si] == '%' and si + 2 < src.len) {
            const hi = hexVal(src[si + 1]) orelse {
                dst[di] = src[si];
                di += 1;
                continue;
            };
            const lo = hexVal(src[si + 2]) orelse {
                dst[di] = src[si];
                di += 1;
                continue;
            };
            dst[di] = hi << 4 | lo;
            di += 1;
            si += 2;
        } else if (src[si] == '+') {
            dst[di] = ' ';
            di += 1;
        } else {
            dst[di] = src[si];
            di += 1;
        }
    }
    return dst[0..di];
}

test "multipart: simple form field" {
    const body = "--boundary\r\n" ++
        \\Content-Disposition: form-data; name="username"
    ++
        "\r\n\r\n" ++
        \\john
    ++
        "\r\n--boundary--\r\n";
    var result = try parseMultipart(std.testing.allocator, body, "boundary");
    defer result.deinit(std.testing.allocator);
    try std.testing.expectEqual(1, result.fields.len);
    try std.testing.expectEqualStrings("username", result.fields[0].name);
    try std.testing.expectEqualStrings("john", result.fields[0].value);
    try std.testing.expectEqual(0, result.files.len);
}

test "multipart: file upload" {
    const body = "--boundary\r\n" ++
        \\Content-Disposition: form-data; name="file"; filename="test.txt"
    ++
        "\r\n" ++
        \\Content-Type: text/plain
    ++
        "\r\n\r\n" ++
        \\hello world
    ++
        "\r\n--boundary--\r\n";
    var result = try parseMultipart(std.testing.allocator, body, "boundary");
    defer result.deinit(std.testing.allocator);
    try std.testing.expectEqual(0, result.fields.len);
    try std.testing.expectEqual(1, result.files.len);
    try std.testing.expectEqualStrings("file", result.files[0].name);
    try std.testing.expectEqualStrings("test.txt", result.files[0].filename);
    try std.testing.expectEqualStrings("text/plain", result.files[0].content_type);
    try std.testing.expectEqualStrings("hello world", result.files[0].body);
}

test "multipart: mixed fields and files" {
    const body = "--boundary\r\n" ++
        \\Content-Disposition: form-data; name="title"
    ++
        "\r\n\r\n" ++
        \\My Doc
    ++
        "\r\n--boundary\r\n" ++
        \\Content-Disposition: form-data; name="upload"; filename="doc.pdf"
    ++
        "\r\n" ++
        \\Content-Type: application/pdf
    ++
        "\r\n\r\n" ++
        \\%PDF-1.4
    ++
        "\r\n--boundary--\r\n";
    var result = try parseMultipart(std.testing.allocator, body, "boundary");
    defer result.deinit(std.testing.allocator);
    try std.testing.expectEqual(1, result.fields.len);
    try std.testing.expectEqualStrings("title", result.fields[0].name);
    try std.testing.expectEqualStrings("My Doc", result.fields[0].value);
    try std.testing.expectEqual(1, result.files.len);
    try std.testing.expectEqualStrings("upload", result.files[0].name);
    try std.testing.expectEqualStrings("doc.pdf", result.files[0].filename);
}

test "urlencoded: simple" {
    const body = "name=alice&age=30";
    var result = try parseUrlencoded(std.testing.allocator, body);
    defer result.deinit(std.testing.allocator);
    try std.testing.expectEqual(2, result.fields.len);
    try std.testing.expectEqualStrings("name", result.fields[0].name);
    try std.testing.expectEqualStrings("alice", result.fields[0].value);
    try std.testing.expectEqualStrings("age", result.fields[1].name);
    try std.testing.expectEqualStrings("30", result.fields[1].value);
}

test "urlencoded: percent encoding" {
    const body = "q=hello+world&email=test%40example.com";
    var result = try parseUrlencoded(std.testing.allocator, body);
    defer result.deinit(std.testing.allocator);
    try std.testing.expectEqual(2, result.fields.len);
    try std.testing.expectEqualStrings("hello world", result.fields[0].value);
    try std.testing.expectEqualStrings("test@example.com", result.fields[1].value);
}

test "boundary extraction" {
    try std.testing.expectEqualStrings("----WebKitFormBoundary7MA4YWxkTrZu0gW", extractBoundary("multipart/form-data; boundary=----WebKitFormBoundary7MA4YWxkTrZu0gW").?);
    try std.testing.expectEqualStrings("abc123", extractBoundary("multipart/form-data; boundary=\"abc123\"").?);
    try std.testing.expect(extractBoundary("application/json") == null);
}
