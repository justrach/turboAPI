// db.zig — Zig-native Postgres via pg.zig
// Zero-Python CRUD: HTTP request → dhi validate → pg.zig query → JSON response
// No GIL acquired at any point.

const std = @import("std");
const pg = @import("pg");
const py = @import("py.zig");
const c = py.c;
const router_mod = @import("turboapi-core").router;
const dhi = @import("dhi_validator.zig");
const logger = @import("logger.zig");

// GIL release shim (C functions to avoid opaque PyThreadState in Zig cimport)
extern fn py_gil_save() ?*anyopaque;
extern fn py_gil_restore(?*anyopaque) void;

const allocator = std.heap.c_allocator;
// ── Types ────────────────────────────────────────────────────────────────────

pub const DbOp = enum(u8) { select_one, select_list, insert, delete, custom_query, custom_query_single };

pub const DbRouteEntry = struct {
    op: DbOp,
    table: []const u8,
    columns: []const []const u8,
    json_key_parts: []const []const u8,
    pk_column: ?[]const u8,
    pk_param: ?[]const u8,
    select_sql: []const u8,
    insert_sql: []const u8,
    delete_sql: []const u8,
    custom_sql: []const u8,
    param_names: []const []const u8,
    cache_name: ?[]const u8, // prepared statement cache name (skips Parse on repeat queries)
    schema: ?dhi.ModelSchema,
};

// ── Global state ─────────────────────────────────────────────────────────────

var db_pool: ?*pg.Pool = null;
var db_routes_map: ?std.StringHashMap(DbRouteEntry) = null;

// ── Production-ready DB cache: TTL, per-table invalidation, thread-safe, LRU ─

const CacheEntry = struct {
    body: []const u8,
    table: []const u8, // which table this entry belongs to (for targeted invalidation)
    created_at: i64, // timestamp in seconds
};

const DB_CACHE_MAX: usize = 10_000;
var db_cache_enabled: bool = true;
var db_cache_ttl: i64 = 30; // default 30 second TTL
var db_cache: ?std.StringHashMap(CacheEntry) = null;
var db_cache_count: usize = 0;
var db_cache_mutex: std.Thread.Mutex = .{};
var db_cache_checked_env: bool = false;

const ExecManyMode = enum {
    multi_values,
    dynamic_protocol,
};

var exec_many_mode: ExecManyMode = .dynamic_protocol;

fn isDbCacheEnabled() bool {
    if (!db_cache_checked_env) {
        db_cache_checked_env = true;
        if (std.posix.getenv("TURBO_DISABLE_DB_CACHE")) |val| {
            if (std.mem.eql(u8, val, "1") or std.mem.eql(u8, val, "true")) {
                db_cache_enabled = false;
                logger.info("[DB] Cache DISABLED via TURBO_DISABLE_DB_CACHE", .{});
            }
        }
    }
    return db_cache_enabled;
}

fn configureExecManyModeFromEnv() void {
    exec_many_mode = .multi_values;
    if (std.posix.getenv("TURBOPG_EXEC_MANY_MODE")) |val| {
        if (std.mem.eql(u8, val, "multi") or std.mem.eql(u8, val, "multi_values")) {
            exec_many_mode = .multi_values;
        } else if (std.mem.eql(u8, val, "dynamic") or std.mem.eql(u8, val, "protocol")) {
            exec_many_mode = .dynamic_protocol;
        }
    }
}
// Per-thread connections
const MAX_WORKERS: usize = 24;
var thread_conns: [MAX_WORKERS]?*pg.Conn = [_]?*pg.Conn{null} ** MAX_WORKERS;
var thread_conn_count: usize = 0;
var use_thread_conns: bool = false;

fn getDbCacheMap() *std.StringHashMap(CacheEntry) {
    if (db_cache) |*dc| return dc;
    db_cache = std.StringHashMap(CacheEntry).init(allocator);
    return &db_cache.?;
}

pub fn getDbRoutes() *std.StringHashMap(DbRouteEntry) {
    if (db_routes_map) |*m| return m;
    db_routes_map = std.StringHashMap(DbRouteEntry).init(allocator);
    return &db_routes_map.?;
}

pub fn getPool() ?*pg.Pool {
    return db_pool;
}

fn now() i64 {
    return @intCast(@divTrunc(std.time.milliTimestamp(), 1000));
}

/// Thread-safe cache lookup. Returns cached body or null if miss/expired.
fn cacheGet(key: []const u8) ?[]const u8 {
    if (!isDbCacheEnabled()) return null;
    db_cache_mutex.lock();
    defer db_cache_mutex.unlock();

    const cache = getDbCacheMap();
    if (cache.get(key)) |entry| {
        // TTL check
        if (db_cache_ttl > 0 and (now() - entry.created_at) > db_cache_ttl) {
            // Expired — remove it
            if (cache.fetchRemove(key)) |removed| {
                allocator.free(@constCast(removed.key));
                allocator.free(@constCast(removed.value.body));
                db_cache_count -|= 1;
            }
            return null;
        }
        return entry.body;
    }
    return null;
}

/// Thread-safe cache put. Evicts oldest entries if full.
fn cachePut(key: []const u8, body: []const u8, table: []const u8) void {
    if (!isDbCacheEnabled()) return;
    db_cache_mutex.lock();
    defer db_cache_mutex.unlock();

    // LRU eviction: if full, remove ~10% oldest entries
    if (db_cache_count >= DB_CACHE_MAX) {
        evictOldest(DB_CACHE_MAX / 10);
    }

    const key_dupe = allocator.dupe(u8, key) catch return;
    const body_dupe = allocator.dupe(u8, body) catch {
        allocator.free(key_dupe);
        return;
    };
    const table_dupe = allocator.dupe(u8, table) catch {
        allocator.free(key_dupe);
        allocator.free(body_dupe);
        return;
    };

    const cache = getDbCacheMap();
    // If key already exists, free old value
    if (cache.fetchRemove(key_dupe)) |old| {
        allocator.free(@constCast(old.key));
        allocator.free(@constCast(old.value.body));
        allocator.free(@constCast(old.value.table));
        db_cache_count -|= 1;
    }

    cache.put(key_dupe, .{
        .body = body_dupe,
        .table = table_dupe,
        .created_at = now(),
    }) catch {
        allocator.free(key_dupe);
        allocator.free(body_dupe);
        allocator.free(table_dupe);
        return;
    };
    db_cache_count += 1;
}

/// Per-table invalidation — only clears entries belonging to the specified table.
fn invalidateTableCache(table: []const u8) void {
    db_cache_mutex.lock();
    defer db_cache_mutex.unlock();

    const cache = getDbCacheMap();
    // Collect keys to remove (can't remove during iteration)
    var keys_to_remove: [256][]const u8 = undefined;
    var remove_count: usize = 0;

    var it = cache.iterator();
    while (it.next()) |entry| {
        if (std.mem.eql(u8, entry.value_ptr.table, table) or table.len == 0) {
            if (remove_count < 256) {
                keys_to_remove[remove_count] = entry.key_ptr.*;
                remove_count += 1;
            }
        }
    }

    for (keys_to_remove[0..remove_count]) |key| {
        if (cache.fetchRemove(key)) |removed| {
            allocator.free(@constCast(removed.key));
            allocator.free(@constCast(removed.value.body));
            allocator.free(@constCast(removed.value.table));
            db_cache_count -|= 1;
        }
    }
}

/// Evict N oldest entries (approximate LRU)
fn evictOldest(count: usize) void {
    // Already holding mutex from caller
    const cache = getDbCacheMap();
    var oldest_keys: [256][]const u8 = undefined;
    var oldest_times: [256]i64 = undefined;
    var oldest_count: usize = 0;
    const max_evict = @min(count, 256);

    var it = cache.iterator();
    while (it.next()) |entry| {
        const age = entry.value_ptr.created_at;
        if (oldest_count < max_evict) {
            oldest_keys[oldest_count] = entry.key_ptr.*;
            oldest_times[oldest_count] = age;
            oldest_count += 1;
        } else {
            // Replace the newest in our evict list if this one is older
            var newest_idx: usize = 0;
            for (0..oldest_count) |j| {
                if (oldest_times[j] > oldest_times[newest_idx]) newest_idx = j;
            }
            if (age < oldest_times[newest_idx]) {
                oldest_keys[newest_idx] = entry.key_ptr.*;
                oldest_times[newest_idx] = age;
            }
        }
    }

    for (oldest_keys[0..oldest_count]) |key| {
        if (cache.fetchRemove(key)) |removed| {
            allocator.free(@constCast(removed.key));
            allocator.free(@constCast(removed.value.body));
            allocator.free(@constCast(removed.value.table));
            db_cache_count -|= 1;
        }
    }
}

