# Native PostgreSQL driver for Zig

A native PostgresSQL driver / client for Zig. Supports [LISTEN](#listen--notify).

See or run [example/main.zig](https://github.com/karlseguin/pg.zig/blob/master/example/main.zig) for a number of examples.

## Install
1) Add pg.zig as a dependency in your `build.zig.zon`:

```bash
zig fetch --save git+https://github.com/karlseguin/pg.zig#master
```

2) In your `build.zig`, add the `pg` module as a dependency to your program:

```zig
const pg_module = b.dependency("pg", .{}).module("pg");

// the executable from your executable/library
const exe = b.addExecutable(.{
  .name = "example",
  ...
  .imports = &.{
    .{ .name = "pg", .module = pg_module },
  },
});
```

## Example
```zig
var pool = try pg.Pool.init(allocator, .{
  .size = 5,
  .connect = .{
    .port = 5432,
    .host = "127.0.0.1",
  },
  .auth = .{
    .username = "postgres",
    .database = "postgres",
    .password = "postgres",
    .timeout = 10_000,
  }
});
defer pool.deinit();

var result = try pool.query("select id, name from users where power > $1", .{9000});
defer result.deinit();

while (try result.next()) |row| {
  const id = try row.get(i32, 0);
  // this is only valid until the next call to next(), deinit() or drain()
  const name = try row.get([]u8, 1);
}
```

## Pool
The pool keeps a configured number of database connection open. The `acquire()` method is used to retrieve a connection from the pool. The pool may start one background thread to attempt to reconnect disconnected connections (or connections which are in an invalid state).

### init(allocator: std.mem.allocator, opts: Opts) !*Pool
Initializes a connection pool. Pool options are:

