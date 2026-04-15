const std = @import("std");
const lib = @import("lib.zig");

const types = lib.types;
const proto = lib.proto;
const Conn = lib.Conn;
const Allocator = std.mem.Allocator;
const ArenaAllocator = std.heap.ArenaAllocator;

pub const Result = struct {
    number_of_columns: usize,

    // will be empty unless the query was executed with the column_names = true option
    column_names: [][]const u8,

    _conn: *Conn,
    _arena: *ArenaAllocator,

    // a sliced version of _state.oids (so we don't have to keep reslicing it to
    // number_of_columns on each row)
    _oids: []i32,

    // a sliced version of _state.values (so we don't have to keep reslicing it to
    // number_of_columns on each row)
    _values: []State.Value,

    // When true, result.deinit() will call conn.release()
    // Used when the result came directly from the pool.query() helper.
    _release_conn: bool,

    pub fn deinit(self: *const Result) void {
        // value.data references the buffer of the reader, this buffer is potentially
        // reused and potentially discarded. There are at least a few very good
        // reasons why the least we can do is blank it out.
        for (self._values) |*value| {
            value.data = &[_]u8{};
        }

        self._conn._reader.endFlow() catch {
            // this can only fail in extreme conditions (OOM) and it will only impact
            // the next query (and if the app is using the pool, the pool will try to
            // recover from this anyways)
            self._conn._state = .fail;
        };

        if (self._release_conn) {
            self._conn.release();
        }

        const arena = self._arena;
        const allocator = arena.child_allocator;
        arena.deinit();
        allocator.destroy(arena);
    }

    // Caller should typically call next() until null is returned.
    // But in some cases, that might not be desirable. So they can
    // "drain" to empty the rest of the result.
    // I don't want to do this implictly in deinit because it can fail
    // and returning an error union in deinit is a pain for the caller.
    pub fn drain(self: *Result) !void {
        var conn = self._conn;
        if (conn._state == .idle) {
            return;
        }

        while (true) {
            const msg = try conn.read();
            switch (msg.type) {
                'C' => {}, // CommandComplete
                'D' => {}, // DataRow
                'Z' => return,
                else => return error.UnexpectedDBMessage,
            }
        }
    }

    pub fn next(self: *Result) !?Row {
        return self._next(.safe);
    }
    pub fn nextUnsafe(self: *Result) !?RowUnsafe {
        return self._next(.unsafe);
    }

    fn _next(self: *Result, comptime fail_mode: lib.FailMode) !(if (fail_mode == .safe) ?Row else ?RowUnsafe) {
        if (self._conn._state != .query) {
            // Possibly weird state. Most likely cause is calling next() multiple times
            // despite null being returned.
            return null;
        }

        const msg = try self._conn.read();
        switch (msg.type) {
            'D' => {
                const data = msg.data;
                // Since our Row API gets data by column #, we need translate the column
                // # to a slice within msg.data. We could do this on the fly within Row,
                // but creating this mapping up front simplifies things and, in normal
                // cases, performs best. "Normal case" here assumes that the client app
                // is going to fetch most/all columns.

                // first column starts at position 2
                var offset: usize = 2;
                const values = self._values;
                for (values) |*value| {
                    const data_start = offset + 4;
                    const length = std.mem.readInt(i32, data[offset..data_start][0..4], .big);
                    if (length == -1) {
                        value.is_null = true;
                        value.data = &[_]u8{};
                        offset = data_start;
                    } else {
                        const data_end = data_start + @as(usize, @intCast(length));
                        value.is_null = false;
                        value.data = data[data_start..data_end];
                        offset = data_end;
                    }
                }

                return .{
                    .values = values,
                    .oids = self._oids,
                    ._result = self,
                };
            },
            'C' => {
                try self._conn.readyForQuery();
                return null;
            },
            else => return error.UnexpectedDBMessage,
        }
    }

    pub fn columnIndex(self: *const Result, column_name: []const u8) ?usize {
        for (self.column_names, 0..) |n, i| {
            if (std.mem.eql(u8, n, column_name)) {
                return i;
            }
        }
        return null;
    }

    const MapperOpts = struct {
        dupe: bool = false,
        allocator: ?Allocator = null,
    };

    pub fn mapper(self: *Result, comptime T: type, opts: MapperOpts) Mapper(T) {
        var column_indexes: [std.meta.fields(T).len]?usize = undefined;

        inline for (std.meta.fields(T), 0..) |field, i| {
            column_indexes[i] = self.columnIndex(field.name);
        }

        // if we're given an allocator, use that.
        // if we're not given an allocator, but asked to dupe use our arena and thus
        // tie the lifetime of the returned T to the lifetime of the DB result object.
        var allocator: ?Allocator = null;
        if (opts.allocator) |a| {
            allocator = a;
        } else if (opts.dupe) {
            allocator = self._arena.allocator();
        }

        return .{
            .result = self,
            .allocator = allocator,
            .column_indexes = column_indexes,
        };
    }

    // For every query, we need to store the type of each column (so we know
    // how to parse the data). Optionally, we might need the name of each column.
    // The connection has a default Result.State for a max # of columns, and we'll use
    // that whenever we can. Otherwise, we'll create this dynamically.
    pub const State = struct {
        // The name for each returned column, we only populate this if we're told
        // to (since it requires us to dupe the data)
        names: [][]const u8,

        // This is different than the above. The above are set once per query
        // from the RowDescription response of our Describe message. This is set for
        // each DataRow message we receive. It maps a column position with the encoded
        // value.
        values: []Value,

        // The OID for each returned column
        oids: []i32,

        pub const Value = struct {
            is_null: bool,
            data: []const u8,
        };

        pub fn init(allocator: Allocator, size: usize) !State {
            const names = try allocator.alloc([]const u8, size);
            errdefer allocator.free(names);

            const values = try allocator.alloc(Value, size);
            errdefer allocator.free(values);

            const oids = try allocator.alloc(i32, size);
            errdefer allocator.free(oids);

            return .{
                .names = names,
                .values = values,
                .oids = oids,
            };
        }

        // Populates the State from the RowDescription payload
        // We already read the number_of_columns from data, so we pass it in here
        // We also already know that number_of_columns fits within our arrays
        pub fn from(self: *State, number_of_columns: u16, data: []const u8, allocator: ?Allocator) !void {
            // skip the column count, which we already know as number_of_columns
            var pos: usize = 2;

            for (0..number_of_columns) |i| {
                const end_pos = std.mem.indexOfScalarPos(u8, data, pos, 0) orelse return error.InvalidDataRow;
                if (data.len < (end_pos + 19)) {
                    return error.InvalidDataRow;
                }
                if (allocator) |a| {
                    self.names[i] = try a.dupe(u8, data[pos..end_pos]);
                }

                // skip the name null terminator (1)
                // skip the table object_id this table belongs to (4)
                // skip the attribute number of this table column (2)
                pos = end_pos + 7;

                {
                    const end = pos + 4;
                    self.oids[i] = std.mem.readInt(i32, data[pos..end][0..4], .big);
                    pos = end;
                }

                // skip date type size (2), type modifier (4) format code (2)
                pos += 8;
            }
        }

        pub fn deinit(self: State, allocator: Allocator) void {
            allocator.free(self.names);
            allocator.free(self.values);
            allocator.free(self.oids);
        }
    };
};

pub const Row = RowT(.safe);
pub const RowUnsafe = RowT(.unsafe);