/// Acquire a Postgres connection — prefers per-thread conn, falls back to pool
fn acquireConn() ?*pg.Conn {
    // Try per-thread connection first (zero mutex overhead)
    if (use_thread_conns) {
        const tid = std.Thread.getCurrentId();
        const idx = tid % MAX_WORKERS;
        if (thread_conns[idx]) |conn| return conn;
    }
    // Fall back to pool
    if (db_pool) |pool| {
        return pool.acquire() catch null;
    }
    return null;
}

fn releaseConn(conn: *pg.Conn) void {
    // Per-thread connections are never released (they persist)
    if (use_thread_conns) return;
    // Pool connections get released
    conn.release();
}

// ── SQL builders (all pre-built at registration time, not per-request) ───────

fn isValidIdentifier(name: []const u8) bool {
    if (name.len == 0 or name.len > 64) return false;
    for (name, 0..) |ch, i| {
        if (i == 0) {
            if (!std.ascii.isAlphabetic(ch) and ch != '_') return false;
        } else {
            if (!std.ascii.isAlphanumeric(ch) and ch != '_') return false;
        }
    }
    return true;
}

fn buildSelectOneSql(table: []const u8, pk_column: []const u8, columns: []const []const u8) []const u8 {
    var col_buf: [2048]u8 = undefined;
    var col_pos: usize = 0;

    if (columns.len == 0) {
        return std.fmt.allocPrint(allocator, "SELECT * FROM {s} WHERE {s} = $1 LIMIT 1", .{ table, pk_column }) catch "";
    }

    for (columns, 0..) |col, i| {
        if (i > 0) {
            col_buf[col_pos] = ',';
            col_pos += 1;
            col_buf[col_pos] = ' ';
            col_pos += 1;
        }
        @memcpy(col_buf[col_pos..][0..col.len], col);
        col_pos += col.len;
    }

    return std.fmt.allocPrint(allocator, "SELECT {s} FROM {s} WHERE {s} = $1 LIMIT 1", .{
        col_buf[0..col_pos],
        table,
        pk_column,
    }) catch "";
}

fn buildSelectListSql(table: []const u8, columns: []const []const u8) []const u8 {
    var col_buf: [2048]u8 = undefined;
    var col_pos: usize = 0;

    if (columns.len == 0) {
        return std.fmt.allocPrint(allocator, "SELECT * FROM {s} LIMIT $1 OFFSET $2", .{table}) catch "";
    }

    for (columns, 0..) |col, i| {
        if (i > 0) {
            col_buf[col_pos] = ',';
            col_pos += 1;
            col_buf[col_pos] = ' ';
            col_pos += 1;
        }
        @memcpy(col_buf[col_pos..][0..col.len], col);
        col_pos += col.len;
    }

    return std.fmt.allocPrint(allocator, "SELECT {s} FROM {s} LIMIT $1 OFFSET $2", .{
        col_buf[0..col_pos],
        table,
    }) catch "";
}

fn buildInsertSql(table: []const u8, columns: []const []const u8) []const u8 {
    // INSERT INTO users (name, email, age) VALUES ($1, $2, $3) RETURNING *
    var col_buf: [2048]u8 = undefined;
    var val_buf: [512]u8 = undefined;
    var col_pos: usize = 0;
    var val_pos: usize = 0;

    for (columns, 0..) |col, i| {
        if (i > 0) {
            col_buf[col_pos] = ',';
            col_pos += 1;
            col_buf[col_pos] = ' ';
            col_pos += 1;
            val_buf[val_pos] = ',';
            val_pos += 1;
            val_buf[val_pos] = ' ';
            val_pos += 1;
        }
        @memcpy(col_buf[col_pos..][0..col.len], col);
        col_pos += col.len;

        // $N placeholder
        const placeholder = std.fmt.bufPrint(val_buf[val_pos..], "${d}", .{i + 1}) catch break;
        val_pos += placeholder.len;
    }

    return std.fmt.allocPrint(allocator, "INSERT INTO {s} ({s}) VALUES ({s}) RETURNING *", .{
        table,
        col_buf[0..col_pos],
        val_buf[0..val_pos],
    }) catch "";
}

fn buildDeleteSql(table: []const u8, pk_column: []const u8) []const u8 {
    return std.fmt.allocPrint(allocator, "DELETE FROM {s} WHERE {s} = $1", .{ table, pk_column }) catch "";
}
// ── JSON serialization — delegates to pg.zig's writeJsonRow ──────────────────

fn serializeRow(row: anytype, col_names: []const []const u8, buf: []u8) ![]const u8 {
    const len = row.writeJsonRow(col_names, buf);
    if (len == 0) return error.SerializationFailed;
    return buf[0..len];
}

fn serializeFixedSchemaRow(row: anytype, json_key_parts: []const []const u8, buf: []u8) ![]const u8 {
    var pos: usize = 0;
    buf[pos] = '{';
    pos += 1;

    const ncols = @min(json_key_parts.len, row.values.len);
    for (0..ncols) |i| {
        if (i > 0) {
            buf[pos] = ',';
            pos += 1;
        }
        const key_part = json_key_parts[i];
        @memcpy(buf[pos..][0..key_part.len], key_part);
        pos += key_part.len;
        pos += row.writeJsonValue(i, buf[pos..]);
    }

    buf[pos] = '}';
    pos += 1;
    return buf[0..pos];
}
// ── Request dispatch (called from server.zig fast-exit path) ─────────────────