* `size` - Number of connections to maintain. Defaults to `10`.
* `auth`: - See [Conn.auth](#authopts-opts-void)
* `connect`: - See the [Conn.open](#openallocator-stdmemallocator-opts-opts-conn).
* `timeout`: - The amount of time, in milliseconds, to wait for a connection to be available when `acquire()` is called.
* `connect_on_init_count`:  - The # of connections in the pool to eagerly connect during `init`. Defaults to `null` which will initiliaze all connections (`size`). The background reconnector is used to setup the remaining (`size - connect_on_init_count`) connections. This can be set to `0`, to prevent `init` from failing except in extreme cases (i.e. OOM), but that will hide any configuration/connection issue until the first query is executed.

### initUri(allocator: std.mem.Allocator, uri: std.Uri, opts: Opts) !*Pool
Initializes a connection pool using a std.Uri. When using this function, the `auth` and `connect` fields of `opts` should **not** be set, as these will automatically set based on the provided `uri`.

```zig
const uri = try std.Uri.parse("postgresql://username:password@localhost:5432/database_name");
const pool = try pg.Pool.initUri(allocator, uri, 5, 10_000);
defer pool.deinit();
```

### acquire() !\*Conn
Returns a [\*Conn](#conn) for the connection pool. Returns an `error.Timeout` if the connection cannot be acquired (i.e. if the pool remains empty) for the  `timeout` configuration passed to `init`.


```zig
const conn = try pool.acquire();
defer pool.release(conn);
_ = try conn.exec("...", .{...});
```

### release(conn: \*Conn) void
Releases the conection back into the pool. Calling `pool.release(conn)` is the same as calling `conn.release()`.

### newListener() !Listener
Returns a new [Listener](#listen--notify). This function creates a new connection, it does not use/acquire a connection from the pool. It is a convenience function for cases which have already setup a pool (with the connection and authentication configuration) and want to create a listening connection using those settings.

### exec / query / queryOpts / row / rowOpts
For single-query operations, the pool offers wrappers around the connection's `exec`, `query`, `queryOpts`, `row` and `rowOpts` methods. These are convenience methods. 

`pool.exec` acquires, executes and releases the connection.

`pool.query` and `pool.queryOpts` acquire and execute the query. The connection is automatically returned to the pool when `result.deinit()` is called. Note that this is a special behavior of `pool.query`. When the result comes explicitly from a `conn.query`, `result.deinit()` does not automatically release the connection back into the pool.

`pool.row` and `pool.rowOpts` acquire and execute the query. The connection is automatically returned to the pool when `row.deinit()` is called. Note that this is a special behavior of `pool.row`. When the result comes explicitly from a `conn.row`, `row.deinit()` does not automatically release the connection back into the pool.

## Conn

### open(allocator: std.mem.Allocator, opts: Opts) !Conn
Opens a connection, or returns an error. Prefer creating connections through the pool. Connection options are:

* `host` - Defaults to `"127.0.0.1"`
* `port` - Defaults to `5432`
* `write_buffer` - Size of the write buffer, used when sending messages to the server. Will temporarily allocate more space as needed. If you're writing large SQL or have large parameters (e.g. long text values), making this larger might improve performance a little. Defaults to `2048`, cannot be less than `128`.
* `read_buffer` - Size of the read buffer, used when reading data from the server. Will temporarily allocate more space as needed. Given most apps are going to be reading rows of data, this can have large impact on performance. Defaults to `4096`.
* `result_state_size` - Each `Result` (retrieved via a call to `query`) carries metadata about the data (e.g. the type of each column). For results with less than or equal to `result_state_size` columns, a static `state` container is used. Queries with more columns require a dynamic allocation. Defaults to `32`. 

### deinit(conn: \*Conn) void
Closes the connection and releases its resources. This method should not be used when the connection comes from the pool.

### auth(opts: Opts) !void
Authentications the request. Prefer creating connections through the pool. Auth options are:

* `username`: Defaults to `"postgres"`
* `password`: Defaults to `null`
* `database`: Defaults to `null`
* `timeout` : Defaults to `10_000` (milliseconds)
* `application_name`: Defaults to `null`
* `params`: Defaults to `null`. An `std.StringHashMap([]const u8)`

### release(conn: \*Conn) void
Releases the connection back to the pool. The pool might decide to close the connection and open a new one.

### exec(sql: []const u8, args: anytype) !?usize
Executes the query with arguments, returns the number of rows affected, or null. Should not be used with a query that returns rows.

### query(sql: []const u8, args: anytype) !Result
Executes the query with arguments, returns [Result](#result). `deinit`, and possibly `drain`, must be called on the returned `result`.

### queryOpts(sql: []const u8, args: anytype, opts: Conn.QueryOpts) !Result
Same as `query` but takes options:

- `timeout: ?u32` - This is not reliable and should probably not be used. Currently it simply puts a recv socket timeout. On timeout, the connection will likely no longer be valid (which the pool will detect and handle when the connection is released) and the underlying query will likely still execute. Defaults to `null`.
- `column_names: bool` - Whether or not the `result.column_names` should be populated. When true, this requires memory allocation (duping the column names). Defaults to `false` unless the `column_names` build option was set to true.
- `allocator` - The allocator to use for any allocations needed when executing the query and reading the results. When `null` this will default to the connection's allocator. If you were executing a query in a web-request and each web-request had its own arena tied to the lifetime of the request, it might make sense to use that arena. Defaults to `null`.
- `release_conn: bool` - Whether or not to call `conn.release()` when `result.deinit()` is called. Useful for writing a function that acquires a connection from a `Pool` and returns a `Result`. When `query` or `row` are called from a `Pool` this is forced to `true`. Otherwise, defaults to `false`. 

### row(sql: []const u8, args: anytype) !?QueryRow
Executes the query with arguments, returns a single row. Returns an error if the query returns more than one row. Returns `null` if the query returns no row. `deinit` must be called on the returned `QueryRow`.

### rowOpts(sql: []const u8, args: anytype, opts: Conn.QueryOpts) !Result
Same as `row` but takes the same options as `queryOpts`.

### prepare(sql: []const u8) !Stmt
Creates a [Stmt](#stmt). It is generally better to use `query`, `row` or `exec`. 

### prepareOpts(sql: []const u8, opts: Conn.QueryOpts) !Stmt
Same as `prepare` but takes the same options as `queryOpts`.

### begin() !void
Calls `_ = try execOpts("begin", .{}, .{})`

### commit() !void
Calls `_ = try execOpts("commit", .{}, .{})`

### rollback() !void
Calls `_ = try execOpts("rollback", .{}, .{})`

## Result
The `conn.query` and `conn.queryOpts` methods return a `pg.Result` which is used to read rows and values.

### Fields
* `number_of_columns: usize` - Number of columns in the result.
* `column_names: [][]const u8` - Names of the column, empty unless the query was executed with the `column_names = true` option or the `column_names` build option was set to true.

### deinit(result: \*Result) void
Releases resources associated with the result.

### drain(result: \*Result) !void
If you do not iterate through the result until `next` returns `null`, you must call `drain`. 

Why can't `deinit` handle this? If `deinit` also drained, you'd have to handle a possible error in `deinit` and you can't `try` in a defer. Thus, this is done to provide better ergonomics for the normal case - the normal case being where `next` is called until it returns `null`. In these cases, just `defer result.deinit()`.

### next(result: \*Result) !?Row
Iterates to the next row of the result, or returns null if there are no more rows.

### columnIndex(result: \*Result, name: []const u8) ?usize
Returns the index of the column with the given name. This is only valid when the query is executed with the `column_names = true` option or the `column_names` build option was set to true.

### mapper(result: \*Result, T: type, opts: MapperOpts) Mapper(T)
Returns a Mapper which can be used to create a T for each row. Mapping from column to field is done by name. This is an optimized version of [row.to](#tot-type-opts-toopts-t) when iterating through multiple rows with the `{.map = .name}`.

See [row.to](#tot-type-opts-toopts-t) and [Mapper](#mapper) for more information.

## Row
The `row` represents a single row from a result. Any non-primitive value that you get from the `row` are valid only until the next call to `next`, `deinit` or `drain`.

### Fields
Only advance usage will need access to the row fields:

* `oids: []i32` - The PG OID value for each column in the row. See `result.number_of_columns` for the length of this slice. Might be useful if you're trying to read a non-natively supported type.
* `values: []Value` - The underlying byte value for each column in the row.  See `result.number_of_columns` for the length of this slice. Might be useful if you're trying to read a non-natively supported type. Has two fields, `is_null: bool` and `data: []const u8`.

### get(comptime T: type, col: usize) !T
Gets a value from the row at the specified column index (0-based). **Type mapping is strict.** For example, you **cannot** use `i32` to read an `smallint` column.

For any supported type, you can use an optional instead. Therefore, if you use `row.get(i16, 0)` the return type is `i16`. If you use `row.get(?i16, 0)` the return type is `!?i16`. 

* `u8` - `char`
* `i16` - `smallint`
* `i32` - `int`
* `i64` - Depends on the underlying column type. A `timestamp(tz)` will be converted to microseconds since unix epoch. Otherwise, a `bigint`.
* `f32` - `float4`
* `f64` - Depends on the underlying column type. A `numeric` will be converted to an `f64`. Otherwise, a `float`.
* `bool` - `bool`
* `[]const u8` - Returns the raw underlying data. Can be used for any column type to get the PG-encoded value. For `text` and `bytea` columns, this will be the expected value. For `numeric`, this will be a text representation of the number. For `UUID` this will be a 16-byte slice (use `pg.uuidToHex [36]u8` if you want a hex-encoded UUID). For `JSON` and `JSONB` this will be the serialized JSON value.
* `[]u8` - Same as []const u8 but returns a mutable value.
* `pg.Numeric` - See numeric section.
* `pg.Cidr` - See CIDR/INET section.

### getCol(comptime T: type, column_name: []const u8) !T
Same as `get` but uses the column name rather than its position. Only valid when the `column_names = true` option is passed to `queryOpts` or the `column_names` build option was set to true.

This relies on calling `result.columnIndex` which iterates through `result.column_names` fields. In some cases, this is more efficient than `StringHashMap` lookup, in others, it is worse. For performance-sensitive code, prefer using `get`, or cache the column index in a local variables outside of the `next()` loop:

```zig
const id_idx = result.columnIndex("id").?
while (try result.next()) |row| {
  // try row.get(i32, id_idx)
}
```

### Array Columns
Use `row.get(pg.Iterator(i32))` to return an [!Iterator](#iteratort) over an array column. Supported array types are:

* `u8` and `?u8` - `char[]`
* `i16` and `?i16` - `smallint[]`
* `i32` and `?i32` - `int[]`
* `i64` and `?i64` - `bigint[]` or `timestamp(tz)[]` (see `get`)
* `f32` and `?f32` - `float4`
* `f64` and `?f64` - `float8`
* `bool` and `?bool` - `bool[]`
* `[]const u8` and `[]?const u8` - More strict than `get([]u8)`. Supports: `text[]`, `char(n)[]`, `bytea[]`, `uuid[]`, `json[]` and `jsonb[]`.
* `[]u8` - Same as `[]const u8` but returns mutable value.
* `pg.Numeric` - See numeric section.
* `pg.Cidr` - See CIDR/INET section.

### record(col: usize) Record
Gets a [Record](#record) by column position.

### recordCol(column_name: []const u8) Record
Gets an [Record](#record) by column name. See [getCol](#getcolcomptime-t-type-column_name-const-u8-t) for performance notes.

### to(T: type, opts: ToOpts) !T
Populates and returns a `T`. 

`opts` values are:
* `dupe` - Duplicate string columns using the internal arena. When set to `true` non-scalar values are valid until `deinit` is called on the `row`/`result`. Defaults to `false`.
* `allocator` - Allocator to use to duplicate non-scalar values (i.e. strings). It is the caller's responsibility to free any non-scalar values from their structure. Defaults to `null`.
* `map` - `.ordinal` or `.name`, defaults to `.ordinal`.

Setting `allocator` implies `dupe`, but uses the specified allocator rather than the internal arena. By default (when `dupe` is `false` and `allocator` is `null`), non-scalar values (i.e. strings) are only valid until the next call to `next()` or `drain()` or `deinit()`.

When `.map = .ordinal`, the default, the order of the field names must match the order of the columns. 

When `.map = .name`, the query must be executed with the  `{.column_names = true}` option or the `column_names` build option must be set. Columns with no field equivalent are ignored. Fields with no column equivalent are set to their default value; if they do not have a default value the function will return `error.FieldColumnMismatch`. If you're going to use this in a loop with a `result`, consider using a [Mapper](#mapper) to avoid the name->index lookup on each iteration.

Slice fields can either be mapped to a `pg.Iterator(T)` or a slice. When mapped to a `slice`, an allocator MUST be provided. When mapping to an array of strings (i.e. [][]const u8), the values are duped, and thus both the values and the slice itself must be freed. When mapping to a slice of primitives (i.e. []i32) the slice must be freed. When mapping to an `pg.Iterator(T)` with a custom allocator (`.{.allocator = allocator}`), the iterator must be freed by calling `iteartor.deinit(allocator)`. Whether you're mapping to an `pg.Iterator(T)` or a slice, I Strongly suggest you use an ArenaAllocator.

## QueryRow
A `QueryRow` is returned from a call to `conn.row` or `conn.rowOpts` and wraps both a `Result` and a `Row.` It exposes the same methods as `Row` as well as `deinit`, which must be called once the `QueryRow` is no longer needed. This is a rare case where `deinit()` can fail. In most cases, you can simply throw away the error (because failure is extremely rare and, if the connection came from a pool, it should repair itself).

## Iterator(T)
The iterator returned from `row.get(pg.Iterator(T), col)` can be iterated using the `next() ?T` call:

```zig
var names = try row.get(pg.Iterator([]const u8), 0);
while (names.next()) |name| {
  ...
}
```

### Fields
* `len` - the number of values in the iterator.
* `is_null` - Whether the array itself was null.

### alloc(it: Iterator(T), allocator: std.mem.Allocator) ![]T
Allocates a slice and populates it with all values. 

If the slice is a `[]u8` or `[]const u8`, the string is also duplicated. It is the responsibility of the caller to free the string values AND the slice.

### fill(it: Iterator(T), into: []T) void
Fill `into` with values of the iterator. `into` can be smaller than `it.len`, in which case only `into.len` values will be filled. This can be a bit faster than calling `next()` multiple times. Values are not duplicated; they are only valid until the next iterations.

## Record
Returned by `row.record(col)` for fetching a PostgreSQL record-type, for example from this query: 

```sql
select row('over', 9000)
```

In many cases, PostgreSQL will mark the inner-types as "unknown", which is likely to cause assertion failures in this library. The solution is to type each value:

```sql
select row('over'::text, 9000::int)
```

### Fields
* `number_of_columns` - the number of columns in the record

### next(T) T
Gets the next column in the record. This behaves similarly [row.get](#getcomptime-t-type-col-usize-t) with the same supported types for `T`, including nullables.

## Mapper
A mapper is used to iterate through a result and turn a row into an instance of `T`. When converting a single row, or using ordinal mapping, prefer using [row.to](#tot-type-opts-toopts-t). The mapper is an optimization over `row.to` with the `{.map = .name}` option which only has to do the name -> index lookup once.

To use a mapper, the `{.column_names = true}` option must be passed to the query/row function or the `column_names` build option must be set.

```zig
const User = struct {
  id: i32,
  name: []const u8,
};

///...

var result = try conn.queryOpts("select id, name from users", .{}, .{.column_names = true});
defer result.deinit();

var mapper = result.mapper(User, .{});
while (try mapper.next()) |user| {
  // use: user.id and user.name
}
```

A column with no matching field is ignored. A field with no matching column is set to its default fault. If no default value is defined, `mapper.next()` will return `error.FieldColumnMismatch`.

The 2nd argument to `result.mapper` is an option:

* `dupe` - Duplicate string columns using the internal arena. When set to `true` non-scalar values are valid until `deinit` is called on the `row`/`result`. Defaults to `false`
* `allocator` - Allocator to use to duplicate non-scalar values (i.e. strings). It is the caller's responsibility to free any non-scalar values from their structure. Defaults to `null`.

Setting `allocator` implies `dupe`, but uses the specified allocator rather than the internal arena. By default (when `dupe` is `false` and `allocator` is `null`), non-scalar values (i.e. strings) are only valid until the next call to `next()` or `drain()` or `deinit()`.

## Stmt
For most queries, you should use the `conn.query(...)`, `conn.row(...)` or `conn.exec(...)` methods. For queries with parameters, these methods look like:

```zig
var stmt = try Stmt.init(conn, opts);
errdefer stmt.deinit();

try stmt.prepare(sql, null);
inline for (parameters) |param| {
  try stmt.bind(param);
}

return stmt.execute();
```

You can create a statement directly using `conn.prepare(sql)` or `conn.prepareOpts(sql, ConnQueryOpts{...})` and call `stmt.bind(value: anytype)` and `execute()` directly.

The main reason to do this is to have more flexibility in binding parameters (e.g. such as when creating dynanmic SQL where all the parameters aren't fixed at compile-time).

Note that `stmt.deinit()` should only be called if `stmt.execute()` is not called or returns an error. Once `stmt.execute()` returns a [Result](#result), `stmt` should be considered invalid. As we can see in the above example, `stmt.deinit()` is only called on `errdefer`.

## Caching Prepared Statements
When you execute a statement with parameters, we first ask PostgreSQL to "parse" the statement (which creates an execution plan) and then describe it. We can then bind the parameters and execute the statement.

If you plan on executing the same query(ies) repeatedly, it's possible to have PostgreSQL cache the execution plan and pg.zig cache the description. However, there are some caveats with this approach (which are not specific to pg.zig). First, if you're using a connection pooler (like pgpool or PgBouncer), make sure to read the documentation and configure it to work properly with cached prepared statements. Historically, cached prepared statements and connection poolers have not worked well together.

Secondly, note that the cache is per-connection. If you have a pool of 50 connections, and you execute the query against connections from the pool, then you should expect the full parse -> describe -> bind -> execute flow for those 50 connections (plus whatever new connections the pool might open).

Caching is enabled by passing the `cache_name` option:

```zig
const result = try conn.queryOpts(
    "select * from saiyans where power > $1", 
    .{9000}, 
    .{.cache_name = "super"}
);
```

Technically, once cached, the SQL statement is ignored. So, after executing the above, you could execute the following **on the same connection**:

```zig
const result = try conn.queryOpts(
    "this isn't valid SQL", 
    .{1000}, 
    .{.cache_name = "super"}
);
```

And it **will** work. But you're playing with fire, and you should just include the same SQL and the same cache name for each execution. If you want to use the `.column_names = true` option, then it _must_ be included in the first query which generated the cache entry (again, in short, just _always_ use the same SQL and the same options).

You can call `try conn.deallocate("super")` to remove a cache entry. But this is only done for the connection on which it is called. This would make sense, for example, if you get a connection from the pool, execute the same query multiple times, deallocate the cached entry, and return the connection back to the pool. Note that the name to deallocate, `super`, is not sanitized and is open to SQL injection - don't pass a user-supplied value to `deallocte`.

## Important Notice 1 - Bind vs Read
When you read a value, e.g. using `row.get`, the library is strict and won't help you with type conversion. If you're column is a smallint, you have to `get`
an `i16.

Conversely, when binding a value to an SQL parameter, the library is a little more generous. For example, an `u64` will bind to an `i32` provided the value is within range.

This is particularly relevant for types which are expressed as `[]u8`. For example a UUID can be a raw binary `[16]u8` or a hex-encoded `[36]u8`. Where possible (e.g. UUID, MacAddr, MacAddr8), the library will support binding either the raw binary data or text-representation. When reading, the raw binary value is always returned.

## Important Notice 2 - Invalid Connections
Strongly consider using `pg.Pool` rather than using `pg.Conn` directly. The pool will attempt to reconnect disconnected connections or connections which are in an invalid state. Until more real world testing is done, you should assume that connections will get into invalid states.

## Important Notice 3 - Errors
Zig errorsets do not support arbitrary payloads. This is problematic in a database driver where most applications probably care about the details of an error. The library takes a simple approach. If `error.PG` is returned, `conn.err` should be set and will contains a PG error object:

```zig
_ = conn.exec("drop table x", .{}) catch |err| {
  if (err == error.PG) {
    if (conn.err) |pge| {
      std.log.err("PG {s}\n", .{pge.message});
    }
  }
  return err;
};
```

In the above snippet, it's possible to skip the `if (err == error.PG)` check, but in that case `conn.err` could be set from some previous command (`conn.err` is always reset when acquired from the pool).

If `error.PG` is returned from a non-connection object, like a query result, the associated connection will have its `conn.err` set. In other words, `conn.err` is the only thing you ever have to check.

A PG error always exposes the following fields:
* `code: []const u8` - https://www.postgresql.org/docs/current/errcodes-appendix.html
* `message: []const u8`
* `severity: []const u8`

And optionally (depending on the error and the version of the server):
* `column: ?[]const u8 = null`
* `constraint: ?[]const u8 = null`
* `data_type_name: ?[]const u8 = null`
* `detail: ?[]const u8 = null`
* `file: ?[]const u8 = null`
* `hint: ?[]const u8 = null`
* `internal_position: ?[]const u8 = null`
* `internal_query: ?[]const u8 = null`
* `line: ?[]const u8 = null`
* `position: ?[]const u8 = null`
* `routine: ?[]const u8 = null`
* `schema: ?[]const u8 = null`
* `severity2: ?[]const u8 = null`
* `table: ?[]const u8 = null`
* `where: ?[]const u8 = null`

The `isUnique() bool` method can be called on the error to determine whether or not the error was a unique violation (i.e. error code `23505`).

## Unsafe Fast Mode
For raw performance and danger, you can use the `unsafe` variants of many functions, e.g. `pool.rowUnsafe()` and `result.nextUnsafe()`. These versions return an unsafe row which skips type checking:

Safe:
```zig
while (try result.next()) |row| {
  // notice the try
  const id = try row.get(i32, 0);
}
```

Unsafe:

Safe:
```zig
while (try result.nextUnsafe()) |row| {
  // no try
  const id = row.get(i32, 0);
}
```

If the types (or nullability) is wrong, in `Debug` and `ReleaseSafe` you'll get a failed assertion. In `ReleaseSmall` and `ReleaseFast` it' it's undefined behavior. This is dangerous, but can be useful when you're reading a very large number of rows in a loop.

## Type Support
All implementations have to deal with things like: how to support unsigned integers, given that PostgreSQL only has signed integers. Or, how to support UUIDs when the language has no UUID type. This section documents the exact behavior.

### Arrays
Multi-dimensional arrays aren't supported. The array lower bound is always 0 (or 1 in PG).

### text, bool, bytea, char, char(n), custom enums
No surprises, arrays supported. 

When reading a `char[]`, it's tempting to use `row.get([]u8, 0)`, but this is incorrect. A `char[]` is an array, and thus `row.get(pg.Iterator(u8), 0)` must be used.

### smallint, int, bigint
When binding an integer, the library will coerce the Zig value to the parameter type, as long as it fits. Thus, a `u64` can be bound to a `smallint`, if the value fits, else an error will be returned.

Array binding is strict. For example, an `[]i16` must be used for a `smallint[]` parameter. The only exception is that the unsigned variant, e.g. `[]u16` can be used provided all values fit.

When reading a column, you must use the correct type. 

### Floats
When binding, `@floatCast` is used based on the SQL parameter type. Array binding is strict. When reading a value, you must use the correct type. 

### Numeric
Until standard support comes to Zig (either in the stdlib or a de facto standard library), numeric support is half-baked. When binding a value to a parameter, you can use a f32, f64, comptime_float or string. The same applies to binding to a numeric array.

You can `get(pg.Numeric, $COL)` to return a `pg.Numeric`. The `pg.Numeric` type only has 2 useful methods: `toFloat` and `toString`. You can also use `num.estimatedStringLen` to get the max size of the string representation:

```zig
const numeric = row.get(pg.Numeric, 0);
var buf = allocator.alloc(u8, numeric.estimatedStringLen());
defer allocator.free(buf)
const str = numeric.toString(&buf);
```

Using `row.get(f64, 0)` on a numeric is the same as `row.get(pg.Numeric, 0).toFloat()`.

You should consider simply casting the numeric to `::double` or `::text` within SQL in order to rely on PostgreSQL's own robust numeric to float/text conversion.

However, `pg.Numeric` has fields for the underlying wire-format of the numeric value. So if you require precision and the text representation isn't sufficient, you can parse the fields directly. `types/numeric.zig` is relatively well documented and tries to explain the fields. Note that any non-primitive fields, e.g. the  `digits: []u8`, is only valid until the next call to `result.next`, `result.deinit`, `result.drain` or `row.deinit`.

### UUID
When a `[]u8` is bound to a UUID column, it must either be a 16-byte slice, or a valid 36-byte hex-encoded UUID. Arrays behave the same.

When reading a `uuid` column with `[]u8` a 16-byte slice will be returned. Use the `pg.uuidToHex() ![36]u8` helper if you need it hex-encoded.

### INET/CIDR
You can bind a string value to a `cidr`, `inet`, `cidr[]` or `inet[]` parameter.

When reading a value via `row.get` or `row.iterator` you should use `pg.Cidr`. It exposes 3 fields:

* `address: []u8` - Will be a 4 or 16 byte slice depending on the family.
* `family: Family` - An enum, either `Family.v4` of `Family.v6`.
* `netmask: u8` - The network mask.

### MacAddr/MacAddr8
You can bind a `[]u8` to either a `macaddr` or a `macaddr8`. These can be either binary representation (6-bytes for `macaddr` or 8 bytes for `macaddr8`) or a text-representation supported by PostgreSQL. This works, like UUID, because there's no ambiguity in the length. The same applied for array variants - it's even possible to mix and match formats within the array.

When reading a value via `row.get` or `row.iterator` using `[]u8`, the binary representation is always returned.

### Timestamp(tz)
When you bind an `i64` to a timestamp(tz) parameter, the value is assumed to be the number of microseconds since unix epoch (e.g. `std.time.microTimestamp()`). Array binding works the same. You can also bind a string, which will pass the string as-is and depend on PostgreSQL to do the conversion. This is true for arrays as well.

When reading a `timestamp` column with `i64`, the number of microseconds since unix epoch will be returned.

### JSON and JSONB
When binding a value to a JSON or JSONB parameter, you can either supply a serialized value (i.e. `[]u8`) or a struct which will be serialized using `std.json.stringify`.

When binding to an array of JSON or JSONB, automatic serialization is not support and thus an array of serialized values must be provided.

When reading a `JSON` or `JSONB` column with `[]u8`, the serialized JSON will be returned.

### PgLSN, xid8, xid
PgLSN and xid8 can be bound and read as i64.

xid can be bound and read as i32.

### Arbitrary Binary Encoding
For other types, either open an issue (ideally, with a sample query/data), or you can use binary encoding directly. 

For reading, you can use `[]u8` to get the raw binary encoded data and parse it yourself.

For writing, wrap your raw encoded data in `pg.Binary{.data = ....}`.

## Listen / Notify
You can create a `pg.Listener` either from an existing `Pool` or directly.

Creating a new Listener directly is a lot like creating a new connection. See [Conn.open](#openallocator-stdmemallocator-opts-opts-conn) and [Conn.auth](#authopts-opts-void).

```zig
// see the Conn.ConnectOpts
var listener = try pg.Listener.open(allocator, .{
  .host = "127.0.0.1",
  .port = 5432,
});
defer listener.deinit();

try listener.auth(.{
  .username = "leto",
  .password = "ghanima",
  .database = "caladan",
});

// add 1 or more channels to listen to
try listener.listen("chan_1", .{});
try listener.listen("chan_2", .{});

// .next() blocks until there's a notification or an error
while (listener.next()) |notification| {
  std.debug.print("Channel: {s}\nPayload: {s}", .{notification.channel, notification.payload});
}

// The error handling is explained, sorry about this API. Zig error payloads plz
switch (listener.err.?) {
  .pg => |pg| std.debug.print("{s}\n", .{pg.message}),
  .err => |err| std.debug.print("{s}\n", .{@errorName(err)}),
}
```

When using the pool, a new connection/session is created. It *does not* use a connection from the pool. This is merely a convenience function if you're also using normal connections through a pool.

```zig
var listener = try pool.newListener();
defer listener.deinit();

// listen to 1 or more channels
try listener.listen("chan_1");

// same as above
```

### Listen Timeout
When calling `listen`, a timeout in milliseconds can be specified:

```zig
try listener.listen("chan_1", .{});
```

If multiple calls to `listen` are made, the last timeout will be used. If no message is received in `timeout` milliseconds, `next()` will return `null` and `listener.err.?.err == error.WouldBlock`.

### Reconnects
A listener will not automatically reconnect on error/disconnect. The pub/sub nature of LISTEN/NOTIFY mean that delivery is at-most-once and auto-reconnecting can hide that fact. Put the above code in a `while (true) {...}` loop.

### Stop
It is safe to call `listener.stop()` from a different thread. When called, `next()` will return `null` and `listener.stopped` will be `true`.

## Errors
The handling of errors isn't great. Blame Zig's lack of error payloads and the awkwardness of using `try` within a `while` condition.

`listener.next()` can only return `null` on error. When `null` is returned, `listener.err` will be non-null. Unlike the `Conn` this is a tagged union that can either be `err` for a normal Zig error (e.g. error.ConnectionResetByPeer) or `pg` a detailed PostgresSQL error.

## Metrics
A few basic metrics are collected using [metrics.zig](https://github.com/karlseguin/metrics.zig), a prometheus-compatible library. These can be written to an `std.io.Writer` using `try pg.writeMetrics(writer)`. As an example using [httpz](https://github.com/karlseguin/http.zig):

```zig
pub fn metrics(_: *httpz.Request, res: *httpz.Response) !void {
    const writer = res.writer();
    try pg.writeMetrics(writer);

    // also write out the httpz metrics
    try httpz.writeMetrics(writer);
}
```

The metrics are:

* `pg_queries` - counts the number of queries.
* `pg_pool_empty` - counts how often the pool is empty.
* `pg_pool_dirty` - counts how often a connection is released back into the pool in an unclean state (thus requiring the connection to be closed and the pool to re-open another connection). This could indicate that results aren't being fully drained (either by calling `next()` until `null` is returned or explicitly calling the `drain()` method).
* `pg_alloc_params` - counts the number of parameter states that were allocated. This indicates that your queries have more parameters than `result_state_size`. If this happens often, consider increasing `result_state_size`.
* `pg_alloc_columns` - counts the number of columns states that were allocated. This indicates that your queries are returning more columns than `result_state_size`. If this happens often, consider increasing `result_state_size`.
* `pg_alloc_reader` - counts the number of bytes allocated while reading messages from PostgreSQL. This generally happens as a result of large result (e.g. selecting large text fields). Controlled by the `read_buffer` configuration option.

## TLS (Experimental)
TLS is supported via openssl. When loading the module, you must enable openssl by including at least 1 openssl setting:

```zig
const pg_module = b.dependency("pg", .{
  .target = target,
  .optimize = optimize,
  .openssl_lib_name = @as([]const u8, "ssl"),
  .openssl_lib_path = std.Build.LazyPath{.cwd_relative = "/path/to/openssl/lib"},
  .openssl_include_path = std.Build.LazyPath{.cwd_relative = "/path/to/openssl/include"},
}).module("pg")
```

When not specified, the system defaults are use for the library and include paths. These should only be set if openssl is installed in a non-default location. In most cases specifying `.openssl_lib_name = "ssl"` or, for some systems `.openssl_lib_name = "openssl"` should be enough.

Set the connection's `tls` option to either `.required` or `.{verify_full = null}`. When using a custom root certificate, specify the path: `.{verify_full = "/path/to/root.crt"}`.

```zig
var pool = try pg.Pool.init(allocator, .{
  .connect = .{ .port = 5432, .host = "ip_or_hostname", .tls = .{.verify_full = null}},
  .auth = .{ .... },
  .size = 5,
});

// OR
const uri = try std.Uri.parse("postgresql://user:password@hostname/DBNAME?sslmode=require");
var pool = try pg.Pool.initUri(allocator, uri, 10, 5_000);
```

In your main file, you can define a global `pub const pg_stderr_tls = true;` to have pg.zig print possible TLS-related errors to stderr. Alternatively, if you get an error, you `pg.printSSLError();` to hopefully print an error message to stderr which can be included in a ticket. This can safely be called in a `catch` clause, and will display nothing if the error is NOT SSL-related. Note that using the global `pg_stderr_tls` is more likely to print useful information in the case of certification verification problems.

## Enabling Column Names by Default

To execute all queries as if the `column_names` option was set to true, you can provide the `column_names` argument to `b.dependency()`:

```zig
const pg_module = b.dependency("pg", .{
  .target = target,
  .optimize = optimize,
  .column_names = true,
}).module("pg");
```

## Tests

Launch the Postgres database with the provided Docker Compose configuration:

```console
cd tests/
docker compose up
```

Run tests:

```console
zig build test
```
