const std = @import("std");

const ascii = std.ascii;
const Wyhash = std.hash.Wyhash;
const Allocator = std.mem.Allocator;

const MetricType = enum {
    counter,
    gauge,
    histogram,
};

// Used by metrics that have labels (CounterVec, GaugeVec, HistogramVec). This
// does Metric does (own the metric name, own the preamble), but also does a lot
// more with respect to labels (beause, regardless of what the underlying metric
// is, label handling is the same).
pub fn MetricVec(comptime L: type) type {
    const ti = @typeInfo(L);
    if (std.meta.activeTag(ti) != .@"struct") {
        @compileError("Vec type must be a struct, got: " ++ @typeName(L));
    }

    const fields = ti.@"struct".fields;
    inline for (fields) |f| {
        validateLabel(f.name, f.type);
    }

    // When we serialize attributes, we'll store each serialized attribute into
    // an array of this type.
    const SerializedValues = [fields.len]SerializedValue;

    // The length of the serialized attributes without the values.
    // If L is struct{status: int, path: []const u8}, then this would be the length
    // of:  {status="",path=""}
    // We use this when we need to allocate the attribute string, taking this length
    // and adding it to the length of the serialized values.
    const static_attribute_len = comptime blk: {
        // +2 for the '{' and  '}' around the entire attribute string
        // +1 for the trailing space
        // +fields.len - 1 for the comma separator between attributes
        var len: usize = 2 + 1 + fields.len - 1;
        for (fields) |f| {
            // +1 for the '=' separator between attribute name and value
            // +2 for the '"' around the value
            len += f.name.len + 3;
        }
        break :blk len;
    };

    return struct {
        // The name of the metric. Unlike with a plain Metric, this doesn't include
        // a trailing space (because attributes are glued to the metric name)
        name: []const u8,

        // The label names (which are the names of L's fields)
        labels: [fields.len][]const u8,

        // std.AutoHashMap doesn't handle structs with slices (i.e. []const u8) fields
        // So we create our own context (hash and eql) which supports the type allowed
        // by our validateLabel
        pub fn HashMap(comptime V: type) type {
            return std.HashMapUnmanaged(L, V, HashContext(L), 80);
        }

        const Self = @This();

        pub fn init(comptime name: []const u8) !Self {
            comptime validateName(name);

            comptime var labels: [fields.len][]const u8 = undefined;
            inline for (fields, 0..) |f, i| {
                labels[i] = f.name;
            }

            return .{
                .name = name,
                .labels = labels,
            };
        }

        // The key of labeled metrics is the label itself (L), or more specifically
        // the values. These need to exist for the lifetime of the entry in the map
        // so we dupe it. We only allow a small number of types in our labels and
        // the only type that needs to be allocated is a []const u8.
        pub fn dupe(allocator: Allocator, value: L) !L {
            var owned: L = undefined;
            inline for (fields) |f| {
                switch (@typeInfo(f.type)) {
                    .pointer => @field(owned, f.name) = try allocator.dupe(u8, @field(value, f.name)),
                    else => @field(owned, f.name) = @field(value, f.name), // all other fields are primitives
                }
            }
            return owned;
        }

        // Frees memory allocated by the above dupe function.
        pub fn free(allocator: Allocator, value: L) void {
            inline for (fields) |f| {
                switch (@typeInfo(f.type)) {
                    .pointer => allocator.free(@field(value, f.name)),
                    else => {}, // all other fields are primitives
                }
            }
        }

        // Every labeled metric has a hashmap of label => VALUE
        // Where VALUE is going to be a metric specific value (like a number for
        // a counter) as well as the serialized attribute string. For example
        // given a CounterVec(u64, struct{status: u16}) and the label:
        //   .{.status = 200}
        // The counter's hashmap will have an extra with the key being the label
        // itself, a u64 count and the serialized label value:
        //   200 => .{
        //       .count = 1,
        //       .attributes = "{status=\"200\"}\n"
        //   }
        //
        // Given:
        //   .{.status = 200}
        // this function builds the attribute string:
        //   "{status=\"200\"}\n"
        pub fn buildAttributes(allocator: Allocator, values: L) ![]const u8 {

            // We begin by serializing all the values in L. We only support a few label
            // types and some don't require allocation. The serializeValue function
            // returns a SerializedValue which contains the serialized (string)
            // representation of the value and a boolean to indicate if an allocation
            // took place. This is needed so that we can properly clean up.
            var len: usize = 0;
            var serialized: SerializedValues = undefined;
            inline for (fields, 0..) |f, i| {
                const s = try serializeValue(allocator, @field(values, f.name));
                serialized[i] = s;
                len += s.str.len;
            }

            // Any allocations done in serializeValue is short lived, because we'll
            // copy everything into the final attribute string.
            defer {
                for (serialized) |s| {
                    if (s.allocated) allocator.free(s.str);
                }
            }

            var buf = try allocator.alloc(u8, static_attribute_len + len);
            buf[0] = '{';
            var pos: usize = 1;
            inline for (fields, 0..) |f, i| {
                {
                    // write the key
                    const value = f.name;
                    const end = pos + value.len;
                    @memcpy(buf[pos..end], value);
                    pos = end;
                }

                buf[pos] = '=';
                buf[pos + 1] = '"';
                pos += 2;

                {
                    // write the value
                    const value = serialized[i];
                    const end = pos + value.str.len;
                    @memcpy(buf[pos..end], value.str);
                    buf[end] = '"';
                    pos = end + 1;
                }
                buf[pos] = ',';
                pos += 1;
            }
            // -1 to overwrite the last trailing comma
            buf[pos - 1] = '}';
            // space between our attribute string and the metric value
            buf[pos] = ' ';
            return buf;
        }
    };
}