pub fn RowT(comptime fail_mode: lib.FailMode) type {
    return struct {
        _result: *Result,
        oids: []i32,
        values: []Result.State.Value,

        const Self = @This();

        pub fn get(self: *const Self, comptime T: type, col: usize) if (fail_mode == .safe) lib.TypeError!T else T {
            const value = self.values[col];
            const TT = switch (@typeInfo(T)) {
                .optional => |opt| {
                    if (value.is_null) {
                        return null;
                    }
                    const val = self.get(opt.child, col);
                    if (comptime fail_mode == .safe) {
                        return try val;
                    }
                    return val;
                },
                .@"struct" => blk: {
                    if (@hasDecl(T, "fromPgzRow") == true) {
                        return T.fromPgzRow(value.data, self.oids[col]) catch |err| {
                            if (comptime fail_mode == .safe) {
                                return err;
                            }
                            std.debug.panic("PostgreSQL value of type {s} could not be read into a " ++ @typeName(T) ++ ".", .{types.oidToString(self.oids[col])});
                        };
                    }
                    break :blk T;
                },
                else => blk: {
                    lib.verifyNotNull(fail_mode, T, value.is_null) catch |err| {
                        if (comptime fail_mode == .unsafe) unreachable;
                        return err;
                    };
                    break :blk T;
                },
            };

            return getScalar(fail_mode, TT, value.data, self.oids[col]);
        }

        pub fn getCol(self: *const Self, comptime T: type, name: []const u8) if (fail_mode == .safe) lib.TypeError!T else T {
            const col = self._result.columnIndex(name);
            try lib.verifyColumnName(fail_mode, name, col != null);
            return self.get(T, col.?);
        }

        pub fn iterator(self: *const Self, comptime T: type, col: usize) if (fail_mode == .safe) lib.TypeError!Iterator(T) else IteratorUnsafe(T) {
            const value = self.values[col];
            if (value.is_null) {
                return IteratorT(fail_mode, T).asNull();
            }
            return IteratorT(fail_mode, T).fromPgzRow(value.data, self.oids[col]) catch |err| {
                if (comptime fail_mode == .safe) {
                    return err;
                }
                @panic("Could not get iterator of type " ++ @typeName(T) ++ " for row.");
            };
        }

        pub fn iteratorCol(self: *const Self, comptime T: type, name: []const u8) if (fail_mode == .safe) lib.TypeError!Iterator(T) else IteratorUnsafe(T) {
            const col = self._result.columnIndex(name);
            try lib.verifyColumnName(fail_mode, name, col != null);
            return self.iterator(T, col.?);
        }

        pub fn record(self: *const Self, col: usize) RecordT(fail_mode) {
            const data = self.values[col].data;
            const number_of_columns = std.mem.readInt(i32, data[0..4], .big);
            return .{
                .data = data[4..],
                .number_of_columns = @intCast(number_of_columns),
            };
        }

        pub fn recordCol(self: *const Self, name: []const u8) if (fail_mode == .safe) lib.TypeError!Record else RecordUnsafe {
            const col = self._result.columnIndex(name);
            try lib.verifyColumnName(fail_mode, name, col != null);
            return self.record(col);
        }

        const ToOpts = struct {
            dupe: bool = false,
            map: Mapping = .ordinal,
            allocator: ?Allocator = null,

            const Mapping = enum {
                name,
                ordinal,
            };
        };

        pub fn to(self: *const Self, T: type, opts: ToOpts) !T {
            // if we're given an allocator, use that.
            // if we're not given an allocator, but asked to dupe use our arena and thus
            // tie the lifetime of the returned T to the lifetime of the DB result object.
            var allocator: ?Allocator = null;
            if (opts.allocator) |a| {
                allocator = a;
            } else if (opts.dupe) {
                allocator = self._result._arena.allocator();
            }

            return switch (opts.map) {
                .ordinal => self.toUsingOrdinal(T, allocator),
                .name => return self.toUsingName(T, allocator),
            };
        }

        fn toUsingOrdinal(self: *const Self, T: type, allocator: ?Allocator) !T {
            var value: T = undefined;
            inline for (std.meta.fields(T), 0..) |field, column_index| {
                @field(value, field.name) = try self.mapColumn(&field, column_index, allocator);
            }
            return value;
        }

        fn toUsingName(self: *const Self, T: type, allocator: ?Allocator) !T {
            var value: T = undefined;
            const result = self._result;
            inline for (std.meta.fields(T)) |field| {
                const name = field.name;
                @field(value, name) = try self.mapColumn(&field, result.columnIndex(name), allocator);
            }
            return value;
        }

        fn mapColumn(self: *const Self, field: *const std.builtin.Type.StructField, optional_column_index: ?usize, allocator: ?Allocator) !field.type {
            const T = field.type;
            const column_index = optional_column_index orelse {
                if (field.default_value_ptr) |dflt| {
                    return @as(*align(1) const field.type, @ptrCast(dflt)).*;
                }
                return error.FieldColumnMismatch;
            };

            if (comptime isSlice(T)) |S| {
                const slice = blk: {
                    if (@typeInfo(T) == .optional) {
                        break :blk self.get(?Iterator(S), column_index) orelse return null;
                    } else {
                        break :blk self.get(Iterator(S), column_index);
                    }
                };
                return try slice.alloc(allocator orelse return error.AllocatorRequiredForSliceMapping);
            }

            const value = self.get(field.type, column_index);
            const a = allocator orelse return value;
            return mapValue(T, if (comptime fail_mode == .safe) try value else value, a);
        }

        /// Write a single column's value as JSON to a buffer.
        /// Handles all Postgres types: int, float, numeric, bool, text, jsonb, arrays, timestamps.
        /// Returns the number of bytes written.
        pub fn writeJsonValue(self: *const Self, col: usize, buf: []u8) usize {
            const value = self.values[col];
            if (value.is_null) {
                if (buf.len < 4) return 0;
                @memcpy(buf[0..4], "null");
                return 4;
            }

            const data = value.data;
            const oid = self.oids[col];
            var pos: usize = 0;

            switch (oid) {
                // Integers
                21 => { // int2
                    const v = std.mem.readInt(i16, data[0..2], .big);
                    const s = std.fmt.bufPrint(buf[pos..], "{d}", .{v}) catch return 0;
                    pos += s.len;
                },
                23 => { // int4
                    const v = std.mem.readInt(i32, data[0..4], .big);
                    const s = std.fmt.bufPrint(buf[pos..], "{d}", .{v}) catch return 0;
                    pos += s.len;
                },
                20 => { // int8
                    const v = std.mem.readInt(i64, data[0..8], .big);
                    const s = std.fmt.bufPrint(buf[pos..], "{d}", .{v}) catch return 0;
                    pos += s.len;
                },
                // Floats
                700 => { // float4
                    const n = std.mem.readInt(i32, data[0..4], .big);
                    const v: f32 = @bitCast(n);
                    const s = std.fmt.bufPrint(buf[pos..], "{d}", .{v}) catch return 0;
                    pos += s.len;
                },
                701 => { // float8
                    const n = std.mem.readInt(i64, data[0..8], .big);
                    const v: f64 = @bitCast(n);
                    const s = std.fmt.bufPrint(buf[pos..], "{d}", .{v}) catch return 0;
                    pos += s.len;
                },
                // Numeric/Decimal — decode via Numeric type then format
                1700 => {
                    const numeric = types.Numeric.decode(fail_mode, data, oid) catch {
                        @memcpy(buf[pos..][0..4], "null");
                        return pos + 4;
                    };
                    const v = numeric.toFloat();
                    const s = std.fmt.bufPrint(buf[pos..], "{d}", .{v}) catch return 0;
                    pos += s.len;
                },
                // Bool
                16 => {
                    const v = data[0] != 0;
                    const s = if (v) "true" else "false";
                    @memcpy(buf[pos..][0..s.len], s);
                    pos += s.len;
                },
                // JSON — already valid JSON, pass through
                114 => {
                    @memcpy(buf[pos..][0..data.len], data);
                    pos += data.len;
                },
                // JSONB — strip version byte, pass through
                3802 => {
                    const json_data = data[1..];
                    @memcpy(buf[pos..][0..json_data.len], json_data);
                    pos += json_data.len;
                },
                // Integer arrays
                1005, 1007, 1016 => { // int2[], int4[], int8[]
                    pos += writeIntArrayJson(data, oid, buf[pos..]);
                },
                // Text arrays
                1009, 1015 => { // text[], varchar[]
                    pos += writeTextArrayJson(data, buf[pos..]);
                },
                // Timestamp — format as ISO 8601
                1114, 1184 => { // timestamp, timestamptz
                    const usec = std.mem.readInt(i64, data[0..8], .big);
                    // Postgres epoch is 2000-01-01, Unix is 1970-01-01
                    const pg_epoch_offset: i64 = 946684800;
                    const unix_sec = @divTrunc(usec, 1_000_000) + pg_epoch_offset;
                    buf[pos] = '"';
                    pos += 1;
                    const s = std.fmt.bufPrint(buf[pos..], "{d}", .{unix_sec}) catch return 0;
                    pos += s.len;
                    buf[pos] = '"';
                    pos += 1;
                },
                // Everything else — check for pgvector, then fall back to quoted string
                else => {
                    // pgvector support — dynamic OID, check at runtime
                    if (types.Vector.oid_decimal != 0 and oid == types.Vector.oid_decimal) {
                        const vec = types.Vector.decode(data);
                        pos += vec.writeJson(buf[pos..]);
                        return pos;
                    }
                    // Default: quote as string (SIMD-accelerated escape scan)
                    buf[pos] = '"';
                    pos += 1;
                    pos += simdJsonEscape(data, buf[pos..]);
                    buf[pos] = '"';
                    pos += 1;
                },
            }
            return pos;
        }

        /// Write an entire row as a JSON object: {"col1":val1,"col2":val2,...}
        /// Requires column_names to be populated (queryOpts with .column_names = true).
        pub fn writeJsonRow(self: *const Self, col_names: []const []const u8, buf: []u8) usize {
            var pos: usize = 0;
            buf[pos] = '{';
            pos += 1;

            const ncols = @min(col_names.len, self.values.len);
            for (0..ncols) |i| {
                if (i > 0) {
                    buf[pos] = ',';
                    pos += 1;
                }
                // Column name
                buf[pos] = '"';
                pos += 1;
                @memcpy(buf[pos..][0..col_names[i].len], col_names[i]);
                pos += col_names[i].len;
                buf[pos] = '"';
                pos += 1;
                buf[pos] = ':';
                pos += 1;
                // Value
                pos += self.writeJsonValue(i, buf[pos..]);
            }

            buf[pos] = '}';
            pos += 1;
            return pos;
        }
    };
}