pub fn handleDbRoute(
    stream: std.net.Stream,
    entry: *const DbRouteEntry,
    body: []const u8,
    params: *const router_mod.RouteParams,
    query_string: []const u8,
    sendResponseFn: *const fn (std.net.Stream, u16, []const u8, []const u8) void,
) void {
    switch (entry.op) {
        .select_one => {
            const pk_param = entry.pk_param orelse "id";
            const first_param: ?router_mod.RouteParam = if (params.len == 1) params.items_buf[0] else null;
            const pk_val_opt = if (first_param) |p|
                if (std.mem.eql(u8, p.key, pk_param)) p.value else params.get(pk_param)
            else
                params.get(pk_param);
            const pk_val = pk_val_opt orelse {
                sendResponseFn(stream, 400, "application/json", "{\"error\": \"Missing primary key\"}");
                return;
            };
            const pk_int = if (first_param) |p|
                if (std.mem.eql(u8, p.key, pk_param) and p.has_int_value) p.int_value else params.getInt(pk_param)
            else
                params.getInt(pk_param);
            const cache_enabled = isDbCacheEnabled();

            // Cache check — build cache key from table + pk value
            var cache_key_buf: [256]u8 = undefined;
            var cache_key: []const u8 = "";
            if (cache_enabled) {
                cache_key = std.fmt.bufPrint(&cache_key_buf, "GET:{s}:{s}", .{ entry.table, pk_val }) catch "";
                if (cache_key.len > 0) {
                    if (cacheGet(cache_key)) |cached_body| {
                        sendResponseFn(stream, 200, "application/json", cached_body);
                        return;
                    }
                }
            }

            const pool = getPool() orelse {
                sendResponseFn(stream, 503, "application/json", "{\"error\": \"Database connection unavailable\"}");
                return;
            };

            const known_columns = entry.columns.len > 0;
            const opts = pg.Conn.QueryOpts{ .column_names = !known_columns, .cache_name = entry.cache_name };
            var query_row = blk: {
                // Fast path for integer primary keys: router already parsed them when possible.
                if (pk_int) |pk_num| {
                    break :blk pool.rowOpts(entry.select_sql, .{pk_num}, opts) catch {
                        sendResponseFn(stream, 500, "application/json", "{\"error\": \"Query failed\"}");
                        return;
                    };
                }

                break :blk pool.rowOpts(entry.select_sql, .{pk_val}, opts) catch {
                    sendResponseFn(stream, 500, "application/json", "{\"error\": \"Query failed\"}");
                    return;
                };
            };
            if (query_row) |*qr| {
                defer qr.deinit() catch {};
                var json_buf: [8192]u8 = undefined;
                const json = if (known_columns)
                    serializeFixedSchemaRow(qr.row, entry.json_key_parts, &json_buf)
                else
                    serializeRow(qr.row, qr.result.column_names, &json_buf);
                const json_value = json catch {
                    sendResponseFn(stream, 500, "application/json", "{\"error\": \"Serialization failed\"}");
                    return;
                };
                // Cache the response
                if (cache_enabled and cache_key.len > 0) {
                    cachePut(cache_key, json_value, entry.table);
                }
                sendResponseFn(stream, 200, "application/json", json_value);
            } else {
                sendResponseFn(stream, 404, "application/json", "{\"error\": \"Not found\"}");
            }
        },

        .select_list => {
            var limit: []const u8 = "50";
            var offset: []const u8 = "0";

            if (query_string.len > 0) {
                var qs_iter = std.mem.splitScalar(u8, query_string, '&');
                while (qs_iter.next()) |pair| {
                    if (std.mem.startsWith(u8, pair, "limit=")) {
                        limit = pair[6..];
                    } else if (std.mem.startsWith(u8, pair, "offset=")) {
                        offset = pair[7..];
                    }
                }
            }

            const cache_enabled = isDbCacheEnabled();
            // Cache check for list queries
            var cache_key_buf: [256]u8 = undefined;
            var cache_key: []const u8 = "";
            if (cache_enabled) {
                cache_key = std.fmt.bufPrint(&cache_key_buf, "LIST:{s}:{s}:{s}", .{ entry.table, limit, offset }) catch "";
                if (cache_key.len > 0) {
                    if (cacheGet(cache_key)) |cached_body| {
                        sendResponseFn(stream, 200, "application/json", cached_body);
                        return;
                    }
                }
            }

            const conn = acquireConn() orelse {
                sendResponseFn(stream, 503, "application/json", "{\"error\": \"Database connection unavailable\"}");
                return;
            };
            defer releaseConn(conn);

            const known_columns = entry.columns.len > 0;
            var result = conn.queryOpts(entry.select_sql, .{ limit, offset }, .{ .column_names = !known_columns, .cache_name = entry.cache_name }) catch {
                sendResponseFn(stream, 500, "application/json", "{\"error\": \"Query failed\"}");
                return;
            };
            defer result.deinit();

            var out_buf = allocator.alloc(u8, 65536) catch {
                sendResponseFn(stream, 500, "application/json", "{\"error\": \"Out of memory\"}");
                return;
            };
            defer allocator.free(out_buf);

            var out_pos: usize = 0;
            out_buf[out_pos] = '[';
            out_pos += 1;

            var row_count: usize = 0;
            while (result.next() catch null) |row| {
                if (row_count > 0) {
                    out_buf[out_pos] = ',';
                    out_pos += 1;
                }
                var row_buf: [8192]u8 = undefined;
                const row_json_result = if (known_columns)
                    serializeFixedSchemaRow(row, entry.json_key_parts, &row_buf)
                else
                    serializeRow(row, result.column_names, &row_buf);
                const row_json = row_json_result catch break;
                if (out_pos + row_json.len + 2 > out_buf.len) break;
                @memcpy(out_buf[out_pos..][0..row_json.len], row_json);
                out_pos += row_json.len;
                row_count += 1;
            }

            out_buf[out_pos] = ']';
            out_pos += 1;

            const response_body = out_buf[0..out_pos];
            if (cache_enabled and cache_key.len > 0) {
                cachePut(cache_key, response_body, entry.table);
            }
            sendResponseFn(stream, 200, "application/json", response_body);
        },

        .insert => {
            if (body.len == 0) {
                sendResponseFn(stream, 400, "application/json", "{\"error\": \"Request body required\"}");
                return;
            }

            if (entry.schema) |schema| {
                const vr = dhi.validateJson(body, &schema);
                switch (vr) {
                    .ok => {},
                    .err => |ve| {
                        defer ve.deinit();
                        sendResponseFn(stream, ve.status_code, "application/json", ve.body);
                        return;
                    },
                }
            }

            const parsed = std.json.parseFromSlice(std.json.Value, allocator, body, .{}) catch {
                sendResponseFn(stream, 400, "application/json", "{\"error\": \"Invalid JSON\"}");
                return;
            };
            defer parsed.deinit();

            const obj = switch (parsed.value) {
                .object => |o| o,
                else => {
                    sendResponseFn(stream, 400, "application/json", "{\"error\": \"Expected JSON object\"}");
                    return;
                },
            };

            var num_bufs: [16][64]u8 = undefined;
            var values: [16][]const u8 = undefined;
            const ncols = @min(entry.columns.len, 16);

            for (entry.columns[0..ncols], 0..) |col, i| {
                if (obj.get(col)) |val| {
                    values[i] = switch (val) {
                        .string => |s| s,
                        .integer => |n| std.fmt.bufPrint(&num_bufs[i], "{d}", .{n}) catch "",
                        .float => |f| std.fmt.bufPrint(&num_bufs[i], "{d}", .{f}) catch "",
                        .bool => |b| if (b) "true" else "false",
                        .null => "null",
                        else => "",
                    };
                } else {
                    values[i] = "null";
                }
            }

            const conn = acquireConn() orelse {
                sendResponseFn(stream, 503, "application/json", "{\"error\": \"Database connection unavailable\"}");
                return;
            };
            defer releaseConn(conn);

            const insert_result = execWithParams(conn, entry.insert_sql, values[0..ncols], entry.cache_name);
            if (insert_result) |result| {
                defer result.deinit();
                // Invalidate cache on write
                invalidateTableCache(entry.table);
                if (result.next() catch null) |row| {
                    var json_buf: [8192]u8 = undefined;
                    const json = serializeRow(row, result.column_names, &json_buf) catch {
                        sendResponseFn(stream, 201, "application/json", "{\"created\": true}");
                        return;
                    };
                    sendResponseFn(stream, 201, "application/json", json);
                } else {
                    sendResponseFn(stream, 201, "application/json", "{\"created\": true}");
                }
            } else {
                sendResponseFn(stream, 500, "application/json", "{\"error\": \"Insert failed\"}");
            }
        },

        .delete => {
            const pk_param = entry.pk_param orelse "id";
            const pk_val = params.get(pk_param) orelse {
                sendResponseFn(stream, 400, "application/json", "{\"error\": \"Missing primary key\"}");
                return;
            };

            const conn = acquireConn() orelse {
                sendResponseFn(stream, 503, "application/json", "{\"error\": \"Database connection unavailable\"}");
                return;
            };
            defer releaseConn(conn);

            const affected = conn.exec(entry.delete_sql, .{pk_val}) catch {
                sendResponseFn(stream, 500, "application/json", "{\"error\": \"Delete failed\"}");
                return;
            };

            // Invalidate cache on write
            invalidateTableCache(entry.table);

            if (affected) |n| {
                if (n > 0) {
                    sendResponseFn(stream, 204, "application/json", "");
                } else {
                    sendResponseFn(stream, 404, "application/json", "{\"error\": \"Not found\"}");
                }
            } else {
                sendResponseFn(stream, 404, "application/json", "{\"error\": \"Not found\"}");
            }
        },

        .custom_query, .custom_query_single => {
            // Collect params: path params first, then query string params
            var param_values: [16][]const u8 = undefined;
            var param_count: usize = 0;
            var param_ints: [16]?i64 = [_]?i64{null} ** 16;

            for (entry.param_names) |pname| {
                if (param_count >= 16) break;
                if (params.get(pname)) |v| {
                    param_values[param_count] = v;
                    param_ints[param_count] = params.getInt(pname);
                    param_count += 1;
                } else {
                    // Try query string
                    var found = false;
                    if (query_string.len > 0) {
                        var qs_iter = std.mem.splitScalar(u8, query_string, '&');
                        while (qs_iter.next()) |pair| {
                            const eq = std.mem.indexOf(u8, pair, "=") orelse continue;
                            if (std.mem.eql(u8, pair[0..eq], pname)) {
                                param_values[param_count] = pair[eq + 1 ..];
                                param_ints[param_count] = std.fmt.parseInt(i64, pair[eq + 1 ..], 10) catch null;
                                param_count += 1;
                                found = true;
                                break;
                            }
                        }
                    }
                    if (!found) {
                        param_values[param_count] = "";
                        param_ints[param_count] = null;
                        param_count += 1;
                    }
                }
            }

            const cache_enabled = isDbCacheEnabled();
            // Cache check
            var cache_key_buf: [512]u8 = undefined;
            var cache_key: []const u8 = "";
            if (cache_enabled) {
                var ck_pos: usize = 0;
                const prefix = "Q:";
                @memcpy(cache_key_buf[ck_pos..][0..prefix.len], prefix);
                ck_pos += prefix.len;
                const sql_key_len = @min(entry.custom_sql.len, 64);
                @memcpy(cache_key_buf[ck_pos..][0..sql_key_len], entry.custom_sql[0..sql_key_len]);
                ck_pos += sql_key_len;
                for (param_values[0..param_count]) |v| {
                    cache_key_buf[ck_pos] = ':';
                    ck_pos += 1;
                    const vlen = @min(v.len, 32);
                    @memcpy(cache_key_buf[ck_pos..][0..vlen], v[0..vlen]);
                    ck_pos += vlen;
                }
                cache_key = cache_key_buf[0..ck_pos];
                if (cacheGet(cache_key)) |cached_body| {
                    sendResponseFn(stream, 200, "application/json", cached_body);
                    return;
                }
            }

            if (entry.op == .custom_query_single) {
                const pool = getPool() orelse {
                    sendResponseFn(stream, 503, "application/json", "{\"error\": \"Database connection unavailable\"}");
                    return;
                };
                const opts = pg.Conn.QueryOpts{ .column_names = true, .cache_name = entry.cache_name };
                const query_row = blk: {
                    if (param_count == 0) {
                        break :blk pool.rowOpts(entry.custom_sql, .{}, opts) catch null;
                    } else if (param_count == 1) {
                        if (param_ints[0]) |n| {
                            break :blk pool.rowOpts(entry.custom_sql, .{n}, opts) catch null;
                        }
                        break :blk pool.rowOpts(entry.custom_sql, .{param_values[0]}, opts) catch null;
                    } else if (param_count == 2) {
                        if (param_ints[0]) |n0| {
                            break :blk pool.rowOpts(entry.custom_sql, .{ n0, param_values[1] }, opts) catch null;
                        }
                        break :blk pool.rowOpts(entry.custom_sql, .{ param_values[0], param_values[1] }, opts) catch null;
                    }
                    break :blk null;
                };

                if (query_row) |qr_value| {
                    var qr = qr_value;
                    defer qr.deinit() catch {};
                    var json_buf: [8192]u8 = undefined;
                    const json = serializeRow(qr.row, qr.result.column_names, &json_buf) catch {
                        sendResponseFn(stream, 500, "application/json", "{\"error\": \"Serialization failed\"}");
                        return;
                    };
                    if (cache_enabled and cache_key.len > 0) cachePut(cache_key, json, entry.table);
                    sendResponseFn(stream, 200, "application/json", json);
                } else {
                    sendResponseFn(stream, 404, "application/json", "{\"error\": \"Not found\"}");
                }
            } else {
                const conn = acquireConn() orelse {
                    sendResponseFn(stream, 503, "application/json", "{\"error\": \"Database connection unavailable\"}");
                    return;
                };
                defer releaseConn(conn);

                const result_opt = execWithParams(conn, entry.custom_sql, param_values[0..param_count], entry.cache_name);
                if (result_opt) |result| {
                    defer result.deinit();

                    // Multi-row — JSON array
                    var out_buf = allocator.alloc(u8, 65536) catch {
                        sendResponseFn(stream, 500, "application/json", "{\"error\": \"Out of memory\"}");
                        return;
                    };
                    defer allocator.free(out_buf);

                    var out_pos: usize = 0;
                    out_buf[out_pos] = '[';
                    out_pos += 1;

                    var row_count: usize = 0;
                    while (result.next() catch null) |row| {
                        if (row_count > 0) {
                            out_buf[out_pos] = ',';
                            out_pos += 1;
                        }
                        var row_buf: [8192]u8 = undefined;
                        const row_json = serializeRow(row, result.column_names, &row_buf) catch break;
                        if (out_pos + row_json.len + 2 > out_buf.len) break;
                        @memcpy(out_buf[out_pos..][0..row_json.len], row_json);
                        out_pos += row_json.len;
                        row_count += 1;
                    }

                    out_buf[out_pos] = ']';
                    out_pos += 1;

                    const resp = out_buf[0..out_pos];
                    if (cache_enabled and cache_key.len > 0) cachePut(cache_key, resp, entry.table);
                    sendResponseFn(stream, 200, "application/json", resp);
                } else {
                    sendResponseFn(stream, 500, "application/json", "{\"error\": \"Query failed\"}");
                }
            }
        },
    }
}
fn execWithParams(conn: *pg.Conn, sql: []const u8, values: []const []const u8, cache_name: ?[]const u8) ?*pg.Result {
    const opts = pg.Conn.QueryOpts{ .column_names = true, .cache_name = cache_name };
    return switch (values.len) {
        0 => conn.queryOpts(sql, .{}, opts) catch return null,
        1 => conn.queryOpts(sql, .{values[0]}, opts) catch return null,
        2 => conn.queryOpts(sql, .{ values[0], values[1] }, opts) catch return null,
        3 => conn.queryOpts(sql, .{ values[0], values[1], values[2] }, opts) catch return null,
        4 => conn.queryOpts(sql, .{ values[0], values[1], values[2], values[3] }, opts) catch return null,
        5 => conn.queryOpts(sql, .{ values[0], values[1], values[2], values[3], values[4] }, opts) catch return null,
        6 => conn.queryOpts(sql, .{ values[0], values[1], values[2], values[3], values[4], values[5] }, opts) catch return null,
        7 => conn.queryOpts(sql, .{ values[0], values[1], values[2], values[3], values[4], values[5], values[6] }, opts) catch return null,
        8 => conn.queryOpts(sql, .{ values[0], values[1], values[2], values[3], values[4], values[5], values[6], values[7] }, opts) catch return null,
        else => null,
    };
}