// Writes value to writer. Value can either be an integer or float.
pub fn write(value: anytype, writer: *std.io.Writer) !void {
    switch (@typeInfo(@TypeOf(value))) {
        .int => return writer.printInt(value, 10, .lower, .{}),
        .float => return writer.print("{d}", .{value}),
        else => unreachable, // there are guards that prevent this from being possible
    }
}

// Validates that a metric name is valid, based on:
// https://prometheus.io/docs/concepts/data_model/#metric-names-and-labels
fn validateName(comptime name: []const u8) void {
    if (name.len == 0) {
        @compileError("Empty metric name is not valid");
    }

    {
        const c = name[0];
        if (!ascii.isAlphabetic(c) and c != '_' and c != ':') {
            @compileError("Metric name must begin with a letter, underscore or colon ([a-zA-Z_:])");
        }
    }

    for (name[1..]) |c| {
        if (!ascii.isAlphanumeric(c) and c != '_' and c != ':') {
            @compileError("Metric name can only contain ascii letters, numbers, underscores and colons ([a-zA-Z_:][a-zA-Z0-9_:]*)");
        }
    }
}

// Validates that a label is valid. Validates both the name and the type.
// The validity of the name is based on:
// https://prometheus.io/docs/concepts/data_model/#metric-names-and-labels
// The validity of the type is based on what our HashContext supports
fn validateLabel(comptime name: []const u8, comptime T: type) void {
    if (name.len == 0) {
        @compileError("Empty label name is not valid");
    }

    {
        const c = name[0];
        if (!ascii.isAlphabetic(c) and c != '_') {
            @compileError("Label name must begin with a letter, underscore or colon ([a-zA-Z_])");
        }

        if (c == '_' and name.len > 1 and name[1] == '_') {
            @compileError("Label names starting with double underscore are reserved");
        }
    }

    for (name[1..]) |c| {
        if (!ascii.isAlphanumeric(c) and c != '_') {
            @compileError("Label name can only contain ascii letters, numbers and underscores ([a-zA-Z_:][a-zA-Z0-9_]*)");
        }
    }

    switch (@typeInfo(T)) {
        .error_set, .@"enum", .type, .bool, .int => return,
        .pointer => |ptr| {
            switch (ptr.size) {
                .slice => {
                    if (ptr.child == u8) {
                        return;
                    }
                },
                else => {},
            }
        },
        else => {},
    }
    @compileError("Label data types " ++ @typeName(T) ++ " is not supported");
}