/// SIMD-accelerated JSON string escaping.
/// Scans 16 bytes at a time for chars needing escape (", \, control chars).
/// Falls back to scalar for remainder and when escapes are found.
fn simdJsonEscape(data: []const u8, buf: []u8) usize {
    const simd_width = 16;
    var pos: usize = 0;
    var i: usize = 0;

    // SIMD fast path: check 16 bytes at a time for escape-needing chars
    while (i + simd_width <= data.len and pos + simd_width + 16 <= buf.len) {
        const chunk: @Vector(simd_width, u8) = data[i..][0..simd_width].*;
        // Check for chars needing escape: control (<0x20), quote, backslash
        const ctrl_mask = chunk < @as(@Vector(simd_width, u8), @splat(0x20));
        const quote_mask = chunk == @as(@Vector(simd_width, u8), @splat('"'));
        const bslash_mask = chunk == @as(@Vector(simd_width, u8), @splat('\\'));
        const any_ctrl = @reduce(.Or, ctrl_mask);
        const any_quote = @reduce(.Or, quote_mask);
        const any_bslash = @reduce(.Or, bslash_mask);

        if (!any_ctrl and !any_quote and !any_bslash) {
            // Fast path: no escaping needed, bulk copy
            @memcpy(buf[pos..][0..simd_width], data[i..][0..simd_width]);
            pos += simd_width;
            i += simd_width;
        } else {
            // Slow path: at least one char needs escaping, do scalar
            for (data[i..][0..simd_width]) |ch| {
                if (ch == '"' or ch == '\\') {
                    buf[pos] = '\\';
                    pos += 1;
                }
                if (ch >= 0x20) {
                    buf[pos] = ch;
                    pos += 1;
                }
            }
            i += simd_width;
        }
    }

    // Scalar remainder
    while (i < data.len and pos + 2 < buf.len) {
        const ch = data[i];
        if (ch == '"' or ch == '\\') {
            buf[pos] = '\\';
            pos += 1;
        }
        if (ch >= 0x20) {
            buf[pos] = ch;
            pos += 1;
        }
        i += 1;
    }

    return pos;
}

/// Parse Postgres binary int array and write as JSON: [1,2,3]
fn writeIntArrayJson(data: []const u8, oid: i32, buf: []u8) usize {
    // Postgres binary array format:
    // 4 bytes: ndim, 4 bytes: flags, 4 bytes: element OID
    // per dimension: 4 bytes length, 4 bytes lower bound
    // then: per element: 4 bytes length (or -1 for null), then data
    if (data.len < 12) {
        @memcpy(buf[0..2], "[]");
        return 2;
    }

    const ndim = std.mem.readInt(i32, data[0..4], .big);
    if (ndim == 0) {
        @memcpy(buf[0..2], "[]");
        return 2;
    }

    // Element size based on array OID
    const elem_size: usize = switch (oid) {
        1005 => 2, // int2[]
        1007 => 4, // int4[]
        1016 => 8, // int8[]
        else => 4,
    };

    const nelems = std.mem.readInt(i32, data[12..16], .big);
    var pos: usize = 0;
    buf[pos] = '[';
    pos += 1;

    var offset: usize = 20; // skip header (12 + 4 length + 4 lower bound)
    var i: i32 = 0;
    while (i < nelems and offset + 4 <= data.len) : (i += 1) {
        if (i > 0) {
            buf[pos] = ',';
            pos += 1;
        }
        const elem_len = std.mem.readInt(i32, data[offset..][0..4], .big);
        offset += 4;
        if (elem_len == -1) {
            @memcpy(buf[pos..][0..4], "null");
            pos += 4;
        } else if (elem_size == 2 and offset + 2 <= data.len) {
            const v = std.mem.readInt(i16, data[offset..][0..2], .big);
            const s = std.fmt.bufPrint(buf[pos..], "{d}", .{v}) catch break;
            pos += s.len;
            offset += 2;
        } else if (elem_size == 4 and offset + 4 <= data.len) {
            const v = std.mem.readInt(i32, data[offset..][0..4], .big);
            const s = std.fmt.bufPrint(buf[pos..], "{d}", .{v}) catch break;
            pos += s.len;
            offset += 4;
        } else if (elem_size == 8 and offset + 8 <= data.len) {
            const v = std.mem.readInt(i64, data[offset..][0..8], .big);
            const s = std.fmt.bufPrint(buf[pos..], "{d}", .{v}) catch break;
            pos += s.len;
            offset += 8;
        } else {
            offset += @intCast(@as(u32, @bitCast(elem_len)));
        }
    }

    buf[pos] = ']';
    pos += 1;
    return pos;
}

/// Parse Postgres binary text array and write as JSON: ["a","b","c"]
fn writeTextArrayJson(data: []const u8, buf: []u8) usize {
    if (data.len < 12) {
        @memcpy(buf[0..2], "[]");
        return 2;
    }

    const ndim = std.mem.readInt(i32, data[0..4], .big);
    if (ndim == 0) {
        @memcpy(buf[0..2], "[]");
        return 2;
    }

    const nelems = std.mem.readInt(i32, data[12..16], .big);
    var pos: usize = 0;
    buf[pos] = '[';
    pos += 1;

    var offset: usize = 20;
    var i: i32 = 0;
    while (i < nelems and offset + 4 <= data.len) : (i += 1) {
        if (i > 0) {
            buf[pos] = ',';
            pos += 1;
        }
        const elem_len = std.mem.readInt(i32, data[offset..][0..4], .big);
        offset += 4;
        if (elem_len == -1) {
            @memcpy(buf[pos..][0..4], "null");
            pos += 4;
        } else {
            const slen: usize = @intCast(@as(u32, @bitCast(elem_len)));
            if (offset + slen > data.len) break;
            buf[pos] = '"';
            pos += 1;
            for (data[offset..][0..slen]) |ch| {
                if (pos + 2 >= buf.len) break;
                if (ch == '"' or ch == '\\') {
                    buf[pos] = '\\';
                    pos += 1;
                }
                buf[pos] = ch;
                pos += 1;
            }
            buf[pos] = '"';
            pos += 1;
            offset += slen;
        }
    }

    buf[pos] = ']';
    pos += 1;
    return pos;
}

fn isSlice(comptime T: type) ?type {
    switch (@typeInfo(T)) {
        .pointer => |ptr| {
            if (ptr.size != .slice) {
                compileHaltGetError(T);
            }
            return if (ptr.child == u8) null else ptr.child;
        },
        .optional => |opt| return isSlice(opt.child),
        else => return null,
    }
}

fn mapValue(comptime T: type, value: T, allocator: Allocator) !T {
    switch (@typeInfo(T)) {
        .optional => |opt| {
            if (value) |v| {
                return try mapValue(opt.child, v, allocator);
            }
            return null;
        },
        else => {},
    }

    if (T == []u8 or T == []const u8) {
        return try allocator.dupe(u8, value);
    }

    if (std.meta.hasFn(T, "pgzMoveOwner")) {
        return value.pgzMoveOwner(allocator);
    }

    return value;
}

pub fn Mapper(comptime T: type) type {
    return struct {
        result: *Result,
        allocator: ?Allocator,
        column_indexes: [std.meta.fields(T).len]?usize,

        const Self = @This();

        pub fn next(self: *const Self) !?T {
            const row = (try self.result.next()) orelse return null;

            var value: T = undefined;

            const allocator = self.allocator;
            inline for (std.meta.fields(T), self.column_indexes) |field, optional_column_index| {
                @field(value, field.name) = try row.mapColumn(&field, optional_column_index, allocator);
            }
            return value;
        }
    };
}

pub const QueryRow = QueryRowT(.safe);
pub const QueryRowUnsafe = QueryRowT(.unsafe);

pub fn QueryRowT(comptime fail_mode: lib.FailMode) type {
    return struct {
        row: RowT(fail_mode),
        result: *Result,

        const Self = @This();

        pub fn get(self: *const Self, comptime T: type, col: usize) if (fail_mode == .safe) lib.TypeError!T else T {
            return self.row.get(T, col);
        }

        pub fn getCol(self: *const Self, comptime T: type, name: []const u8) if (fail_mode == .safe) lib.TypeError!T else T {
            return self.row.getCol(T, name);
        }

        pub fn iterator(self: *const Self, comptime T: type, col: usize) if (fail_mode == .safe) lib.TypeError!Iterator(T) else IteratorUnsafe(T) {
            return self.row.iterator(T, col);
        }

        pub fn iteratorCol(self: *const Self, comptime T: type, name: []const u8) if (fail_mode == .safe) lib.TypeError!Iterator(T) else IteratorUnsafe(T) {
            return self.row.iteratorCol(T, name);
        }

        pub fn record(self: *const Self, col: usize) RecordT(fail_mode) {
            return self.row.record(col);
        }

        pub fn recordCol(self: *const Self, name: []const u8) if (fail_mode == .safe) lib.TypeError!Record else RecordUnsafe {
            return self.row.recordCol(name);
        }
        pub fn to(self: *const Self, T: type, opts: Row.ToOpts) !T {
            return self.row.to(T, opts);
        }

        pub fn deinit(self: *Self) !void {
            // this is unfortunate
            try self.result.drain();
            self.result.deinit();
        }
    };
}