fn execCountWithParams(conn: *pg.Conn, sql: []const u8, values: []const []const u8, cache_name: ?[]const u8) ?i64 {
    const opts = pg.Conn.QueryOpts{ .cache_name = cache_name };
    return switch (values.len) {
        0 => conn.execOpts(sql, .{}, opts) catch return null,
        1 => conn.execOpts(sql, .{values[0]}, opts) catch return null,
        2 => conn.execOpts(sql, .{ values[0], values[1] }, opts) catch return null,
        3 => conn.execOpts(sql, .{ values[0], values[1], values[2] }, opts) catch return null,
        4 => conn.execOpts(sql, .{ values[0], values[1], values[2], values[3] }, opts) catch return null,
        5 => conn.execOpts(sql, .{ values[0], values[1], values[2], values[3], values[4] }, opts) catch return null,
        6 => conn.execOpts(sql, .{ values[0], values[1], values[2], values[3], values[4], values[5] }, opts) catch return null,
        7 => conn.execOpts(sql, .{ values[0], values[1], values[2], values[3], values[4], values[5], values[6] }, opts) catch return null,
        8 => conn.execOpts(sql, .{ values[0], values[1], values[2], values[3], values[4], values[5], values[6], values[7] }, opts) catch return null,
        else => null,
    };
}

fn isNumericSqlValue(value: []const u8) bool {
    if (value.len == 0) return false;
    var has_digit = false;
    for (value, 0..) |ch, i| {
        switch (ch) {
            '0'...'9' => has_digit = true,
            '-', '+' => if (i != 0) return false,
            '.', 'e', 'E' => {},
            else => return false,
        }
    }
    return has_digit;
}

fn appendSqlLiteral(out: *std.ArrayList(u8), value: []const u8) !void {
    if (std.ascii.eqlIgnoreCase(value, "null")) {
        try out.appendSlice(allocator, "NULL");
        return;
    }
    if (std.ascii.eqlIgnoreCase(value, "true") or std.ascii.eqlIgnoreCase(value, "false") or isNumericSqlValue(value)) {
        try out.appendSlice(allocator, value);
        return;
    }

    try out.append(allocator, '\'');
    for (value) |ch| {
        if (ch == '\'') {
            try out.appendSlice(allocator, "''");
        } else {
            try out.append(allocator, ch);
        }
    }
    try out.append(allocator, '\'');
}

fn estimateMultiInsertCapacity(base_sql: []const u8, rows: []const []const []const u8) usize {
    var total: usize = base_sql.len + 2;
    for (rows, 0..) |row, ri| {
        if (ri > 0) total += 2;
        total += 2;
        for (row, 0..) |value, ci| {
            if (ci > 0) total += 2;
            if (std.ascii.eqlIgnoreCase(value, "null") or
                std.ascii.eqlIgnoreCase(value, "true") or
                std.ascii.eqlIgnoreCase(value, "false") or
                isNumericSqlValue(value))
            {
                total += value.len;
            } else {
                total += value.len + 2;
                for (value) |ch| {
                    if (ch == '\'') total += 1;
                }
            }
        }
    }
    return total + 1;
}

fn buildMultiInsertSql(base_sql: []const u8, rows: []const []const []const u8) ?[]u8 {
    if (rows.len == 0) return null;
    const values_idx = std.mem.indexOf(u8, base_sql, "VALUES") orelse return null;
    const prefix = std.mem.trimRight(u8, base_sql[0 .. values_idx + "VALUES".len], " \t\r\n");

    var out = std.ArrayList(u8).empty;
    errdefer out.deinit(allocator);
    out.ensureTotalCapacity(allocator, estimateMultiInsertCapacity(prefix, rows)) catch return null;
    out.appendSlice(allocator, prefix) catch return null;
    out.append(allocator, ' ') catch return null;

    for (rows, 0..) |row, ri| {
        if (ri > 0) out.appendSlice(allocator, ", ") catch return null;
        out.append(allocator, '(') catch return null;
        for (row, 0..) |value, ci| {
            if (ci > 0) out.appendSlice(allocator, ", ") catch return null;
            appendSqlLiteral(&out, value) catch return null;
        }
        out.append(allocator, ')') catch return null;
    }
    out.append(allocator, ';') catch return null;
    return out.toOwnedSlice(allocator) catch null;
}