// attribite value => text
fn serializeValue(allocator: Allocator, value: anytype) !SerializedValue {
    switch (@typeInfo(@TypeOf(value))) {
        .int => {
            const digits = numberOfDigits(value);
            const buf = try allocator.alloc(u8, digits);
            var writer: std.io.Writer = .fixed(buf);
            try writer.printInt(value, 10, .lower, .{});
            std.debug.assert(writer.end == digits);
            return .{ .str = buf, .allocated = true };
        },
        .bool => return .{ .str = if (value) "true" else "false" },
        .pointer => {
            // validateLabel would only allow a []u8, so if we're here, it has to be a []u8
            // but the value might need to be escaped,
            var escape_count: usize = 0;
            for (value) |c| {
                if (c == '\\' or c == '\n' or c == '"') {
                    escape_count += 1;
                }
            }
            if (escape_count == 0) {
                return .{ .str = value };
            }
            var pos: usize = 0;
            var escaped = try allocator.alloc(u8, value.len + escape_count);
            for (value) |c| {
                switch (c) {
                    '\\' => {
                        escaped[pos] = '\\';
                        pos += 1;
                        escaped[pos] = '\\';
                    },
                    '\n' => {
                        escaped[pos] = '\\';
                        pos += 1;
                        escaped[pos] = 'n';
                    },
                    '"' => {
                        escaped[pos] = '\\';
                        pos += 1;
                        escaped[pos] = '"';
                    },
                    else => escaped[pos] = c,
                }
                pos += 1;
            }
            return .{ .str = escaped, .allocated = true };
        },
        .type => return .{ .str = @typeName(value) },
        .@"enum" => return .{ .str = @tagName(value) },
        .error_set => return .{ .str = @errorName(value) },
        else => unreachable,
    }
}

// When allocate is true, then str was allocated (and needed to be freed)
const SerializedValue = struct {
    str: []const u8,
    allocated: bool = false,
};

// Return the number of digits in a number, including a negative sign.
fn numberOfDigits(value: anytype) usize {
    const adj: usize = if (value < 0) 1 else 0;
    var v = @abs(value);
    var count: usize = 1;
    while (true) {
        if (v < 10) return count + adj;
        if (v < 100) return count + adj + 1;
        if (v < 1000) return count + adj + 2;
        if (v < 10000) return count + adj + 3;
        if (v < 100000) return count + adj + 4;
        if (v < 1000000) return count + adj + 5;
        v = v / 1000000;
        count += 6;
    }
}

// See MetricVec.HashMap above
fn HashContext(comptime K: type) type {
    return struct {
        const Self = @This();

        const fields = @typeInfo(K).@"struct".fields;

        pub fn hash(_: Self, key: K) u64 {
            var hasher = Wyhash.init(0);
            inline for (fields) |field| {
                hashValue(&hasher, @field(key, field.name));
            }
            return hasher.final();
        }

        // similar to std.mem.eql, but compares string values
        pub fn eql(_: Self, a: K, b: K) bool {
            inline for (fields) |field| {
                const value_a = @field(a, field.name);
                const value_b = @field(b, field.name);
                switch (@typeInfo(@TypeOf(value_a))) {
                    .pointer => if (std.mem.eql(u8, value_a, value_b) == false) return false,
                    else => if (value_a != value_b) return false,
                }
            }
            return true;
        }

        // Similar to what you'd find in std/hash/auto_hash.zig
        // but only accepts a subset of types (only those types we support as label
        // values) and accepts a []u8 value.
        fn hashValue(hasher: *Wyhash, value: anytype) void {
            const V = @TypeOf(value);
            switch (@typeInfo(V)) {
                .int => |int| switch (int.signedness) {
                    .signed => hashValue(hasher, @as(@Int(int.bits, .unsigned), @bitCast(value))),
                    .unsigned => {
                        if (std.meta.hasUniqueRepresentation(V)) {
                            hasher.update(std.mem.asBytes(&value));
                        } else {
                            const byte_size = comptime std.math.divCeil(comptime_int, @bitSizeOf(V), 8) catch unreachable;
                            hasher.update(std.mem.asBytes(&value)[0..byte_size]);
                        }
                    },
                },
                .@"enum" => hashValue(hasher, @intFromEnum(value)),
                .error_set => hashValue(hasher, @intFromError(value)),
                .bool => hasher.update(if (value) &.{1} else &.{0}),
                .pointer => hasher.update(value), // validateLabelType ensures this was a []u8
                .type => hasher.update(@typeName(value)),
                else => unreachable, // validateLabelType only allows the above types
            }
        }
    };
}