pub fn Iterator(comptime T: type) type {
    return IteratorT(.safe, T);
}
pub fn IteratorUnsafe(comptime T: type) type {
    return IteratorT(.unsafe, T);
}
pub fn IteratorT(comptime fail_mode: lib.FailMode, comptime T: type) type {
    return struct {
        is_null: bool,
        _len: usize,
        _pos: usize,
        _data: []const u8,
        _decoder: *const fn (data: []const u8) ItemType(),

        fn ItemType() type {
            return switch (@typeInfo(T)) {
                .optional => |opt| opt.child,
                else => T,
            };
        }

        const Self = @This();

        pub fn len(self: Self) usize {
            return self._len;
        }

        fn asNull() Self {
            return .{
                .is_null = true,
                ._len = 0,
                ._pos = 0,
                ._data = &.{},
                ._decoder = struct {
                    fn noop(_: []const u8) ItemType() {
                        unreachable;
                    }
                }.noop,
            };
        }

        // used internally by row.get(Iterator(T))
        fn fromPgzRow(data: []const u8, oid: i32) !Self {
            const TT = switch (@typeInfo(T)) {
                .optional => |opt| opt.child,
                else => T,
            };

            const decoder = switch (TT) {
                u8 => blk: {
                    lib.verifyDecodeType(fail_mode, []u8, &.{types.CharArray.oid.decimal}, oid) catch |err| {
                        if (comptime fail_mode == .unsafe) unreachable;
                        return err;
                    };
                    break :blk &types.Char.decodeKnown;
                },
                i16 => blk: {
                    lib.verifyDecodeType(fail_mode, []i16, &.{types.Int16Array.oid.decimal}, oid) catch |err| {
                        if (comptime fail_mode == .unsafe) unreachable;
                        return err;
                    };
                    break :blk &types.Int16.decodeKnown;
                },
                i32 => blk: {
                    lib.verifyDecodeType(fail_mode, []i32, &.{types.Int32Array.oid.decimal}, oid) catch |err| {
                        if (comptime fail_mode == .unsafe) unreachable;
                        return err;
                    };
                    break :blk &types.Int32.decodeKnown;
                },
                i64 => switch (oid) {
                    types.TimestampArray.oid.decimal => &types.Timestamp.decodeKnown,
                    types.TimestampTzArray.oid.decimal => &types.Timestamp.decodeKnown,
                    types.Int64Array.oid.decimal => &types.Int64.decodeKnown,
                    else => std.debug.panic("{d} oid cannot target i64 iterator", .{oid}),
                },
                f32 => blk: {
                    lib.verifyDecodeType(fail_mode, []f32, &.{types.Float32Array.oid.decimal}, oid) catch |err| {
                        if (comptime fail_mode == .unsafe) unreachable;
                        return err;
                    };
                    break :blk &types.Float32.decodeKnown;
                },
                f64 => switch (oid) {
                    types.Float64Array.oid.decimal => &types.Float64.decodeKnown,
                    types.NumericArray.oid.decimal => &types.Numeric.decodeKnownToFloat,
                    else => std.debug.panic("{d} oid cannot target f64 iterator", .{oid}),
                },
                bool => blk: {
                    lib.verifyDecodeType(fail_mode, []bool, &.{types.BoolArray.oid.decimal}, oid) catch |err| {
                        if (comptime fail_mode == .unsafe) unreachable;
                        return err;
                    };
                    break :blk &types.Bool.decodeKnown;
                },
                []const u8 => switch (oid) {
                    types.JSONBArray.oid.decimal => &types.JSONB.decodeKnown,
                    else => &types.Bytea.decodeKnown,
                },
                []u8 => switch (oid) {
                    types.JSONBArray.oid.decimal => &types.JSONB.decodeKnownMutable,
                    else => &types.Bytea.decodeKnownMutable,
                },
                types.Numeric => blk: {
                    lib.verifyDecodeType(fail_mode, []f64, &.{types.NumericArray.oid.decimal}, oid) catch |err| {
                        if (comptime fail_mode == .unsafe) unreachable;
                        return err;
                    };
                    break :blk &types.Numeric.decodeKnown;
                },
                types.Cidr => blk: {
                    lib.verifyDecodeType(fail_mode, []types.Cidr, &.{ types.CidrArray.oid.decimal, types.CidrArray.inet_oid.decimal }, oid) catch |err| {
                        if (comptime fail_mode == .unsafe) unreachable;
                        return err;
                    };
                    break :blk &types.Cidr.decodeKnown;
                },
                else => switch (@typeInfo(TT)) {
                    .@"enum" => blk: {
                        lib.verifyDecodeType(fail_mode, []const u8, &.{types.StringArray.oid.decimal}, oid) catch |err| {
                            if (comptime fail_mode == .unsafe) unreachable;
                            return err;
                        };
                        break :blk &EnumDecoder(TT).decodeKnown;
                    },
                    else => compileHaltGetError(T),
                },
            };

            if (data.len == 12) {
                // we have an empty array
                return .{
                    .is_null = false,
                    ._len = 0,
                    ._pos = 0,
                    ._data = &[_]u8{},
                    ._decoder = decoder,
                };
            }

            // minimum size for 1 empty array
            lib.assert(data.len >= 20);
            const dimensions = std.mem.readInt(i32, data[0..4], .big);
            lib.assert(dimensions == 1);

            const has_nulls = std.mem.readInt(i32, data[4..8][0..4], .big);
            lib.assert(has_nulls == 0 or @typeInfo(T) == .optional);

            // const oid = std.mem.readInt(i32, data[8..12][0..4], .big);
            const l = std.mem.readInt(i32, data[12..16][0..4], .big);
            // const lower_bound = std.mem.readInt(i32, data[16..20][0..4], .big);

            return .{
                .is_null = false,
                ._len = @intCast(l),
                ._pos = 0,
                ._data = data[20..],
                ._decoder = decoder,
            };
        }

        pub fn pgzMoveOwner(self: Self, allocator: Allocator) !Self {
            return .{
                .is_null = false,
                ._len = self._len,
                ._pos = self._pos,
                ._data = try allocator.dupe(u8, self._data),
                ._decoder = self._decoder,
            };
        }

        // Should only be called if the Iterator was created with row.to(...)
        // or a result mapper AND an explicit allocator was given
        pub fn deinit(self: *const Self, allocator: Allocator) void {
            allocator.free(self._data);
        }

        pub fn next(self: *Self) ?T {
            const pos = self._pos;
            const data = self._data;
            if (pos == data.len) {
                return null;
            }

            // TODO: for fixed length types, we don't need to decode the length
            const len_end = pos + 4;
            const value_len = std.mem.readInt(i32, data[pos..len_end][0..4], .big);

            const data_end = len_end + @as(usize, @intCast(value_len));
            lib.assert(data.len >= data_end);

            self._pos = data_end;
            return self._decoder(data[len_end..data_end]);
        }

        pub fn alloc(self: *const Self, allocator: Allocator) ![]T {
            const into = try allocator.alloc(T, self._len);
            try self.fillAlloc(true, into, allocator);
            return into;
        }

        pub fn fill(self: *const Self, into: []T) void {
            self.fillAlloc(false, into, undefined) catch unreachable;
        }

        fn fillAlloc(self: *const Self, comptime should_dupe: bool, into: []T, allocator: Allocator) !void {
            const data = self._data;
            const decoder = self._decoder;

            var pos: usize = 0;
            const limit = @min(into.len, self._len);
            for (0..limit) |i| {
                // TODO: for fixed length types, we don't need to decode the length
                const len_end = pos + 4;
                const data_len = std.mem.readInt(i32, data[pos..len_end][0..4], .big);

                if ((comptime @typeInfo(T) == .optional) and data_len == -1) {
                    pos = len_end;
                    into[i] = null;
                } else {
                    pos = len_end + @as(usize, @intCast(data_len));
                    if (comptime should_dupe and (T == []u8 or T == []const u8)) {
                        into[i] = try allocator.dupe(u8, decoder(data[len_end..pos]));
                    } else {
                        into[i] = decoder(data[len_end..pos]);
                    }
                }
            }
        }
    };
}

fn EnumDecoder(comptime T: type) type {
    return struct {
        pub fn decodeKnown(data: []const u8) T {
            return std.meta.stringToEnum(T, data).?;
        }
    };
}

fn compileHaltGetError(comptime T: type) noreturn {
    @compileError("cannot get value of type " ++ @typeName(T));
}

pub const Record = RecordT(.safe);
pub const RecordUnsafe = RecordT(.unsafe);