fn encodePySqlValue(item: *c.PyObject, buf: *[256]u8) usize {
    if (py.isNone(item)) {
        @memcpy(buf[0..4], "null");
        return 4;
    }
    if (c.PyBool_Check(item) != 0) {
        if (item == @as(*c.PyObject, @ptrCast(&c._Py_TrueStruct))) {
            @memcpy(buf[0..4], "true");
            return 4;
        }
        @memcpy(buf[0..5], "false");
        return 5;
    }
    if (c.PyLong_Check(item) != 0) {
        const value = c.PyLong_AsLongLong(item);
        if (c.PyErr_Occurred() == null) {
            const formatted = std.fmt.bufPrint(buf, "{d}", .{value}) catch return 0;
            return formatted.len;
        }
        c.PyErr_Clear();
    }
    if (c.PyFloat_Check(item) != 0) {
        const value = c.PyFloat_AsDouble(item);
        if (c.PyErr_Occurred() == null) {
            const formatted = std.fmt.bufPrint(buf, "{d}", .{value}) catch return 0;
            return formatted.len;
        }
        c.PyErr_Clear();
    }
    if (c.PyUnicode_Check(item) != 0) {
        if (c.PyUnicode_AsUTF8(item)) |cs| {
            const s = std.mem.span(cs);
            const copy_len = @min(s.len, 255);
            @memcpy(buf[0..copy_len], s[0..copy_len]);
            return copy_len;
        }
        c.PyErr_Clear();
        return 0;
    }

    const str_obj = c.PyObject_Str(item) orelse return 0;
    defer c.Py_DecRef(str_obj);
    if (c.PyUnicode_AsUTF8(str_obj)) |cs| {
        const s = std.mem.span(cs);
        const copy_len = @min(s.len, 255);
        @memcpy(buf[0..copy_len], s[0..copy_len]);
        return copy_len;
    }
    c.PyErr_Clear();
    return 0;
}

fn execManyMultiValues(sql: []const u8, py_rows: *c.PyObject, max_rows: usize, cols_per_row: usize) ?i64 {
    const values_storage = allocator.alloc([256]u8, max_rows * cols_per_row) catch return null;
    defer allocator.free(values_storage);
    const row_views = allocator.alloc([][]const u8, max_rows) catch return null;
    defer allocator.free(row_views);
    const cell_views = allocator.alloc([]const u8, max_rows * cols_per_row) catch return null;
    defer allocator.free(cell_views);

    for (0..max_rows) |ri| {
        const row_obj = c.PyList_GetItem(py_rows, @intCast(ri)) orelse return null;
        const row_len: usize = @intCast(c.PyObject_Length(row_obj));
        if (row_len < cols_per_row) return null;

        row_views[ri] = cell_views[ri * cols_per_row ..][0..cols_per_row];
        for (0..cols_per_row) |ci| {
            const item = if (c.PyTuple_Check(row_obj) != 0)
                c.PyTuple_GetItem(row_obj, @intCast(ci))
            else
                c.PyList_GetItem(row_obj, @intCast(ci));
            if (item == null) return null;

            const cell_idx = ri * cols_per_row + ci;
            const len = encodePySqlValue(item.?, &values_storage[cell_idx]);
            row_views[ri][ci] = values_storage[cell_idx][0..len];
        }
    }

    const sql_owned = buildMultiInsertSql(sql, row_views[0..max_rows]) orelse return null;
    defer allocator.free(sql_owned);

    const gil_state = py_gil_save();
    const conn = acquireConn() orelse {
        py_gil_restore(gil_state);
        return null;
    };
    defer {
        releaseConn(conn);
        py_gil_restore(gil_state);
    }

    return conn.exec(sql_owned, .{}) catch null;
}

fn execManyDynamicProtocol(sql: []const u8, py_rows: *c.PyObject, max_rows: usize, cols_per_row: usize) ?i64 {
    const max_cells = max_rows * cols_per_row;
    const text_storage = allocator.alloc([256]u8, max_cells) catch return null;
    defer allocator.free(text_storage);
    const dynamic_cells = allocator.alloc(pg.DynamicValue, max_cells) catch return null;
    defer allocator.free(dynamic_cells);

    for (0..max_rows) |ri| {
        const row_obj = c.PyList_GetItem(py_rows, @intCast(ri)) orelse return null;
        const row_len: usize = @intCast(c.PyObject_Length(row_obj));
        if (row_len < cols_per_row) return null;

        for (0..cols_per_row) |ci| {
            const cell_idx = ri * cols_per_row + ci;
            const item = if (c.PyTuple_Check(row_obj) != 0)
                c.PyTuple_GetItem(row_obj, @intCast(ci))
            else
                c.PyList_GetItem(row_obj, @intCast(ci));
            if (item == null) {
                dynamic_cells[cell_idx] = .null;
                continue;
            }

            const py_item = item.?;
            if (py.isNone(py_item)) {
                dynamic_cells[cell_idx] = .null;
                continue;
            }
            if (c.PyBool_Check(py_item) != 0) {
                dynamic_cells[cell_idx] = .{ .bool = py_item == @as(*c.PyObject, @ptrCast(&c._Py_TrueStruct)) };
                continue;
            }
            if (c.PyLong_Check(py_item) != 0) {
                const v = c.PyLong_AsLongLong(py_item);
                if (c.PyErr_Occurred() != null) {
                    c.PyErr_Clear();
                } else {
                    dynamic_cells[cell_idx] = .{ .i64 = v };
                    continue;
                }
            }
            if (c.PyFloat_Check(py_item) != 0) {
                const v = c.PyFloat_AsDouble(py_item);
                if (c.PyErr_Occurred() != null) {
                    c.PyErr_Clear();
                } else {
                    dynamic_cells[cell_idx] = .{ .f64 = v };
                    continue;
                }
            }

            var text_len: usize = 0;
            if (c.PyUnicode_Check(py_item) != 0) {
                if (c.PyUnicode_AsUTF8(py_item)) |cs| {
                    const s = std.mem.span(cs);
                    text_len = @min(s.len, 255);
                    @memcpy(text_storage[cell_idx][0..text_len], s[0..text_len]);
                } else {
                    c.PyErr_Clear();
                }
            } else {
                const str_obj = c.PyObject_Str(py_item) orelse {
                    dynamic_cells[cell_idx] = .null;
                    continue;
                };
                defer c.Py_DecRef(str_obj);
                if (c.PyUnicode_AsUTF8(str_obj)) |cs| {
                    const s = std.mem.span(cs);
                    text_len = @min(s.len, 255);
                    @memcpy(text_storage[cell_idx][0..text_len], s[0..text_len]);
                } else {
                    c.PyErr_Clear();
                }
            }
            dynamic_cells[cell_idx] = .{ .text = text_storage[cell_idx][0..text_len] };
        }
    }

    const row_slices = allocator.alloc([]const pg.DynamicValue, max_rows) catch return null;
    defer allocator.free(row_slices);
    for (0..max_rows) |ri| {
        row_slices[ri] = dynamic_cells[ri * cols_per_row ..][0..cols_per_row];
    }

    const gil_state = py_gil_save();
    const conn = acquireConn() orelse {
        py_gil_restore(gil_state);
        return null;
    };
    defer {
        releaseConn(conn);
        py_gil_restore(gil_state);
    }

    return conn.execManyDynamic(sql, row_slices[0..max_rows], .{
        .cache_name = "db_exec_many_raw",
        .column_names = false,
    }) catch null;
}

// ── Python C API functions ───────────────────────────────────────────────────

pub fn db_configure(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var conn_str: [*c]const u8 = null;
    var pool_size: c_int = 16;
    if (c.PyArg_ParseTuple(args, "si", &conn_str, &pool_size) == 0) return null;

    const uri_str = std.mem.span(conn_str);
    const size: u16 = if (pool_size > 0 and pool_size <= 128) @intCast(pool_size) else 16;
    configureExecManyModeFromEnv();

    // Parse postgres://user:pass@host:port/database
    const uri = std.Uri.parse(uri_str) catch {
        py.setError("Invalid connection string: {s}", .{uri_str});
        return null;
    };

    // Extract host string from URI component
    // Extract strings from URI components (always use percent_encoded — safe for both)
    const host_str: []const u8 = if (uri.host) |h| h.percent_encoded else "127.0.0.1";
    const user_str: []const u8 = if (uri.user) |u| u.percent_encoded else "postgres";
    const db_name: []const u8 = if (uri.path.percent_encoded.len > 1) uri.path.percent_encoded[1..] else "postgres";
    const pw_str: ?[]const u8 = if (uri.password) |p| p.percent_encoded else null;

    db_pool = pg.Pool.init(allocator, .{
        .size = size,
        .connect = .{
            .port = uri.port,
            .host = host_str,
        },
        .auth = .{
            .username = user_str,
            .database = db_name,
            .password = pw_str,
        },
    }) catch {
        py.setError("Failed to connect to database: {s}", .{uri_str});
        return null;
    };

    logger.info("[DB] Pool initialized: {d} connections to {s}", .{ size, uri_str });

    // Auto-check env vars for cache control
    if (std.posix.getenv("TURBO_DISABLE_DB_CACHE")) |val| {
        if (std.mem.eql(u8, val, "1") or std.mem.eql(u8, val, "true")) {
            db_cache_enabled = false;
            logger.info("[DB] Cache DISABLED via TURBO_DISABLE_DB_CACHE", .{});
        }
    }
    if (std.posix.getenv("TURBO_DB_CACHE_TTL")) |val| {
        db_cache_ttl = std.fmt.parseInt(i64, val, 10) catch 30;
        logger.info("[DB] Cache TTL set to {d}s", .{db_cache_ttl});
    }

    return py.pyNone();
}