// The "preamble" is the optional "# HELP $DESC\n" and "# TYPE $TYPE\n" string
// which is output before the metric value. Help is optional, when null the
// "# HELP ..." line is omitted.
pub fn preamble(comptime name: []const u8, comptime tpe: MetricType, comptime append_name: bool, comptime help_: ?[]const u8) []const u8 {
    comptime {
        const suffix = if (append_name) name ++ " " else "";
        const type_line = std.fmt.comptimePrint("# TYPE {s} {s}\n{s}", .{ name, @tagName(tpe), suffix });
        const help = help_ orelse return type_line;

        // Help text requires \\ and \n to be escaped. Let's count how many of those we have.
        var escape_count: usize = 0;
        for (help) |c| {
            if (c == '\\' or c == '\n') {
                escape_count += 1;
            }
        }

        var h = help;
        if (escape_count > 0) {
            // We need to escape at least one special character. We need to allocate
            // a new string to hold the escaped value

            // Since we know the original length and the # of characters that need to
            // be escaped, we know the final length)
            var escaped: [help.len + escape_count]u8 = undefined;

            var pos: usize = 0;
            for (help) |c| {
                switch (c) {
                    '\\' => {
                        escaped[pos] = '\\';
                        pos += 1;
                        escaped[pos] = '\\';
                    },
                    '\n' => {
                        escaped[pos] = '\\';
                        pos += 1;
                        escaped[pos] = 'n';
                    },
                    else => escaped[pos] = c,
                }
                pos += 1;
            }

            h = &escaped;
        }

        return std.fmt.comptimePrint("# HELP {s} {s}\n{s}", .{ name, h, type_line });
    }
}

const t = @import("t.zig");
test "preamble: no help" {
    const p = comptime preamble("metric_test_1", .counter, true, null);
    try t.expectString("# TYPE metric_test_1 counter\nmetric_test_1 ", p);
}

test "preamble: no help, histogram" {
    // histogram doesn't include the metric name it he preamble
    const p = comptime preamble("metric_test_1", .histogram, false, null);
    try t.expectString("# TYPE metric_test_1 histogram\n", p);
}

test "preamble: simple help" {
    const p = comptime preamble("metric_test_2", .gauge, true, "this is a valid help line");
    try t.expectString("# HELP metric_test_2 this is a valid help line\n# TYPE metric_test_2 gauge\nmetric_test_2 ", p);
}

test "preamble: escape help" {
    const p = comptime preamble("metric_test_3", .histogram, false, "th\\is is a\nvalid help line");
    try t.expectString("# HELP metric_test_3 th\\\\is is a\\nvalid help line\n# TYPE metric_test_3 histogram\n", p);
}

test "MetricVec: labels" {
    const m = try MetricVec(struct {
        active: bool,
        name: []const u8,
    }).init("metric_vec_test_1");
    try t.expectSlice([]const u8, &.{ "active", "name" }, &m.labels);
}

test "MetricVec: dupe/free" {
    const base = t.AllLabels{
        .id = -320,
        .key = 4199,
        .active = true,
        .err = error.OutOfMemory,
        .state = .start,
        .tag = "teg",
    };
    const d = try MetricVec(t.AllLabels).dupe(t.allocator, .{
        .id = -320,
        .key = 4199,
        .active = true,
        .err = error.OutOfMemory,
        .state = .start,
        .tag = "teg",
    });
    defer MetricVec(t.AllLabels).free(t.allocator, d);

    try t.expectEqual(-320, d.id);
    try t.expectEqual(4199, d.key);
    try t.expectEqual(true, d.active);
    try t.expectEqual(error.OutOfMemory, d.err);
    try t.expectEqual(.start, d.state);
    try t.expectString("teg", d.tag);
    try t.expectEqual(false, d.tag.ptr == base.tag.ptr);
}

test "MetricVec: buildAttributes" {
    {
        const l = try MetricVec(t.AllLabels).buildAttributes(t.allocator, .{
            .id = -320,
            .key = 4199,
            .active = true,
            .err = error.OutOfMemory,
            .state = .start,
            .tag = "teg",
        });
        defer t.allocator.free(l);
        try t.expectString("{id=\"-320\",key=\"4199\",active=\"true\",err=\"OutOfMemory\",state=\"start\",tag=\"teg\"} ", l);
    }

    {
        // Escape string
        const l = try MetricVec(struct { n: []const u8 }).buildAttributes(t.allocator, .{
            .n = "hello\nworld, how's\\it \"going\"",
        });
        defer t.allocator.free(l);
        try t.expectString("{n=\"hello\\nworld, how's\\\\it \\\"going\\\"\"} ", l);
    }
}