pub fn RecordT(comptime fail_mode: lib.FailMode) type {
    return struct {
        data: []const u8,
        number_of_columns: usize,

        const Self = @This();

        pub fn next(self: *Self, comptime T: type) if (fail_mode == .safe) lib.TypeError!T else T {
            var data = self.data;

            // at least 4 bytes for the type and 4 bytes for the lenght
            lib.assert(data.len >= 8);

            const oid = std.mem.readInt(i32, data[0..4], .big);

            data = data[4..];
            const len = std.mem.readInt(i32, data[0..4], .big);

            const TT = switch (@typeInfo(T)) {
                .optional => |opt| blk: {
                    if (len == -1) return null;
                    break :blk opt.child;
                },
                else => T,
            };

            // end of the data for this "column"
            const end = @as(usize, @intCast(len)) + 4;

            // the rest of the data
            self.data = data[end..];

            // start at 4 to skip the length which we already read
            return getScalar(fail_mode, TT, data[4..end], oid);
        }
    };
}

fn getScalar(comptime fail_mode: lib.FailMode, comptime T: type, data: []const u8, oid: i32) if (fail_mode == .safe) lib.TypeError!T else T {
    switch (T) {
        u8 => return types.Char.decode(fail_mode, data, oid),
        i16 => return types.Int16.decode(fail_mode, data, oid),
        i32 => return types.Int32.decode(fail_mode, data, oid),
        i64 => return types.Int64.decode(fail_mode, data, oid),
        f32 => return types.Float32.decode(fail_mode, data, oid),
        f64 => return types.Float64.decode(fail_mode, data, oid),
        bool => return types.Bool.decode(fail_mode, data, oid),
        []const u8 => return types.Bytea.decode(data, oid),
        []u8 => return @constCast(types.Bytea.decode(data, oid)),
        types.Numeric => return types.Numeric.decode(fail_mode, data, oid),
        types.Cidr => return types.Cidr.decode(fail_mode, data, oid),
        else => switch (@typeInfo(T)) {
            .@"enum" => {
                const str = types.Bytea.decode(data, oid);
                return std.meta.stringToEnum(T, str).?;
            },
            else => compileHaltGetError(T),
        },
    }
}

const t = lib.testing;

test "Result: ints" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select $1::smallint, $2::int, $3::bigint";

    {
        // int max
        var result = try c.query(sql, .{ @as(i16, 32767), @as(i32, 2147483647), @as(i64, 9223372036854775807) });
        defer result.deinit();
        const row = (try result.nextUnsafe()).?;
        try t.expectEqual(32767, row.get(i16, 0));
        try t.expectEqual(2147483647, row.get(i32, 1));
        try t.expectEqual(9223372036854775807, row.get(i64, 2));

        try t.expectEqual(32767, row.get(?i16, 0));
        try t.expectEqual(2147483647, row.get(?i32, 1));
        try t.expectEqual(9223372036854775807, row.get(?i64, 2));

        try t.expectEqual(null, result.next());
    }

    {
        // int min
        var result = try c.query(sql, .{ @as(i16, -32768), @as(i32, -2147483648), @as(i64, -9223372036854775808) });
        defer result.deinit();
        const row = (try result.nextUnsafe()).?;
        try t.expectEqual(-32768, row.get(i16, 0));
        try t.expectEqual(-2147483648, row.get(i32, 1));
        try t.expectEqual(-9223372036854775808, row.get(i64, 2));
        try result.drain();
    }

    {
        // int null
        var result = try c.query(sql, .{ null, null, null });
        defer result.deinit();
        defer result.drain() catch unreachable;
        const row = (try result.nextUnsafe()).?;
        try t.expectEqual(null, row.get(?i16, 0));
        try t.expectEqual(null, row.get(?i32, 1));
        try t.expectEqual(null, row.get(?i64, 2));
    }

    {
        // uint within limit
        var result = try c.query(sql, .{ @as(u16, 32767), @as(u32, 2147483647), @as(u64, 9223372036854775807) });
        defer result.deinit();
        const row = (try result.nextUnsafe()).?;
        try t.expectEqual(32767, row.get(i16, 0));
        try t.expectEqual(2147483647, row.get(i32, 1));
        try t.expectEqual(9223372036854775807, row.get(i64, 2));

        try t.expectEqual(32767, row.get(?i16, 0));
        try t.expectEqual(2147483647, row.get(?i32, 1));
        try t.expectEqual(9223372036854775807, row.get(?i64, 2));
        try result.drain();
    }

    {
        // u16 outside of limit
        try t.expectError(error.IntWontFit, c.query(sql, .{ @as(u16, 32768), @as(u32, 0), @as(u64, 0) }));
        // u32 outside of limit
        try t.expectError(error.IntWontFit, c.query(sql, .{ @as(u16, 0), @as(u32, 2147483648), @as(u64, 0) }));
        // u64 outside of limit
        try t.expectError(error.IntWontFit, c.query(sql, .{ @as(u16, 0), @as(u32, 0), @as(u64, 9223372036854775808) }));
    }
}

test "Result: floats" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select $1::float4, $2::float8";

    {
        // positive float
        var result = try c.query(sql, .{ @as(f32, 1.23456), @as(f64, 1093.229183) });
        defer result.deinit();
        const row = (try result.nextUnsafe()).?;
        try t.expectEqual(1.23456, row.get(f32, 0));
        try t.expectEqual(1093.229183, row.get(f64, 1));

        try t.expectEqual(1.23456, row.get(?f32, 0));
        try t.expectEqual(1093.229183, row.get(?f64, 1));

        try t.expectEqual(null, result.next());
    }

    {
        // negative float
        var result = try c.query(sql, .{ @as(f32, -392.31), @as(f64, -99991.99992) });
        defer result.deinit();
        const row = (try result.nextUnsafe()).?;
        try t.expectEqual(-392.31, row.get(f32, 0));
        try t.expectEqual(-99991.99992, row.get(f64, 1));
        try t.expectEqual(null, result.next());
    }

    {
        // null float
        var result = try c.query(sql, .{ null, null });
        defer result.deinit();
        const row = (try result.nextUnsafe()).?;
        try t.expectEqual(null, row.get(?f32, 0));
        try t.expectEqual(null, row.get(?f64, 1));
        try t.expectEqual(null, result.next());
    }
}

test "Result: bool" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select $1::bool";

    {
        // true
        var result = try c.query(sql, .{true});
        defer result.deinit();
        defer result.drain() catch unreachable;
        const row = (try result.nextUnsafe()).?;
        try t.expectEqual(true, row.get(bool, 0));
        try t.expectEqual(true, row.get(?bool, 0));
        try t.expectEqual(null, result.next());
    }

    {
        // false
        var result = try c.query(sql, .{false});
        defer result.deinit();
        defer result.drain() catch unreachable;
        const row = (try result.nextUnsafe()).?;
        try t.expectEqual(false, row.get(bool, 0));
        try t.expectEqual(false, row.get(?bool, 0));
        try t.expectEqual(null, result.next());
    }

    {
        // null
        var result = try c.query(sql, .{null});
        defer result.deinit();
        defer result.drain() catch unreachable;
        const row = (try result.nextUnsafe()).?;
        try t.expectEqual(null, row.get(?bool, 0));
        try t.expectEqual(null, result.next());
    }
}

test "Result: text and bytea" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select $1::text, $2::bytea";

    {
        // empty
        var result = try c.query(sql, .{ "", "" });
        defer result.deinit();
        const row = (try result.nextUnsafe()).?;
        try t.expectString("", row.get([]u8, 0));
        try t.expectString("", row.get(?[]u8, 0).?);
        try t.expectString("", row.get([]u8, 1));
        try t.expectString("", row.get(?[]u8, 1).?);
        try result.drain();
    }

    {
        // not empty
        var result = try c.query(sql, .{ "it's over 9000!!!", "i will Not fear" });
        defer result.deinit();
        const row = (try result.nextUnsafe()).?;
        try t.expectString("it's over 9000!!!", row.get([]u8, 0));
        try t.expectString("it's over 9000!!!", row.get(?[]const u8, 0).?);
        try t.expectString("i will Not fear", row.get([]const u8, 1));
        try t.expectString("i will Not fear", row.get(?[]u8, 1).?);
        try result.drain();
    }

    {
        // as an array
        var result = try c.query(sql, .{ [_]u8{ 'a', 'c', 'b' }, [_]u8{ 'z', 'z', '3' } });
        defer result.deinit();
        const row = (try result.nextUnsafe()).?;
        try t.expectString("acb", row.get([]const u8, 0));
        try t.expectString("acb", row.get(?[]u8, 0).?);
        try t.expectString("zz3", row.get([]const u8, 1));
        try t.expectString("zz3", row.get(?[]u8, 1).?);
        try result.drain();
    }

    {
        // as a slice
        const s1 = try t.allocator.alloc(u8, 4);
        defer t.allocator.free(s1);
        @memcpy(s1, "Leto");

        var result = try c.query(sql, .{ s1, constString() });
        defer result.deinit();
        const row = (try result.nextUnsafe()).?;
        try t.expectString("Leto", row.get([]u8, 0));
        try t.expectString("Leto", row.get(?[]u8, 0).?);
        try t.expectString("Ghanima", row.get([]u8, 1));
        try t.expectString("Ghanima", row.get(?[]u8, 1).?);
        try result.drain();
    }

    {
        // null
        var result = try c.query(sql, .{ null, null });
        defer result.deinit();
        const row = (try result.nextUnsafe()).?;
        try t.expectEqual(null, row.get(?[]u8, 0));
        try t.expectEqual(null, row.get(?[]u8, 1));
        try result.drain();
    }
}