/// Check env vars for cache control — called at startup or from Python.
pub fn db_check_cache_env(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    if (std.posix.getenv("TURBO_DISABLE_DB_CACHE")) |val| {
        if (std.mem.eql(u8, val, "1") or std.mem.eql(u8, val, "true")) {
            db_cache_enabled = false;
            logger.info("[DB] Cache DISABLED via TURBO_DISABLE_DB_CACHE", .{});
        }
    }
    if (std.posix.getenv("TURBO_DB_CACHE_TTL")) |val| {
        db_cache_ttl = std.fmt.parseInt(i64, val, 10) catch 30;
        logger.info("[DB] Cache TTL set to {d}s", .{db_cache_ttl});
    }
    return py.pyNone();
}

pub fn db_add_route(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var method_c: [*c]const u8 = null;
    var path_c: [*c]const u8 = null;
    var op_c: [*c]const u8 = null;
    var table_c: [*c]const u8 = null;
    var pk_col_c: [*c]const u8 = null;
    var pk_param_c: [*c]const u8 = null;
    var columns_c: [*c]const u8 = null; // comma-separated column names

    if (c.PyArg_ParseTuple(args, "sssssss", &method_c, &path_c, &op_c, &table_c, &pk_col_c, &pk_param_c, &columns_c) == 0) return null;

    const method_s = std.mem.span(method_c);
    const path_s = std.mem.span(path_c);
    const op_s = std.mem.span(op_c);
    const table_s = std.mem.span(table_c);
    const pk_col_s = std.mem.span(pk_col_c);
    const pk_param_s = std.mem.span(pk_param_c);
    const columns_s = std.mem.span(columns_c);

    const op: DbOp = if (std.mem.eql(u8, op_s, "select_one"))
        .select_one
    else if (std.mem.eql(u8, op_s, "select_list"))
        .select_list
    else if (std.mem.eql(u8, op_s, "insert"))
        .insert
    else if (std.mem.eql(u8, op_s, "delete"))
        .delete
    else if (std.mem.eql(u8, op_s, "custom_query"))
        .custom_query
    else if (std.mem.eql(u8, op_s, "custom_query_single"))
        .custom_query_single
    else {
        py.setError("Invalid db op: {s}", .{op_s});
        return null;
    };

    // Validate table name for CRUD ops (custom queries pass SQL as table)
    if (op != .custom_query and op != .custom_query_single) {
        if (!isValidIdentifier(table_s)) {
            py.setError("Invalid table name: {s}", .{table_s});
            return null;
        }
    }

    // Parse column names (also used as param names for custom queries)
    var cols: [16][]const u8 = undefined;
    var ncols: usize = 0;
    if (columns_s.len > 0) {
        var col_iter = std.mem.splitScalar(u8, columns_s, ',');
        while (col_iter.next()) |col| {
            if (ncols >= 16) break;
            const trimmed = std.mem.trim(u8, col, " ");
            cols[ncols] = allocator.dupe(u8, trimmed) catch return null;
            ncols += 1;
        }
    }

    const columns_owned = allocator.dupe([]const u8, cols[0..ncols]) catch return null;
    var json_key_parts_buf: [16][]const u8 = undefined;
    for (cols[0..ncols], 0..) |col, i| {
        json_key_parts_buf[i] = std.fmt.allocPrint(allocator, "\"{s}\":", .{col}) catch return null;
    }
    const json_key_parts_owned = allocator.dupe([]const u8, json_key_parts_buf[0..ncols]) catch return null;
    const pk_col = if (pk_col_s.len > 0) allocator.dupe(u8, pk_col_s) catch return null else null;
    const pk_param = if (pk_param_s.len > 0) allocator.dupe(u8, pk_param_s) catch return null else null;
    const table = allocator.dupe(u8, table_s) catch return null;

    // For custom queries, columns_s contains the raw SQL (passed via the columns arg)
    // and pk_col_s contains comma-separated param names
    const custom_sql = if (op == .custom_query or op == .custom_query_single)
        allocator.dupe(u8, table_s) catch return null // table_s carries the SQL for custom queries
    else
        "";

    // For custom queries, parse param names from pk_col_s
    var pnames: [16][]const u8 = undefined;
    var npnames: usize = 0;
    if ((op == .custom_query or op == .custom_query_single) and pk_col_s.len > 0) {
        var pn_iter = std.mem.splitScalar(u8, pk_col_s, ',');
        while (pn_iter.next()) |pn| {
            if (npnames >= 16) break;
            const trimmed = std.mem.trim(u8, pn, " ");
            pnames[npnames] = allocator.dupe(u8, trimmed) catch return null;
            npnames += 1;
        }
    }
    const param_names_owned = allocator.dupe([]const u8, pnames[0..npnames]) catch return null;
    // Generate prepared statement cache name: "db_METHOD_path"
    var cache_name_counter: usize = 0;
    _ = @atomicRmw(usize, &cache_name_counter, .Add, 1, .seq_cst);
    const cache_name = std.fmt.allocPrint(allocator, "db_{s}_{s}", .{ method_s, path_s }) catch null;

    const entry = DbRouteEntry{
        .op = op,
        .table = table,
        .columns = columns_owned,
        .json_key_parts = json_key_parts_owned,
        .pk_column = pk_col,
        .pk_param = pk_param,
        .select_sql = if (pk_col) |pk| buildSelectOneSql(table, pk, columns_owned) else buildSelectListSql(table, columns_owned),
        .insert_sql = if (ncols > 0 and op == .insert) buildInsertSql(table, columns_owned) else "",
        .delete_sql = if (pk_col) |pk| buildDeleteSql(table, pk) else "",
        .custom_sql = custom_sql,
        .param_names = param_names_owned,
        .cache_name = cache_name,
        .schema = null,
    };

    const key = std.fmt.allocPrint(allocator, "{s} {s}", .{ method_s, path_s }) catch return null;
    getDbRoutes().put(key, entry) catch return null;

    // Register in router
    const rt = @import("server.zig").getRouter();
    rt.addRoute(method_s, path_s, key) catch return null;

    logger.debug("[DB] Registered: {s} {s} -> {s}.{s} ({s})", .{ method_s, path_s, table_s, if (pk_col) |pk| pk else "*", op_s });
    return py.pyNone();
}

// Execute SQL without returning rows (DDL, setup/teardown, multi-statement)
pub fn db_exec_raw(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var sql_ptr: [*c]const u8 = null;
    if (c.PyArg_ParseTuple(args, "s", &sql_ptr) == 0) return null;

    const sql = std.mem.span(sql_ptr);

    if (db_pool == null) {
        py.setError("Database not configured. Call configure_db() first.", .{});
        return null;
    }

    const gil_state = py_gil_save();

    const conn = acquireConn() orelse {
        py_gil_restore(gil_state);
        py.setError("Failed to acquire database connection", .{});
        return null;
    };

    const rows_affected = conn.exec(sql, .{}) catch {
        releaseConn(conn);
        py_gil_restore(gil_state);
        py.setError("Exec failed: {s}", .{sql});
        return null;
    };

    releaseConn(conn);
    py_gil_restore(gil_state);

    if (rows_affected) |n| {
        return c.PyLong_FromLongLong(n);
    }
    return py.pyNone();
}

// ── Raw query API (no HTTP, direct pg.zig from Python) ──────────────────────

