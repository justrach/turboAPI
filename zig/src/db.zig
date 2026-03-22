// db.zig — Zig-native Postgres via pg.zig
// Zero-Python CRUD: HTTP request → dhi validate → pg.zig query → JSON response
// No GIL acquired at any point.

const std = @import("std");
const pg = @import("pg");
const py = @import("py.zig");
const c = py.c;
const router_mod = @import("router.zig");
const dhi = @import("dhi_validator.zig");

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

fn isDbCacheEnabled() bool {
    if (!db_cache_checked_env) {
        db_cache_checked_env = true;
        if (std.posix.getenv("TURBO_DISABLE_DB_CACHE")) |val| {
            if (std.mem.eql(u8, val, "1") or std.mem.eql(u8, val, "true")) {
                db_cache_enabled = false;
                std.debug.print("[DB] Cache DISABLED via TURBO_DISABLE_DB_CACHE\n", .{});
            }
        }
    }
    return db_cache_enabled;
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

fn buildSelectOneSql(table: []const u8, pk_column: []const u8) []const u8 {
    return std.fmt.allocPrint(allocator, "SELECT * FROM {s} WHERE {s} = $1", .{ table, pk_column }) catch "";
}

fn buildSelectListSql(table: []const u8) []const u8 {
    return std.fmt.allocPrint(allocator, "SELECT * FROM {s} LIMIT $1 OFFSET $2", .{table}) catch "";
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
            const pk_val = params.get(pk_param) orelse {
                sendResponseFn(stream, 400, "application/json", "{\"error\": \"Missing primary key\"}");
                return;
            };

            // Cache check — build cache key from table + pk value
            var cache_key_buf: [256]u8 = undefined;
            const cache_key = std.fmt.bufPrint(&cache_key_buf, "GET:{s}:{s}", .{ entry.table, pk_val }) catch "";
            if (cache_key.len > 0) {
                if (cacheGet(cache_key)) |cached_body| {
                    sendResponseFn(stream, 200, "application/json", cached_body);
                    return;
                }
            }

            const conn = acquireConn() orelse {
                sendResponseFn(stream, 503, "application/json", "{\"error\": \"Database connection unavailable\"}");
                return;
            };
            defer releaseConn(conn);

            var result = conn.queryOpts(entry.select_sql, .{pk_val}, .{ .column_names = true, .cache_name = entry.cache_name }) catch {
                sendResponseFn(stream, 500, "application/json", "{\"error\": \"Query failed\"}");
                return;
            };
            defer result.deinit();

            if (result.next() catch null) |row| {
                var json_buf: [8192]u8 = undefined;
                const json = serializeRow(row, result.column_names, &json_buf) catch {
                    sendResponseFn(stream, 500, "application/json", "{\"error\": \"Serialization failed\"}");
                    return;
                };
                // Cache the response
                if (cache_key.len > 0) {
                    cachePut(cache_key, json, entry.table);
                }
                sendResponseFn(stream, 200, "application/json", json);
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
                    if (std.mem.indexOf(u8, pair, "limit=")) |idx| {
                        limit = pair[idx + 6 ..];
                    } else if (std.mem.indexOf(u8, pair, "offset=")) |idx| {
                        offset = pair[idx + 7 ..];
                    }
                }
            }

            // Cache check for list queries
            var cache_key_buf: [256]u8 = undefined;
            const cache_key = std.fmt.bufPrint(&cache_key_buf, "LIST:{s}:{s}:{s}", .{ entry.table, limit, offset }) catch "";
            if (cache_key.len > 0) {
                if (cacheGet(cache_key)) |cached_body| {
                    sendResponseFn(stream, 200, "application/json", cached_body);
                    return;
                }
            }

            const conn = acquireConn() orelse {
                sendResponseFn(stream, 503, "application/json", "{\"error\": \"Database connection unavailable\"}");
                return;
            };
            defer releaseConn(conn);

            var result = conn.queryOpts(entry.select_sql, .{ limit, offset }, .{ .column_names = true, .cache_name = entry.cache_name }) catch {
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
                const row_json = serializeRow(row, result.column_names, &row_buf) catch break;
                if (out_pos + row_json.len + 2 > out_buf.len) break;
                @memcpy(out_buf[out_pos..][0..row_json.len], row_json);
                out_pos += row_json.len;
                row_count += 1;
            }

            out_buf[out_pos] = ']';
            out_pos += 1;

            const response_body = out_buf[0..out_pos];
            if (cache_key.len > 0) {
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

            var values: [16][]const u8 = undefined;
            const ncols = @min(entry.columns.len, 16);

            for (entry.columns[0..ncols], 0..) |col, i| {
                if (obj.get(col)) |val| {
                    values[i] = switch (val) {
                        .string => |s| s,
                        .integer => |n| std.fmt.allocPrint(allocator, "{d}", .{n}) catch "",
                        .float => |f| std.fmt.allocPrint(allocator, "{d}", .{f}) catch "",
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

            for (entry.param_names) |pname| {
                if (param_count >= 16) break;
                if (params.get(pname)) |v| {
                    param_values[param_count] = v;
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
                                param_count += 1;
                                found = true;
                                break;
                            }
                        }
                    }
                    if (!found) {
                        param_values[param_count] = "";
                        param_count += 1;
                    }
                }
            }

            // Cache check
            var cache_key_buf: [512]u8 = undefined;
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
            const cache_key = cache_key_buf[0..ck_pos];

            if (isDbCacheEnabled()) {
                if (cacheGet(cache_key)) |cached_body| {
                    sendResponseFn(stream, 200, "application/json", cached_body);
                    return;
                }
            }

            const conn = acquireConn() orelse {
                sendResponseFn(stream, 503, "application/json", "{\"error\": \"Database connection unavailable\"}");
                return;
            };
            defer releaseConn(conn);

            const result_opt = execWithParams(conn, entry.custom_sql, param_values[0..param_count], entry.cache_name);
            if (result_opt) |result| {
                defer result.deinit();

                if (entry.op == .custom_query_single) {
                    // Single row
                    if (result.next() catch null) |row| {
                        var json_buf: [8192]u8 = undefined;
                        const json = serializeRow(row, result.column_names, &json_buf) catch {
                            sendResponseFn(stream, 500, "application/json", "{\"error\": \"Serialization failed\"}");
                            return;
                        };
                        cachePut(cache_key, json, entry.table);
                        sendResponseFn(stream, 200, "application/json", json);
                    } else {
                        sendResponseFn(stream, 404, "application/json", "{\"error\": \"Not found\"}");
                    }
                } else {
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
                    cachePut(cache_key, resp, entry.table);
                    sendResponseFn(stream, 200, "application/json", resp);
                }
            } else {
                sendResponseFn(stream, 500, "application/json", "{\"error\": \"Query failed\"}");
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

// ── Python C API functions ───────────────────────────────────────────────────

pub fn db_configure(_: ?*c.PyObject, args: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    var conn_str: [*c]const u8 = null;
    var pool_size: c_int = 16;
    if (c.PyArg_ParseTuple(args, "si", &conn_str, &pool_size) == 0) return null;

    const uri_str = std.mem.span(conn_str);
    const size: u16 = if (pool_size > 0 and pool_size <= 128) @intCast(pool_size) else 16;

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

    std.debug.print("[DB] Pool initialized: {d} connections to {s}\n", .{ size, uri_str });

    // Auto-check env vars for cache control
    if (std.posix.getenv("TURBO_DISABLE_DB_CACHE")) |val| {
        if (std.mem.eql(u8, val, "1") or std.mem.eql(u8, val, "true")) {
            db_cache_enabled = false;
            std.debug.print("[DB] Cache DISABLED via TURBO_DISABLE_DB_CACHE\n", .{});
        }
    }
    if (std.posix.getenv("TURBO_DB_CACHE_TTL")) |val| {
        db_cache_ttl = std.fmt.parseInt(i64, val, 10) catch 30;
        std.debug.print("[DB] Cache TTL set to {d}s\n", .{db_cache_ttl});
    }

    return py.pyNone();
}

/// Check env vars for cache control — called at startup or from Python.
pub fn db_check_cache_env(_: ?*c.PyObject, _: ?*c.PyObject) callconv(.c) ?*c.PyObject {
    if (std.posix.getenv("TURBO_DISABLE_DB_CACHE")) |val| {
        if (std.mem.eql(u8, val, "1") or std.mem.eql(u8, val, "true")) {
            db_cache_enabled = false;
            std.debug.print("[DB] Cache DISABLED via TURBO_DISABLE_DB_CACHE\n", .{});
        }
    }
    if (std.posix.getenv("TURBO_DB_CACHE_TTL")) |val| {
        db_cache_ttl = std.fmt.parseInt(i64, val, 10) catch 30;
        std.debug.print("[DB] Cache TTL set to {d}s\n", .{db_cache_ttl});
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
        .pk_column = pk_col,
        .pk_param = pk_param,
        .select_sql = if (pk_col) |pk| buildSelectOneSql(table, pk) else buildSelectListSql(table),
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

    std.debug.print("[DB] Registered: {s} {s} -> {s}.{s} ({s})\n", .{ method_s, path_s, table_s, if (pk_col) |pk| pk else "*", op_s });
    return py.pyNone();
}


// ── Raw query API (no HTTP, direct pg.zig from Python) ──────────────────────

const RawCell = struct { start: u32, len: u16, is_null: bool, oid: i32 };
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
                if (c.Py_IsTrue(item) != 0) {
                    @memcpy(param_bufs[param_count][0..4], "true");
                    param_values[param_count] = param_bufs[param_count][0..4];
                    param_count += 1;
                    continue;
                }
                if (c.Py_IsFalse(item) != 0) {
                    @memcpy(param_bufs[param_count][0..5], "false");
                    param_values[param_count] = param_bufs[param_count][0..5];
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