fn constString() []const u8 {
    return "Ghanima";
}

test "Result: optional" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select $1::int, $2::int";

    {
        // int max
        var result = try c.query(sql, .{ @as(?i32, 321), @as(?i32, null) });
        defer result.deinit();
        const row = (try result.nextUnsafe()).?;
        try t.expectEqual(321, row.get(i32, 0));

        try t.expectEqual(321, row.get(?i32, 0));
        try t.expectEqual(null, row.get(?i32, 1));
        try t.expectEqual(null, result.next());
    }
}

test "Result: iterator" {
    var c = t.connect(.{});
    defer c.deinit();

    {
        // empty row.iterator()
        var result = try c.query("select $1::int[]", .{[_]i32{}});
        defer result.deinit();
        var row = (try result.nextUnsafe()).?;

        var iterator = row.iterator(i32, 0);
        try t.expectEqual(0, iterator.len());

        try t.expectEqual(null, iterator.next());
        try t.expectEqual(null, iterator.next());

        const a = try iterator.alloc(t.allocator);
        try t.expectEqual(0, a.len);
        try result.drain();
    }

    {
        // empty row.get()
        var result = try c.query("select $1::int[]", .{[_]i32{}});
        defer result.deinit();
        var row = (try result.nextUnsafe()).?;

        var iterator = row.get(Iterator(i32), 0);
        try t.expectEqual(0, iterator.len());

        try t.expectEqual(null, iterator.next());
        try t.expectEqual(null, iterator.next());

        const a = try iterator.alloc(t.allocator);
        try t.expectEqual(0, a.len);
        try result.drain();
    }

    {
        // one: row.iterator
        var result = try c.query("select $1::int[]", .{[_]i32{9}});
        defer result.deinit();
        var row = (try result.nextUnsafe()).?;

        var iterator = row.iterator(i32, 0);
        try t.expectEqual(1, iterator.len());

        try t.expectEqual(9, iterator.next());
        try t.expectEqual(null, iterator.next());

        const arr = try iterator.alloc(t.allocator);
        defer t.allocator.free(arr);
        try t.expectEqual(1, arr.len);
        try t.expectSlice(i32, &.{9}, arr);
        try result.drain();
    }

    {
        // one: row.get
        var result = try c.query("select $1::int[]", .{[_]i32{9}});
        defer result.deinit();
        var row = (try result.nextUnsafe()).?;

        var iterator = row.get(Iterator(i32), 0);
        try t.expectEqual(1, iterator.len());

        try t.expectEqual(9, iterator.next());
        try t.expectEqual(null, iterator.next());

        const arr = try iterator.alloc(t.allocator);
        defer t.allocator.free(arr);
        try t.expectEqual(1, arr.len);
        try t.expectSlice(i32, &.{9}, arr);
        try result.drain();
    }

    {
        // fill
        var result = try c.query("select $1::int[]", .{[_]i32{ 0, -19 }});
        defer result.deinit();
        var row = (try result.nextUnsafe()).?;

        var iterator = row.iterator(i32, 0);
        try t.expectEqual(2, iterator.len());

        try t.expectEqual(0, iterator.next());
        try t.expectEqual(-19, iterator.next());
        try t.expectEqual(null, iterator.next());

        var arr1: [2]i32 = undefined;
        iterator.fill(&arr1);
        try t.expectSlice(i32, &.{ 0, -19 }, &arr1);
        try result.drain();

        // smaller
        var arr2: [1]i32 = undefined;
        iterator.fill(&arr2);
        try t.expectSlice(i32, &.{0}, &arr2);
        try result.drain();
    }
}

test "Result: null iterator" {
    var c = t.connect(.{});
    defer c.deinit();

    {
        // null int
        var result = try c.query("select $1::int[]", .{null});
        defer result.deinit();

        var row = (try result.nextUnsafe()).?;

        var iterator = row.iterator(i32, 0);
        try t.expectEqual(true, iterator.is_null);
        try t.expectEqual(null, iterator.next());
        try result.drain();
    }

    {
        // null text
        var result = try c.query("select $1::text[]", .{null});
        defer result.deinit();

        var row = (try result.nextUnsafe()).?;

        var iterator = row.iterator([]u8, 0);
        try t.expectEqual(true, iterator.is_null);
        try t.expectEqual(null, iterator.next());
        try result.drain();
    }
}

test "Result: int[]" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select $1::smallint[], $2::int[], $3::bigint[]";

    var result = try c.query(sql, .{ [_]i16{ -303, 9449, 2 }, [_]i32{ -3003, 49493229, 0 }, [_]i64{ 944949338498392, -2 } });
    defer result.deinit();

    var row = (try result.nextUnsafe()).?;

    const v1 = try row.iterator(i16, 0).alloc(t.allocator);
    defer t.allocator.free(v1);
    try t.expectSlice(i16, &.{ -303, 9449, 2 }, v1);

    const v2 = try row.iterator(i32, 1).alloc(t.allocator);
    defer t.allocator.free(v2);
    try t.expectSlice(i32, &.{ -3003, 49493229, 0 }, v2);

    const v3 = try row.iterator(i64, 2).alloc(t.allocator);
    defer t.allocator.free(v3);
    try t.expectSlice(i64, &.{ 944949338498392, -2 }, v3);
}

test "Result: float[]" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select $1::float4[], $2::float8[]";

    var result = try c.query(sql, .{ [_]f32{ 1.1, 0, -384.2 }, [_]f64{ -888585.123322, 0.001 } });
    defer result.deinit();

    var row = (try result.nextUnsafe()).?;

    const v1 = try row.iterator(f32, 0).alloc(t.allocator);
    defer t.allocator.free(v1);
    try t.expectSlice(f32, &.{ 1.1, 0, -384.2 }, v1);

    const v2 = try row.iterator(f64, 1).alloc(t.allocator);
    defer t.allocator.free(v2);
    try t.expectSlice(f64, &.{ -888585.123322, 0.001 }, v2);
}

test "Result: bool[]" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select $1::bool[]";

    var result = try c.query(sql, .{[_]bool{ true, false, false }});
    defer result.deinit();

    var row = (try result.nextUnsafe()).?;

    const v1 = try row.iterator(bool, 0).alloc(t.allocator);
    defer t.allocator.free(v1);
    try t.expectSlice(bool, &.{ true, false, false }, v1);
}

test "Result: text[] & bytea[]" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select $1::text[], $2::bytea[]";

    var arr1 = [_]u8{ 0, 1, 2 };
    var arr2 = [_]u8{255};
    var result = try c.query(sql, .{ [_][]const u8{ "over", "9000" }, [_][]u8{ &arr1, &arr2 } });
    defer result.deinit();

    var row = (try result.nextUnsafe()).?;

    const v1 = try row.iterator([]u8, 0).alloc(t.allocator);
    defer {
        t.allocator.free(v1[0]);
        t.allocator.free(v1[1]);
        t.allocator.free(v1);
    }
    try t.expectString("over", v1[0]);
    try t.expectString("9000", v1[1]);
    try t.expectEqual(2, v1.len);

    const v2 = try row.iterator([]const u8, 1).alloc(t.allocator);
    defer {
        t.allocator.free(v2[0]);
        t.allocator.free(v2[1]);
        t.allocator.free(v2);
    }
    try t.expectString(&arr1, v2[0]);
    try t.expectString(&arr2, v2[1]);
    try t.expectEqual(2, v2.len);
}

test "Result: text[] alloc dupes" {
    var c = t.connect(.{});
    defer c.deinit();

    var arr1: [][]const u8 = undefined;
    var arr2: [][]const u8 = undefined;
    defer {
        for (arr1) |str| {
            t.allocator.free(str);
        }
        t.allocator.free(arr1);

        for (arr2) |str| {
            t.allocator.free(str);
        }
        t.allocator.free(arr2);
    }

    {
        var row = (try c.rowUnsafe("select array['Leto', 'Test']::text[]", .{})) orelse unreachable;
        defer row.deinit() catch {};
        arr1 = try row.iterator([]const u8, 0).alloc(t.allocator);
    }

    {
        var row = (try c.rowUnsafe("select array['Ghanima', 'Goku']::text[]", .{})) orelse unreachable;
        defer row.deinit() catch {};
        arr2 = try row.iterator([]const u8, 0).alloc(t.allocator);
    }

    try t.expectStringSlice(&.{ "Leto", "Test" }, arr1);
    try t.expectStringSlice(&.{ "Ghanima", "Goku" }, arr2);
}

test "Result: UUID" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select $1::uuid, $2::uuid";
    var result = try c.query(sql, .{ "fcbebf0f-b996-43b9-9818-672bc689cda8", &[_]u8{ 174, 47, 71, 95, 128, 112, 65, 183, 186, 51, 134, 187, 168, 137, 123, 222 } });
    defer result.deinit();

    const row = (try result.nextUnsafe()).?;
    try t.expectSlice(u8, &.{ 252, 190, 191, 15, 185, 150, 67, 185, 152, 24, 103, 43, 198, 137, 205, 168 }, row.get([]u8, 0));
    try t.expectSlice(u8, &.{ 174, 47, 71, 95, 128, 112, 65, 183, 186, 51, 134, 187, 168, 137, 123, 222 }, row.get([]u8, 1));
}