const RawCell = struct { start: u32, len: u32, is_null: bool, oid: i32 };
const MAX_RAW_CELLS = 32768;
pub fn db_query_raw(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var sql_ptr: [*c]const u8 = null;
    var params_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "sO", &sql_ptr, &params_obj) == 0) return null;

    const sql = std.mem.span(sql_ptr);

    if (db_pool == null) {
        py.setError("Database not configured. Call configure_db() first.", .{});
        return null;
    }

    // Phase 1: Extract params from Python (GIL held)
    var param_values: [16][]const u8 = undefined;
    var param_count: usize = 0;
    // We need owned copies since we'll release the GIL
    var param_bufs: [16][256]u8 = undefined;

    if (params_obj) |plist| {
        if (c.PyList_Check(plist) != 0) {
            const n: usize = @intCast(c.PyList_Size(plist));
            for (0..@min(n, 16)) |i| {
                const item = c.PyList_GetItem(plist, @intCast(i));
                if (item == null) continue;
                // Handle bools specially (Python str(True) = "True", pg.zig needs "true")
                if (c.PyBool_Check(item) != 0) {
                    if (c.Py_IsTrue(item) != 0) {
                        @memcpy(param_bufs[param_count][0..4], "true");
                        param_values[param_count] = param_bufs[param_count][0..4];
                    } else {
                        @memcpy(param_bufs[param_count][0..5], "false");
                        param_values[param_count] = param_bufs[param_count][0..5];
                    }
                    param_count += 1;
                    continue;
                }
                const str_obj = c.PyObject_Str(item) orelse continue;
                defer c.Py_DecRef(str_obj);
                if (c.PyUnicode_AsUTF8(str_obj)) |cs| {
                    const s = std.mem.span(cs);
                    const copy_len = @min(s.len, 255);
                    @memcpy(param_bufs[param_count][0..copy_len], s[0..copy_len]);
                    param_values[param_count] = param_bufs[param_count][0..copy_len];
                    param_count += 1;
                }
            }
        }
    }

    // Phase 2: Release GIL, do Postgres I/O (true parallel threading)
    const gil_state = py_gil_save();

    const conn = acquireConn() orelse {
        py_gil_restore(gil_state);
        py.setError("Failed to acquire database connection", .{});
        return null;
    };

    const result = execWithParams(conn, sql, param_values[0..param_count], null) orelse {
        releaseConn(conn);
        py_gil_restore(gil_state);
        py.setError("Query failed: {s}", .{sql});
        return null;
    };
    // Buffer row values as strings while GIL is released
    // Use a flat buffer with offsets to avoid huge struct arrays
    // Buffer row values while GIL is released (heap allocated for large results)
    const flat_buf = allocator.alloc(u8, 2 * 1024 * 1024) catch {
        releaseConn(conn);
        py_gil_restore(gil_state);
        py.setError("Out of memory for query result buffer", .{});
        return null;
    };
    defer allocator.free(flat_buf);
    var flat_pos: usize = 0;

    const cells = allocator.alloc(RawCell, MAX_RAW_CELLS) catch {
        releaseConn(conn);
        py_gil_restore(gil_state);
        py.setError("Out of memory for cell buffer", .{});
        return null;
    };
    defer allocator.free(cells);

    var col_name_ptrs: [32][]const u8 = undefined;
    var col_name_storage: [32][64]u8 = undefined; // owned copies of column names
    var cell_count: usize = 0;
    var num_cols: usize = 0;
    var num_rows: usize = 0;

    const col_names = result.column_names;
    num_cols = @min(col_names.len, 32);
    for (0..num_cols) |ci| {
        const name = col_names[ci];
        const copy_len = @min(name.len, 63);
        @memcpy(col_name_storage[ci][0..copy_len], name[0..copy_len]);
        col_name_ptrs[ci] = col_name_storage[ci][0..copy_len];
    }

    while (result.next() catch null) |row| {
        if (cell_count + num_cols > MAX_RAW_CELLS) break;
        for (0..num_cols) |ci| {
            const value = row.values[ci];
            if (value.is_null) {
                cells[cell_count] = .{ .start = 0, .len = 0, .is_null = true, .oid = 0 };
            } else {
                // Store raw binary data + OID for direct decoding in Phase 3
                const data = value.data;
                const copy_len = @min(data.len, flat_buf.len - flat_pos);
                if (copy_len < data.len) break; // buffer full
                @memcpy(flat_buf[flat_pos..][0..copy_len], data[0..copy_len]);
                cells[cell_count] = .{
                    .start = @intCast(flat_pos),
                    .len = @intCast(copy_len),
                    .is_null = false,
                    .oid = row.oids[ci],
                };
                flat_pos += copy_len;
            }
            cell_count += 1;
        }
        num_rows += 1;
    }
    result.deinit();
    releaseConn(conn);

    // Phase 3: Reacquire GIL, build Python objects
    py_gil_restore(gil_state);

    // Pre-intern column name keys (created once, reused for all rows)
    var py_keys: [32]?*c.PyObject = [_]?*c.PyObject{null} ** 32;
    for (0..num_cols) |ci| {
        py_keys[ci] = c.PyUnicode_FromStringAndSize(
            @ptrCast(col_name_ptrs[ci].ptr),
            @intCast(col_name_ptrs[ci].len),
        );
        if (py_keys[ci] == null) {
            // Clean up already created keys
            for (0..ci) |j| {
                if (py_keys[j]) |k| c.Py_DecRef(k);
            }
            return null;
        }
    }

    const py_list = c.PyList_New(@intCast(num_rows)) orelse {
        for (0..num_cols) |ci| {
            if (py_keys[ci]) |k| c.Py_DecRef(k);
        }
        return null;
    };

    for (0..num_rows) |ri| {
        const py_dict = c._PyDict_NewPresized(@intCast(num_cols)) orelse {
            c.Py_DecRef(py_list);
            for (0..num_cols) |ci| {
                if (py_keys[ci]) |k| c.Py_DecRef(k);
            }
            return null;
        };

        for (0..num_cols) |ci| {
            const py_key = py_keys[ci].?;

            var py_val: *c.PyObject = undefined;

            const cell_idx = ri * num_cols + ci;
            const cell = cells[cell_idx];

            if (cell.is_null) {
                py_val = py.pyNone();
            } else {
                const data = flat_buf[cell.start..][0..cell.len];
                // Decode binary data directly based on Postgres OID
                switch (cell.oid) {
                    // Integers: int2, int4, int8
                    21 => py_val = c.PyLong_FromLong(@as(c_long, std.mem.readInt(i16, data[0..2], .big))),
                    23 => py_val = c.PyLong_FromLong(@as(c_long, std.mem.readInt(i32, data[0..4], .big))),
                    20 => py_val = c.PyLong_FromLongLong(std.mem.readInt(i64, data[0..8], .big)),
                    // Float: float4, float8
                    700 => py_val = c.PyFloat_FromDouble(@floatCast(@as(f32, @bitCast(std.mem.readInt(u32, data[0..4], .big))))),
                    701 => py_val = c.PyFloat_FromDouble(@bitCast(std.mem.readInt(u64, data[0..8], .big))),
                    // Bool
                    16 => py_val = if (data[0] != 0) py.pyTrue() else py.pyFalse(),
                    // OID (uint32)
                    26 => py_val = c.PyLong_FromUnsignedLong(@as(c_ulong, std.mem.readInt(u32, data[0..4], .big))),
                    // Text, varchar, name, char(n), unknown
                    25, 1043, 19, 1042, 705, 18 => {
                        py_val = c.PyUnicode_DecodeUTF8(@ptrCast(data.ptr), @intCast(data.len), "replace") orelse {
                            c.Py_DecRef(py_dict);
                            c.Py_DecRef(py_list);
                            return null;
                        };
                    },
                    // Everything else: try as UTF-8 string
                    else => {
                        py_val = c.PyUnicode_DecodeUTF8(@ptrCast(data.ptr), @intCast(data.len), "replace") orelse {
                            c.Py_DecRef(py_dict);
                            c.Py_DecRef(py_list);
                            return null;
                        };
                    },
                }
            }

            _ = c.PyDict_SetItem(py_dict, py_key, py_val);
            c.Py_DecRef(py_val);
        }

        c.PyList_SET_ITEM(py_list, @intCast(ri), py_dict);
    }

    // Clean up interned keys
    for (0..num_cols) |ci| {
        if (py_keys[ci]) |k| c.Py_DecRef(k);
    }

    return py_list;
}

pub fn db_exec_many_raw(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var sql_ptr: [*c]const u8 = null;
    var rows_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "sO", &sql_ptr, &rows_obj) == 0) return null;

    const sql = std.mem.span(sql_ptr);
    if (db_pool == null) {
        py.setError("Database not configured. Call configure_db() first.", .{});
        return null;
    }

    const py_rows = rows_obj orelse {
        py.setError("rows must be a list", .{});
        return null;
    };
    if (c.PyList_Check(py_rows) == 0) {
        py.setError("rows must be a list", .{});
        return null;
    }

    const row_count_py: usize = @intCast(c.PyList_Size(py_rows));
    if (row_count_py == 0) return c.PyLong_FromLongLong(0);
    const max_rows = @min(row_count_py, 10000);

    const first_row = c.PyList_GetItem(py_rows, 0) orelse {
        py.setError("rows must contain sequences", .{});
        return null;
    };
    if (c.PyList_Check(first_row) == 0 and c.PyTuple_Check(first_row) == 0) {
        py.setError("rows must contain sequences", .{});
        return null;
    }

    const cols_per_row: usize = @min(@as(usize, @intCast(c.PyObject_Length(first_row))), 8);
    if (cols_per_row == 0) return c.PyLong_FromLongLong(0);

    const total_rows = switch (exec_many_mode) {
        .multi_values => execManyMultiValues(sql, py_rows, max_rows, cols_per_row),
        .dynamic_protocol => execManyDynamicProtocol(sql, py_rows, max_rows, cols_per_row),
    } orelse {
        py.setError("Batch execution failed: {s}", .{sql});
        return null;
    };
    return c.PyLong_FromLongLong(total_rows);
}

