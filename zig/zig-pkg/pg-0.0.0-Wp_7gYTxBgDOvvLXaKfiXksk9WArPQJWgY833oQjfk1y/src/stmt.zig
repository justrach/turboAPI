const std = @import("std");
const lib = @import("lib.zig");
const Buffer = @import("buffer").Buffer;

const types = lib.types;
const Conn = lib.Conn;
const Result = lib.Result;
const Allocator = std.mem.Allocator;
const ArenaAllocator = std.heap.ArenaAllocator;

pub const Stmt = struct {
    buf: *Buffer,

    opts: Conn.QueryOpts,

    conn: *Conn,
    // Executing a stmt may or may not require allocations. It depends on the
    // number of columns, number of parameters, size of the SQL, size of the
    // serialized values and our configuration (e.g. how big
    // our write buffer is).
    arena: *ArenaAllocator,

    // Every call to stmt.bind increments this value. Important because the Bind
    // message contains all the parameter meta data first, then the serialized
    // values. So when we bind a parameter, we need to jump around our buf payload
    // based on the param_index * $some_offset.
    param_index: u16,

    // Number of parameters in the query.
    param_count: u16,

    // Offset of the current Bind message inside the write buffer so we can
    // patch its length without scanning arbitrary payload bytes.
    bind_start: usize,

    // The type of each parameter, which postgresql tells us after we send it the
    // SQL and ask for a description. `param_oids.len` can be greater than
    // `param_count` because we initially use the conn._param_oids which is
    // globally configured.
    param_oids: []i32,

    // Number of colums in the result
    column_count: u16,

    // Information about the colums in the result, which postgresql tells us after
    // we send it the SQL and ask for a description. The slices in this structure
    // can be larger than `column_count` because we initially conn._result_state
    // which is globally configured.
    result_state: Result.State,

    // Name of the prepared statement. Empty == unnamed, so it won't be cached
    // by the server
    name: []const u8,

    pub fn init(conn: *Conn, opts: Conn.QueryOpts) !Stmt {
        const base_allocator = opts.allocator orelse conn._allocator;
        const arena = try base_allocator.create(ArenaAllocator);
        arena.* = ArenaAllocator.init(base_allocator);

        return .{
            .conn = conn,
            .opts = opts,
            .buf = &conn._buf,
            .arena = arena,
            .param_index = 0,
            .param_count = 0,
            .bind_start = 0,
            .param_oids = conn._param_oids,
            .column_count = 0,
            .result_state = conn._result_state,
            .name = opts.cache_name orelse "",
        };
    }

    pub fn fromDescribe(conn: *Conn, describe: *Describe, opts: Conn.QueryOpts) !Stmt {
        const base_allocator = opts.allocator orelse conn._allocator;
        const arena = try base_allocator.create(ArenaAllocator);
        arena.* = ArenaAllocator.init(base_allocator);

        return .{
            .conn = conn,
            .opts = opts,
            .buf = &conn._buf,
            .arena = arena,
            .param_index = 0,
            .param_count = @intCast(describe.param_oids.len),
            .bind_start = 0,
            .param_oids = describe.param_oids,
            .column_count = @intCast(describe.result_state.oids.len),
            .result_state = describe.result_state,
            .name = opts.cache_name.?,
        };
    }

    // Should only be called in an error case. In a normal case, where
    // stmt.execute() returns a result, stmt.deinit() must not be called (all
    // ownership is passed to the result).
    pub fn deinit(self: *Stmt) void {
        self.conn._reader.endFlow() catch {
            // this can only fail in extreme conditions (OOM) and it will only impact
            // the next query (and if the app is using the pool, the pool will try to
            // recover from this anyways)
            self.conn._state = .fail;
        };

        const arena = self.arena;
        const allocator = arena.child_allocator;
        arena.deinit();
        allocator.destroy(arena);
    }

    // When describe_allocator != null, we intend to cache the query information
    // (in conn.__prepared_statements).
    pub fn prepare(self: *Stmt, sql: []const u8, describe_allocator: ?Allocator) !void {
        var conn = self.conn;
        const opts = &self.opts;
        const statement_arena = self.arena.allocator();

        try conn._reader.startFlow(statement_arena, opts.timeout);

        var buf = self.buf;
        buf.reset();

        const name = self.name;

        // This function will issue 3 commands: Parse, Describe, Sync
        // We need the response from describe to put together our Bind message.
        // Specifically, describe will tell us the type of the return columns, and
        // in Bind, we tell the server how we want it to encode each column (text
        // or binary) and to do that, we need to know what they are.
        {
            // Build the payload from our 3 commands

            // We can calculate exactly how many bytes our 3 messages are going to be
            // and make sure our buffer is big enough, thus avoiding some unecessary
            // bound checking
            const bind_payload_len = 8 + sql.len + name.len;
            const describe_payload_len = 6 + name.len;
            const sync_payload_len = 4;

            // the +3 for the initial byte message for each of the 3 messages
            const total_length = 3 + bind_payload_len + describe_payload_len + sync_payload_len;

            try buf.ensureTotalCapacity(total_length);
            var view = buf.skip(total_length) catch unreachable;

            // PARSE
            view.writeByte('P');
            view.writeIntBig(u32, @intCast(bind_payload_len));
            view.write(name);
            view.writeByte(0);
            view.write(sql);
            // null terminate sql string, and we'll be specifying 0 parameter types
            view.write(&.{ 0, 0, 0 });

            // DESCRIBE
            view.writeByte('D');
            view.writeIntBig(u32, @intCast(describe_payload_len));
            view.writeByte('S'); // Describe a prepared statement
            view.write(name);
            view.writeByte(0); // null terminate our name

            // SYNC
            view.write(&.{ 'S', 0, 0, 0, 4 });
            try conn.write(buf.string());
        }

        // no longer idle, we're now in a query
        conn._state = .query;

        // First message we expect back is a ParseComplete, which has no data.
        {
            // If Parse fails, then the server won't reply to our other messages
            // (i.e. Describe) and it'l immediately send a ReadyForQuery.
            const msg = conn.read() catch |err| {
                conn.readyForQuery() catch {};
                return err;
            };

            if (msg.type != '1') {
                return conn.unexpectedDBMessage();
            }
        }

        var param_count: u16 = 0;

        {
            // we expect a ParameterDescription message
            const msg = try conn.read();
            if (msg.type != 't') {
                return conn.unexpectedDBMessage();
            }

            var param_oids = self.param_oids;
            const data = msg.data;
            param_count = std.mem.readInt(u16, data[0..2], .big);
            if (describe_allocator) |da| {
                // If we plan on caching this prepared statement, then we need
                // to allocate a new param_oids list which will outlive this
                // statement
                param_oids = try da.alloc(i32, param_count);
                self.param_oids = param_oids;
            } else if (param_count > param_oids.len) {
                lib.metrics.allocParams(param_count);
                param_oids = try statement_arena.alloc(i32, param_count);
                self.param_oids = param_oids;
            }

            var pos: usize = 2;
            for (0..param_count) |i| {
                const end = pos + 4;
                param_oids[i] = std.mem.readInt(i32, data[pos..end][0..4], .big);
                pos = end;
            }
            self.param_count = param_count;
        }

        {
            // We now expect an answer to our describe message.
            // This is either going to be a RowDescription, or a NoData. NoData means
            // our statement doesn't return any data. Either way, we're going to use
            // this information when we generate our Bind message, next.
            const msg = try conn.read();
            switch (msg.type) {
                'n' => {}, // no data, column_count = 0
                'T' => {
                    var state = self.result_state;
                    const data = msg.data;
                    const column_count = std.mem.readInt(u16, data[0..2], .big);
                    if (describe_allocator) |da| {
                        // If we plan on caching this prepared statement, then we need
                        // to allocate a new param_oids list which will outlive this
                        // statement
                        state = try Result.State.init(da, column_count);
                        self.result_state = state;
                    } else if (column_count > state.oids.len) {
                        lib.metrics.allocColumns(column_count);
                        // we have more columns than our self._result_state can handle, we
                        // need to create a new Result.State specifically for this
                        state = try Result.State.init(statement_arena, column_count);
                        self.result_state = state;
                    }
                    const a: ?Allocator = if (opts.column_names) (describe_allocator orelse statement_arena) else null;
                    try state.from(column_count, data, a);
                    self.column_count = column_count;
                },
                else => return conn.unexpectedDBMessage(),
            }
        }

        return self.prepareForBind(param_count);
    }

    // We need to call Bind for every value we're binding. Rather than having
    // to check "is this the first call to bind" each time, we make it the caller's
    // responsibility to "prepareForBind" upfront.
    pub fn prepareForBind(self: *Stmt, param_count: u16) !void {
        try self.conn.readyForQuery();

        var buf = self.buf;
        buf.resetRetainingCapacity();
        try self.startBindMessage(param_count);
    }

    pub fn startBindMessage(self: *Stmt, param_count: u16) !void {
        self.param_index = 0;

        var buf = self.buf;
        const name = self.name;
        self.bind_start = buf.len();

        // Bind command = 'B'
        // 4 byte length placeholder - 0, 0, 0, 0
        // portal name (empty string, length 0) - 0
        // prepared statement name + null terminator
        // parameter format count + parameter formats + value count
        const bind_prefix_len = 1 + 4 + 1 + name.len + 1 + 2 + (param_count * 2) + 2;
        try buf.ensureUnusedCapacity(bind_prefix_len);

        // We reserved the fixed-size prefix above, so these append operations can
        // skip their own bounds checks.
        buf.writeAssumeCapacity(&.{ 'B', 0, 0, 0, 0, 0 });

        buf.writeAssumeCapacity(name);
        buf.writeByteAssumeCapacity(0);

        // number of parameters types we're sending a
        try buf.writeIntBig(u16, param_count);

        // the format (text or binary) of each parameter. We'll default to text
        // for now, and fill this in as we get the data
        try buf.writeByteNTimes(0, param_count * 2);

        // number of parameters we're sending a
        try buf.writeIntBig(u16, param_count);
    }

    pub fn bind(self: *Stmt, value: anytype) !void {
        const name = self.name;

        const param_index = self.param_index;
        lib.assert(param_index < self.param_count);

        // We tell PostgreSQL the format (text or binary) of each parameter. This
        // information is at the start of the message, always starts at byte 9
        // and each value is 2 bytes.
        const format_offset = self.bind_start + 9 + (param_index * 2) + name.len;

        try types.bindValue(@TypeOf(value), self.param_oids[param_index], value, self.buf, format_offset);
        self.param_index = param_index + 1;
    }

    pub fn bindDynamic(self: *Stmt, value: types.DynamicValue) !void {
        const name = self.name;

        const param_index = self.param_index;
        lib.assert(param_index < self.param_count);

        const format_offset = self.bind_start + 9 + (param_index * 2) + name.len;

        try types.bindDynamicValue(self.param_oids[param_index], value, self.buf, format_offset);
        self.param_index = param_index + 1;
    }

    pub fn finishExecuteMessage(self: *Stmt, append_sync: bool) !void {
        lib.assert(self.param_index == self.param_count);

        const buf = self.buf;

        try lib.types.resultEncoding(self.result_state.oids[0..self.column_count], buf);
        const bind_end = buf.len();
        var bind_len: [4]u8 = undefined;
        std.mem.writeInt(u32, &bind_len, @intCast(bind_end - self.bind_start - 1), .big);
        @memcpy(buf.buf[self.bind_start + 1 .. self.bind_start + 5], &bind_len);

        try buf.write(&.{
            'E',
            0,
            0,
            0,
            9,
            0,
            0,
            0,
            0,
            0,
        });
        if (append_sync) {
            try buf.write(&.{ 'S', 0, 0, 0, 4 });
        }
    }

    pub fn execute(self: *Stmt) !*Result {
        const buf = self.buf;
        const conn = self.conn;

        try self.finishExecuteMessage(true);

        try conn.write(buf.string());

        {
            const msg = conn.read() catch |err| {
                conn.readyForQuery() catch {};
                return err;
            };
            if (msg.type != '2') {
                // expecting a BindComplete
                return conn.unexpectedDBMessage();
            }
        }

        try conn.peekForError();

        // our call to readyForQuery above changed the state, but as far as we're
        // concerned, we're still doing the query.
        conn._state = .query;

        lib.metrics.query();

        const opts = &self.opts;
        const state = self.result_state;
        const column_count = self.column_count;

        const arena = self.arena;

        // Put result on the heap largely for the QueryRow (created via the
        // conn.row(...) helper). This allows QueryRow.result and QueryRow.row._result
        // to reference the result, which isn't otherwise owned.
        const result = try arena.allocator().create(Result);
        result.* = .{
            ._conn = conn,
            ._arena = self.arena,
            ._release_conn = opts.release_conn,
            ._oids = state.oids[0..column_count],
            ._values = state.values[0..column_count],
            .column_names = if (opts.column_names) state.names[0..column_count] else &[_][]const u8{},
            .number_of_columns = column_count,
        };
        return result;
    }

    pub const Describe = struct {
        param_oids: []i32,
        arena: ArenaAllocator,
        result_state: Result.State,
    };
};
