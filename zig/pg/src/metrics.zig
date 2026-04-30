const m = @import("metrics");

// This is an advanced usage of metrics.zig, largely done because we aren't
// using any vectored metrics and thus can do everything at comptime.
var metrics = Metrics{
    .queries = m.Counter(usize).Impl.init("pg_query", .{}),
    .pool_empty = m.Counter(usize).Impl.init("pg_pool_empty", .{}),
    .pool_dirty = m.Counter(usize).Impl.init("pg_pool_dirty", .{}),
    .alloc_params = m.Counter(usize).Impl.init("pg_alloc_params", .{}),
    .alloc_columns = m.Counter(usize).Impl.init("pg_alloc_columns", .{}),
    .alloc_reader = m.Counter(usize).Impl.init("pg_alloc_reader", .{}),
};

const Metrics = struct {
    queries: m.Counter(usize).Impl,
    pool_empty: m.Counter(usize).Impl,
    pool_dirty: m.Counter(usize).Impl,
    alloc_params: m.Counter(usize).Impl,
    alloc_columns: m.Counter(usize).Impl,
    alloc_reader: m.Counter(usize).Impl,
};

pub fn write(writer: anytype) !void {
    try metrics.queries.write(writer);
    try metrics.pool_empty.write(writer);
    try metrics.pool_dirty.write(writer);
    try metrics.alloc_params.write(writer);
    try metrics.alloc_columns.write(writer);
    try metrics.alloc_reader.write(writer);
}

pub fn query() void {
    metrics.queries.incr();
}

pub fn poolEmpty() void {
    metrics.pool_empty.incr();
}

pub fn poolDirty() void {
    metrics.pool_dirty.incr();
}

pub fn allocParams(count: usize) void {
    // this is the # of parameters, not the bytes allocated.
    metrics.alloc_params.incrBy(count);
}

pub fn allocColumns(count: usize) void {
    // this is the # of columns, not the bytes allocated.
    metrics.alloc_columns.incrBy(count);
}

pub fn allocReader(size: usize) void {
    metrics.alloc_reader.incrBy(size);
}