test "Result: lsn" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select $1::pg_lsn + 1";
    var result = try c.query(sql, .{32788447688});
    defer result.deinit();

    const row = (try result.nextUnsafe()).?;
    try t.expectEqual(32788447689, row.get(i64, 0));
}

test "Row: column names" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select 923 as id, 'Leto' as name";
    var row = (try c.rowUnsafeOpts(sql, .{}, .{ .column_names = true })).?;
    defer row.deinit() catch {};

    try t.expectEqual(923, row.getCol(i32, "id"));
    try t.expectString("Leto", row.getCol([]u8, "name"));
}

test "Result: mutable []u8" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select 'Leto'";
    var row = (try c.rowUnsafe(sql, .{})).?;
    defer row.deinit() catch {};

    var name = row.get([]u8, 0);
    name[3] = '!';
    try t.expectString("Let!", name);
}

test "Result: mutable [][]u8" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select array['Leto', 'Test']::text[]";
    var row = (try c.rowUnsafe(sql, .{})).?;
    defer row.deinit() catch {};

    var values = try row.iterator([]u8, 0).alloc(t.allocator);
    defer {
        t.allocator.free(values[0]);
        t.allocator.free(values[1]);
        t.allocator.free(values);
    }
    values[0][0] = 'n';
    try t.expectString("neto", values[0]);
    try t.expectString("Test", values[1]);
}

test "Row.to: ordinal" {
    const User = struct {
        id: i32,
        active: bool,
        name: []const u8,
        note: ?[]const u8,
        choice: Choice,

        const Choice = enum {
            blue,
            green,
            red,
        };
    };

    var c = t.connect(.{});
    defer c.deinit();

    {
        // null, no dupe
        var row = (try c.rowUnsafe("select 1::integer, true, 'teg', null::text, 'blue'", .{})).?;
        defer row.deinit() catch {};

        const user = try row.to(User, .{});
        try t.expectEqual(1, user.id);
        try t.expectEqual(true, user.active);
        try t.expectString("teg", user.name);
        try t.expectEqual(null, user.note);
        try t.expectEqual(.blue, user.choice);
    }

    {
        // not null, no dupe
        var row = (try c.rowUnsafe("select 2::integer, false, 'ghanima', 'n1', 'red'", .{})).?;
        defer row.deinit() catch {};

        const user = try row.to(User, .{});
        try t.expectEqual(2, user.id);
        try t.expectEqual(false, user.active);
        try t.expectString("ghanima", user.name);
        try t.expectString("n1", user.note.?);
        try t.expectEqual(.red, user.choice);
    }

    {
        // null, dupe with internal arena
        var row = (try c.rowUnsafe("select 1::integer, true, 'teg', null::text, 'red'", .{})).?;
        defer row.deinit() catch {};

        const user = try row.to(User, .{ .dupe = true });
        try t.expectEqual(1, user.id);
        try t.expectEqual(true, user.active);
        try t.expectString("teg", user.name);
        try t.expectEqual(null, user.note);
        try t.expectEqual(.red, user.choice);
    }

    {
        // not null, dupe with internal arena
        var row = (try c.rowUnsafe("select 2::integer, false, 'ghanima', 'n1', 'red'", .{})).?;
        const user = try row.to(User, .{ .dupe = true });
        defer row.deinit() catch {};

        try t.expectEqual(2, user.id);
        try t.expectEqual(false, user.active);
        try t.expectString("ghanima", user.name);
        try t.expectString("n1", user.note.?);
        try t.expectEqual(.red, user.choice);
    }

    {
        // null, dupe with explicit allocator
        var row = (try c.rowUnsafe("select 1::integer, true, 'teg', null::text, 'red'", .{})).?;
        const user = try row.to(User, .{ .allocator = t.allocator });
        row.deinit() catch {};

        defer t.allocator.free(user.name);
        try t.expectEqual(1, user.id);
        try t.expectEqual(true, user.active);
        try t.expectString("teg", user.name);
        try t.expectEqual(null, user.note);
        try t.expectEqual(.red, user.choice);
    }

    {
        // not null, dupe with explicit allocator
        var row = (try c.rowUnsafe("select 2::integer, false, 'ghanima', 'n1', 'red'", .{})).?;

        const user = try row.to(User, .{ .allocator = t.allocator });
        row.deinit() catch {};

        defer t.allocator.free(user.name);
        defer t.allocator.free(user.note.?);

        try t.expectEqual(2, user.id);
        try t.expectEqual(false, user.active);
        try t.expectString("ghanima", user.name);
        try t.expectString("n1", user.note.?);
        try t.expectEqual(.red, user.choice);
    }
}

test "Row.to: name no map" {
    const User = struct {
        id: i32 = 9876,
        active: bool,
        name: []const u8,
        note: ?[]const u8 = null,
    };

    var c = t.connect(.{});
    defer c.deinit();

    {
        // null, no dupe
        var row = (try c.rowUnsafeOpts("select 1 as id, true as active, 'teg' as name, null as note", .{}, .{ .column_names = true })).?;
        defer row.deinit() catch {};

        const user = try row.to(User, .{ .map = .name });
        try t.expectEqual(1, user.id);
        try t.expectEqual(true, user.active);
        try t.expectString("teg", user.name);
        try t.expectEqual(null, user.note);
    }

    {
        // default values are used if no colum
        // and extra columns are ignored
        var row = (try c.rowUnsafeOpts("select 2 as id, false as active, 'ghanima' as name, 'x123' as other", .{}, .{ .column_names = true })).?;
        defer row.deinit() catch {};

        const user = try row.to(User, .{ .map = .name });
        try t.expectEqual(2, user.id);
        try t.expectEqual(false, user.active);
        try t.expectString("ghanima", user.name);
        try t.expectEqual(null, user.note);
    }

    {
        // nullable fields are nulled if no column
        // and extra columns are ignored
        var row = (try c.rowUnsafeOpts("select false as active, 'ghanima' as name, 'x123' as other", .{}, .{ .column_names = true })).?;
        defer row.deinit() catch {};

        const user = try row.to(User, .{ .map = .name });
        try t.expectEqual(9876, user.id);
        try t.expectEqual(false, user.active);
        try t.expectString("ghanima", user.name);
        try t.expectEqual(null, user.note);
    }

    {
        // error on missing column with non-default value
        var row = (try c.rowUnsafeOpts("select 1 as id", .{}, .{ .column_names = true })).?;
        defer row.deinit() catch {};

        try t.expectError(error.FieldColumnMismatch, row.to(User, .{ .map = .name }));
    }

    {
        // not null, no dupe
        var row = (try c.rowUnsafeOpts("select 2::integer as id, false as active, 'ghanima' as name, 'n1' as note", .{}, .{ .column_names = true })).?;
        defer row.deinit() catch {};

        const user = try row.to(User, .{ .map = .name });
        try t.expectEqual(2, user.id);
        try t.expectEqual(false, user.active);
        try t.expectString("ghanima", user.name);
        try t.expectString("n1", user.note.?);
    }

    {
        // null, dupe with internal arena
        var row = (try c.rowUnsafeOpts("select 1::integer as id, true as active, 'teg' as name, null::text as note", .{}, .{ .column_names = true })).?;
        defer row.deinit() catch {};

        const user = try row.to(User, .{ .dupe = true, .map = .name });
        try t.expectEqual(1, user.id);
        try t.expectEqual(true, user.active);
        try t.expectString("teg", user.name);
        try t.expectEqual(null, user.note);
    }

    {
        // not null, dupe with internal arena
        var row = (try c.rowUnsafeOpts("select 2::integer as id, false as active, 'ghanima' as name, 'n1' as note", .{}, .{ .column_names = true })).?;
        defer row.deinit() catch {};

        const user = try row.to(User, .{ .dupe = true, .map = .name });
        try t.expectEqual(2, user.id);
        try t.expectEqual(false, user.active);
        try t.expectString("ghanima", user.name);
        try t.expectString("n1", user.note.?);
    }

    {
        // null, dupe with explicit allocator
        var row = (try c.rowUnsafeOpts("select 1::integer as id, true as active, 'teg' as name, null::text as note", .{}, .{ .column_names = true })).?;
        defer row.deinit() catch {};

        const user = try row.to(User, .{ .allocator = t.allocator, .map = .name });
        defer t.allocator.free(user.name);
        try t.expectEqual(1, user.id);
        try t.expectEqual(true, user.active);
        try t.expectString("teg", user.name);
        try t.expectEqual(null, user.note);
    }

    {
        // not null, dupe with explicit allocator
        var row = (try c.rowUnsafeOpts("select 5::integer as id, false as active, 'ghanima' as name, 'n1' as note", .{}, .{ .column_names = true })).?;
        defer row.deinit() catch {};

        const user = try row.to(User, .{ .allocator = t.allocator, .map = .name });
        defer t.allocator.free(user.name);
        defer t.allocator.free(user.note.?);

        try t.expectEqual(5, user.id);
        try t.expectEqual(false, user.active);
        try t.expectString("ghanima", user.name);
        try t.expectString("n1", user.note.?);
    }
}