// ── COPY FROM STDIN API (bulk insert from Python) ─────────────────────────────

pub fn db_copy_from(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var table_ptr: [*c]const u8 = null;
    var cols_obj: ?*c.PyObject = null;
    var rows_obj: ?*c.PyObject = null;
    if (c.PyArg_ParseTuple(args, "sOO", &table_ptr, &cols_obj, &rows_obj) == 0) return null;

    // Copy table name to owned storage
    const table_raw = std.mem.span(table_ptr);
    var table_storage: [128]u8 = undefined;
    const tlen = @min(table_raw.len, 127);
    @memcpy(table_storage[0..tlen], table_raw[0..tlen]);
    const table = table_storage[0..tlen];

    if (db_pool == null) {
        py.setError("Database not configured. Call configure_db() first.", .{});
        return null;
    }

    const col_list = cols_obj orelse {
        py.setError("columns must be a list", .{});
        return null;
    };
    const row_list = rows_obj orelse {
        py.setError("rows must be a list", .{});
        return null;
    };

    if (c.PyList_Check(col_list) == 0 or c.PyList_Check(row_list) == 0) {
        py.setError("columns and rows must be lists", .{});
        return null;
    }

    const num_cols_i: isize = c.PyList_Size(col_list);
    const num_rows_i: isize = c.PyList_Size(row_list);
    if (num_cols_i <= 0 or num_rows_i <= 0) return c.PyLong_FromLongLong(0);
    const num_cols: usize = @intCast(num_cols_i);
    const num_rows: usize = @intCast(num_rows_i);
    const cols_to_use = @min(num_cols, 32);
    const max_rows = @min(num_rows, 10000);

    // Column names (stack)
    var col_storage: [32][64]u8 = undefined;
    var col_slices: [32][]const u8 = undefined;
    for (0..cols_to_use) |i| {
        const item = c.PyList_GetItem(col_list, @intCast(i)) orelse continue;
        const str_obj = c.PyObject_Str(item) orelse continue;
        defer c.Py_DecRef(str_obj);
        if (c.PyUnicode_AsUTF8(str_obj)) |cs| {
            const s = std.mem.span(cs);
            const copy_len = @min(s.len, 63);
            @memcpy(col_storage[i][0..copy_len], s[0..copy_len]);
            col_slices[i] = col_storage[i][0..copy_len];
        }
    }

    // Check if all rows are the same Python object (common: [row] * N)
    const first_row_obj = c.PyList_GetItem(row_list, 0);
    var all_same = true;
    for (1..@min(max_rows, 3)) |i| {
        if (c.PyList_GetItem(row_list, @intCast(i)) != first_row_obj) {
            all_same = false;
            break;
        }
    }

    if (all_same and first_row_obj != null) {
        // Optimization: extract one row, repeat it for copyFrom
        var one_row_storage: [32][256]u8 = undefined;
        var one_row_slices: [32][]const u8 = undefined;

        const row_obj = first_row_obj.?;
        const row_len: usize = @intCast(c.PyObject_Length(row_obj));
        for (0..@min(row_len, cols_to_use)) |ci| {
            const item = if (c.PyTuple_Check(row_obj) != 0)
                c.PyTuple_GetItem(row_obj, @intCast(ci))
            else
                c.PyList_GetItem(row_obj, @intCast(ci));
            if (item) |it| {
                const str_obj = c.PyObject_Str(it) orelse {
                    one_row_slices[ci] = one_row_storage[ci][0..0];
                    continue;
                };
                defer c.Py_DecRef(str_obj);
                if (c.PyUnicode_AsUTF8(str_obj)) |cs| {
                    const s = std.mem.span(cs);
                    const copy_len = @min(s.len, 255);
                    @memcpy(one_row_storage[ci][0..copy_len], s[0..copy_len]);
                    one_row_slices[ci] = one_row_storage[ci][0..copy_len];
                } else {
                    one_row_slices[ci] = one_row_storage[ci][0..0];
                }
            } else {
                one_row_slices[ci] = one_row_storage[ci][0..0];
            }
        }

        // Build row_slices: all pointing to the same one_row_slices
        const row_slices = allocator.alloc([]const []const u8, max_rows) catch {
            py.setError("Out of memory for COPY row slices", .{});
            return null;
        };
        defer allocator.free(row_slices);

        // Each row_slices[i] must be a separate slice of []const u8
        // But they can all point to the same underlying data
        const cell_slices = allocator.alloc([]const u8, cols_to_use) catch {
            py.setError("Out of memory for COPY cell slices", .{});
            return null;
        };
        defer allocator.free(cell_slices);
        for (0..cols_to_use) |ci| {
            cell_slices[ci] = one_row_slices[ci];
        }
        for (0..max_rows) |ri| {
            row_slices[ri] = cell_slices[0..cols_to_use];
        }

        // Release GIL, do COPY I/O
        const gil_state = py_gil_save();
        const conn = acquireConn() orelse {
            py_gil_restore(gil_state);
            py.setError("Failed to acquire database connection", .{});
            return null;
        };

        const row_count = conn.copyFrom(table, col_slices[0..cols_to_use], row_slices[0..max_rows]) catch {
            releaseConn(conn);
            py_gil_restore(gil_state);
            py.setError("COPY FROM failed for table: {s}", .{table});
            return null;
        };

        releaseConn(conn);
        py_gil_restore(gil_state);
        return c.PyLong_FromLongLong(row_count);
    }

    // General case: different rows — extract all
    const max_cells = max_rows * cols_to_use;
    const val_storage = allocator.alloc([256]u8, max_cells) catch {
        py.setError("Out of memory for COPY row buffer", .{});
        return null;
    };
    defer allocator.free(val_storage);
    const val_lens = allocator.alloc(usize, max_cells) catch {
        py.setError("Out of memory for COPY len buffer", .{});
        return null;
    };
    defer allocator.free(val_lens);

    for (0..max_rows) |ri| {
        const row_obj = c.PyList_GetItem(row_list, @intCast(ri)) orelse continue;
        if (c.PyList_Check(row_obj) == 0 and c.PyTuple_Check(row_obj) == 0) continue;
        const row_len: usize = @intCast(c.PyObject_Length(row_obj));
        for (0..@min(row_len, cols_to_use)) |ci| {
            const cell_idx = ri * cols_to_use + ci;
            const item = if (c.PyTuple_Check(row_obj) != 0)
                c.PyTuple_GetItem(row_obj, @intCast(ci))
            else
                c.PyList_GetItem(row_obj, @intCast(ci));
            if (item == null) {
                val_lens[cell_idx] = 0;
                continue;
            }
            const str_obj = c.PyObject_Str(item.?) orelse {
                val_lens[cell_idx] = 0;
                continue;
            };
            defer c.Py_DecRef(str_obj);
            if (c.PyUnicode_AsUTF8(str_obj)) |cs| {
                const s = std.mem.span(cs);
                const copy_len = @min(s.len, 255);
                @memcpy(val_storage[cell_idx][0..copy_len], s[0..copy_len]);
                val_lens[cell_idx] = copy_len;
            } else {
                val_lens[cell_idx] = 0;
            }
        }
    }

    const row_slices = allocator.alloc([]const []const u8, max_rows) catch {
        py.setError("Out of memory for COPY row slices", .{});
        return null;
    };
    defer allocator.free(row_slices);
    const cell_slices = allocator.alloc([]const u8, max_cells) catch {
        py.setError("Out of memory for COPY cell slices", .{});
        return null;
    };
    defer allocator.free(cell_slices);

    for (0..max_rows) |ri| {
        for (0..cols_to_use) |ci| {
            const cell_idx = ri * cols_to_use + ci;
            cell_slices[cell_idx] = val_storage[cell_idx][0..val_lens[cell_idx]];
        }
        row_slices[ri] = cell_slices[ri * cols_to_use ..][0..cols_to_use];
    }

    const gil_state = py_gil_save();
    const conn = acquireConn() orelse {
        py_gil_restore(gil_state);
        py.setError("Failed to acquire database connection", .{});
        return null;
    };

    const row_count = conn.copyFrom(table, col_slices[0..cols_to_use], row_slices[0..max_rows]) catch {
        releaseConn(conn);
        py_gil_restore(gil_state);
        py.setError("COPY FROM failed for table: {s}", .{table});
        return null;
    };

    releaseConn(conn);
    py_gil_restore(gil_state);
    return c.PyLong_FromLongLong(row_count);
}