test "HashContext" {
    var h = MetricVec(t.AllLabels).HashMap(i32){};
    defer h.deinit(t.allocator);

    const k1a = t.AllLabels{
        .id = -320,
        .key = 4199,
        .active = true,
        .err = error.OutOfMemory,
        .state = .start,
        .tag = "teg",
    };

    // same as k1b, but our string (tag) is a different ptr
    const k1b = t.AllLabels{
        .id = -320,
        .key = 4199,
        .active = true,
        .err = error.OutOfMemory,
        .state = .start,
        .tag = try t.allocator.dupe(u8, "teg"),
    };
    defer t.allocator.free(k1b.tag);

    {
        const gop = try h.getOrPut(t.allocator, k1a);
        try t.expectEqual(false, gop.found_existing);
        gop.value_ptr.* = 1;
    }

    {
        const gop = try h.getOrPut(t.allocator, k1a);
        try t.expectEqual(true, gop.found_existing);
        try t.expectEqual(1, gop.value_ptr.*);
        gop.value_ptr.* = 2;
    }

    {
        const gop = try h.getOrPut(t.allocator, k1b);
        try t.expectEqual(true, gop.found_existing);
        try t.expectEqual(2, gop.value_ptr.*);
        gop.value_ptr.* = 3;
    }

    {
        // different int
        var k = k1a;
        k.id = 320;
        {
            const gop = try h.getOrPut(t.allocator, k);
            try t.expectEqual(false, gop.found_existing);
            gop.value_ptr.* = 3;
        }
        {
            const gop = try h.getOrPut(t.allocator, k);
            try t.expectEqual(true, gop.found_existing);
            try t.expectEqual(3, gop.value_ptr.*);
        }
    }

    {
        // different u13
        var k = k1a;
        k.key += 1;
        {
            const gop = try h.getOrPut(t.allocator, k);
            try t.expectEqual(false, gop.found_existing);
            gop.value_ptr.* = 4;
        }
        {
            const gop = try h.getOrPut(t.allocator, k);
            try t.expectEqual(true, gop.found_existing);
            try t.expectEqual(4, gop.value_ptr.*);
        }
    }

    {
        // different bool
        var k = k1a;
        k.active = !k.active;
        {
            const gop = try h.getOrPut(t.allocator, k);
            try t.expectEqual(false, gop.found_existing);
            gop.value_ptr.* = 5;
        }
        {
            const gop = try h.getOrPut(t.allocator, k);
            try t.expectEqual(true, gop.found_existing);
            try t.expectEqual(5, gop.value_ptr.*);
        }
    }

    {
        // different err
        var k = k1a;
        k.err = error.Other;
        {
            const gop = try h.getOrPut(t.allocator, k);
            try t.expectEqual(false, gop.found_existing);
            gop.value_ptr.* = 6;
        }
        {
            const gop = try h.getOrPut(t.allocator, k);
            try t.expectEqual(true, gop.found_existing);
            try t.expectEqual(6, gop.value_ptr.*);
        }
    }

    {
        // different enum
        var k = k1a;
        k.state = .end;
        {
            const gop = try h.getOrPut(t.allocator, k);
            try t.expectEqual(false, gop.found_existing);
            gop.value_ptr.* = 7;
        }
        {
            const gop = try h.getOrPut(t.allocator, k);
            try t.expectEqual(true, gop.found_existing);
            try t.expectEqual(7, gop.value_ptr.*);
        }
    }

    {
        // different string
        var k = k1a;
        k.tag = "tag";
        {
            const gop = try h.getOrPut(t.allocator, k);
            try t.expectEqual(false, gop.found_existing);
            gop.value_ptr.* = 8;
        }
        {
            const gop = try h.getOrPut(t.allocator, k);
            try t.expectEqual(true, gop.found_existing);
            try t.expectEqual(8, gop.value_ptr.*);
        }
    }
}

test "numberOfDigits" {
    try t.expectEqual(1, numberOfDigits(@as(i32, 0)));
    try t.expectEqual(1, numberOfDigits(@as(u9, 1)));
    try t.expectEqual(2, numberOfDigits(@as(i16, -1)));
    try t.expectEqual(10, numberOfDigits(@as(u33, 1234567890)));
    try t.expectEqual(19, numberOfDigits(@as(usize, 9223372036854775807)));
    try t.expectEqual(20, numberOfDigits(@as(i64, -9223372036854775808)));
}