test "Result.Mapper" {
    var c = t.connect(.{});
    defer c.deinit();

    {
        // mapper with missing column and non-default field
        var result = try c.queryOpts("select 1", .{}, .{ .column_names = true });
        defer result.deinit();
        const mapper = result.mapper(struct { id: i32 }, .{});
        try t.expectError(error.FieldColumnMismatch, mapper.next());
        try result.drain();
    }

    // null, no dupe
    try expectResultMapper(&c, "select 1 as id, true as active, 'teg' as name, null as note", .{
        .id = 1,
        .active = true,
        .name = "teg",
        .note = null,
    }, .{});

    // default values are used if no colum
    // and extra columns are ignored
    try expectResultMapper(&c, "select 2 as id, false as active, 'ghanima' as name, 'x123' as other", .{
        .id = 2,
        .active = false,
        .name = "ghanima",
        .note = null,
    }, .{});

    // nullable fields are nulled if no column
    // and extra columns are ignored
    try expectResultMapper(&c, "select false as active, 'ghanima' as name, 'x123' as other", .{
        .id = 9876,
        .active = false,
        .name = "ghanima",
        .note = null,
    }, .{});

    // not null, no dupe
    try expectResultMapper(&c, "select 2::integer as id, false as active, 'ghanima' as name, 'n1' as note", .{
        .id = 2,
        .active = false,
        .name = "ghanima",
        .note = "n1",
    }, .{});

    // null, dupe with internal arena
    try expectResultMapper(&c, "select 1::integer as id, true as active, 'teg' as name, null::text as note", .{
        .id = 1,
        .active = true,
        .name = "teg",
        .note = null,
    }, .{ .dupe = true });

    // not null, dupe with internal arena
    try expectResultMapper(&c, "select 3::integer as id, false as active, 'ghanima' as name, 'n1' as note", .{
        .id = 3,
        .active = false,
        .name = "ghanima",
        .note = "n1",
    }, .{ .dupe = true });

    // null, dupe with explicit allocator
    try expectResultMapper(&c, "select 4::integer as id, true as active, 'teg' as name, null::text as note", .{
        .id = 4,
        .active = true,
        .name = "teg",
        .note = null,
    }, .{ .allocator = t.allocator });

    // not null, dupe with explicit allocator
    try expectResultMapper(&c, "select 5::integer as id, false as active, 'ghanima' as name, 'n1' as note", .{
        .id = 5,
        .active = false,
        .name = "ghanima",
        .note = "n1",
    }, .{ .allocator = t.allocator });
}

test "Row.to: iterator" {
    const User = struct {
        parents: Iterator(i32),
        tags: ?Iterator([]const u8),
    };

    defer t.reset();
    var c = t.connect(.{});
    defer c.deinit();

    {
        var row = (try c.rowUnsafe("select array[1, 99]::integer[], null", .{})).?;
        defer row.deinit() catch {};

        const user = try row.to(User, .{});
        try t.expectSlice(i32, &.{ 1, 99 }, try user.parents.alloc(t.arena.allocator()));
        try t.expectEqual(null, user.tags);
    }

    {
        var row = (try c.rowUnsafe("select array[0]::integer[], array['over', '9000']::text[]", .{})).?;
        const user = try row.to(User, .{ .allocator = t.allocator });
        row.deinit() catch {};

        defer user.parents.deinit(t.allocator);
        defer user.tags.?.deinit(t.allocator);

        try t.expectSlice(i32, &.{0}, try user.parents.alloc(t.arena.allocator()));
        try t.expectStringSlice(&.{ "over", "9000" }, try user.tags.?.alloc(t.arena.allocator()));
    }

    {
        // dupe with result arena
        var result = try c.query(
            \\ select array[0]::integer[], array['over']::text[]
            \\ union all
            \\ select array[1]::integer[], array['9000']::text[]
        , .{});

        const user1 = try (try result.nextUnsafe()).?.to(User, .{ .dupe = true });
        const user2 = try (try result.nextUnsafe()).?.to(User, .{ .dupe = true });
        try t.expectEqual(null, try result.nextUnsafe());
        defer result.deinit();

        try t.expectSlice(i32, &.{0}, try user1.parents.alloc(t.arena.allocator()));
        try t.expectStringSlice(&.{"over"}, try user1.tags.?.alloc(t.arena.allocator()));

        try t.expectSlice(i32, &.{1}, try user2.parents.alloc(t.arena.allocator()));
        try t.expectStringSlice(&.{"9000"}, try user2.tags.?.alloc(t.arena.allocator()));
    }

    {
        // dupe with explicit arena
        var result = try c.query(
            \\ select array[0]::integer[], array['over']::text[]
            \\ union all
            \\ select array[1]::integer[], array['9000']::text[]
        , .{});

        const user1 = try (try result.nextUnsafe()).?.to(User, .{ .allocator = t.allocator });
        const user2 = try (try result.nextUnsafe()).?.to(User, .{ .allocator = t.allocator });
        try t.expectEqual(null, try result.nextUnsafe());
        result.deinit();

        defer user1.tags.?.deinit(t.allocator);
        defer user1.parents.deinit(t.allocator);
        defer user2.tags.?.deinit(t.allocator);
        defer user2.parents.deinit(t.allocator);

        try t.expectSlice(i32, &.{0}, try user1.parents.alloc(t.arena.allocator()));
        try t.expectStringSlice(&.{"over"}, try user1.tags.?.alloc(t.arena.allocator()));

        try t.expectSlice(i32, &.{1}, try user2.parents.alloc(t.arena.allocator()));
        try t.expectStringSlice(&.{"9000"}, try user2.tags.?.alloc(t.arena.allocator()));
    }
}

test "Row.to: array" {
    const User = struct {
        parents: []i32,
        tags: ?[][]const u8,
        choices: ?[]Choice,

        const Choice = enum {
            red,
            blue,
            green,
        };
    };

    defer t.reset();
    var c = t.connect(.{});
    defer c.deinit();

    {
        var row = (try c.rowUnsafe("select array[1, 99]::integer[], array['over', '9000']::text[], array['red', 'green']::text[]", .{})).?;
        const user = try row.to(User, .{ .allocator = t.allocator });
        row.deinit() catch {};

        defer {
            t.allocator.free(user.tags.?[0]);
            t.allocator.free(user.tags.?[1]);
            t.allocator.free(user.tags.?);
            t.allocator.free(user.parents);
            t.allocator.free(user.choices.?);
        }
        try t.expectSlice(i32, &.{ 1, 99 }, user.parents);
        try t.expectStringSlice(&.{ "over", "9000" }, user.tags.?);
        try t.expectSlice(User.Choice, &.{ .red, .green }, user.choices.?);
    }

    {
        var row = (try c.rowUnsafe("select array[1, 99]::integer[], null::text[], null::text[]", .{})).?;
        const user = try row.to(User, .{ .allocator = t.allocator });
        row.deinit() catch {};

        defer {
            t.allocator.free(user.parents);
        }
        try t.expectSlice(i32, &.{ 1, 99 }, user.parents);
        try t.expectEqual(null, user.tags);
        try t.expectEqual(null, user.choices);
    }
}

test "Result: safe" {
    var c = t.connect(.{});
    defer c.deinit();
    const sql = "select $1::int, $2::int";

    {
        var result = try c.query(sql, .{ @as(?i32, 321), @as(?i32, null) });
        defer result.deinit();
        const row = (try result.next()).?;
        try t.expectEqual(321, try row.get(i32, 0));
        try t.expectEqual(error.InvalidType, row.get(bool, 0));

        try t.expectEqual(321, try row.get(?i32, 0));
        try t.expectEqual(null, try row.get(?i32, 1));
        try t.expectEqual(null, result.next());
    }
}

fn expectResultMapper(conn: *Conn, sql: []const u8, expected: anytype, opts: Result.MapperOpts) !void {
    const User = struct {
        id: i32 = 9876,
        active: bool,
        name: []const u8,
        note: ?[]const u8 = null,
    };

    var result = try conn.queryOpts(sql, .{}, .{ .column_names = true });
    defer result.deinit();
    var mapper = result.mapper(User, opts);

    const user = (try mapper.next()) orelse unreachable;
    try t.expectEqual(expected.id, user.id);
    try t.expectEqual(expected.active, user.active);
    try t.expectString(expected.name, user.name);
    if (opts.allocator) |a| {
        a.free(user.name);
    }
    if (@TypeOf(expected.note) == @TypeOf(null)) {
        try t.expectEqual(null, user.note);
    } else {
        try t.expectString(expected.note, user.note.?);
        if (opts.allocator) |a| {
            a.free(user.note.?);
        }
    }

    try t.expectEqual(null, mapper.next());
}
