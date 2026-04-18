// Generic bounded response cache — thread-safe string→V map with a max entry cap.

const std = @import("std");

/// A thread-safe, bounded string-keyed cache.
/// Once `max_entries` is reached, new insertions are silently dropped.
/// Callers own the lifecycle of values passed in — the cache does NOT free values on eviction.
pub fn BoundedCache(comptime V: type) type {
    return struct {
        const Self = @This();

        map: std.StringHashMap(V),
        lock: std.c.pthread_mutex_t = std.c.PTHREAD_MUTEX_INITIALIZER,
        count: usize = 0,
        max_entries: usize,
        allocator: std.mem.Allocator,

        pub fn init(allocator: std.mem.Allocator, max_entries: usize) Self {
            return .{
                .map = std.StringHashMap(V).init(allocator),
                .lock = .{},
                .count = 0,
                .max_entries = max_entries,
                .allocator = allocator,
            };
        }

        pub fn deinit(self: *Self) void {
            // Free all duped keys
            var it = self.map.keyIterator();
            while (it.next()) |key_ptr| {
                self.allocator.free(key_ptr.*);
            }
            _ = std.c.pthread_mutex_destroy(&self.lock);
            self.map.deinit();
        }

        /// Look up a cached value. Returns null if not present.
        pub fn get(self: *Self, key: []const u8) ?V {
            _ = std.c.pthread_mutex_lock(&self.lock);
            defer _ = std.c.pthread_mutex_unlock(&self.lock);
            return self.map.get(key);
        }

        /// Insert a key-value pair. Silently drops if at capacity or key already exists.
        /// The key is duped internally; the caller owns the value.
        pub fn put(self: *Self, key: []const u8, value: V) void {
            _ = std.c.pthread_mutex_lock(&self.lock);
            defer _ = std.c.pthread_mutex_unlock(&self.lock);

            if (self.count >= self.max_entries) return;

            const key_dupe = self.allocator.dupe(u8, key) catch return;
            const gop = self.map.getOrPut(key_dupe) catch {
                self.allocator.free(key_dupe);
                return;
            };

            if (gop.found_existing) {
                self.allocator.free(key_dupe);
                return;
            }

            gop.value_ptr.* = value;
            self.count += 1;
        }
    };
}

// ── Tests ───────────────────────────────────────────────────────────────────

test "BoundedCache basic get/put" {
    var cache = BoundedCache([]const u8).init(std.testing.allocator, 100);
    defer cache.deinit();

    cache.put("key1", "value1");
    try std.testing.expectEqualStrings("value1", cache.get("key1").?);
    try std.testing.expect(cache.get("missing") == null);
}

test "BoundedCache respects max_entries" {
    var cache = BoundedCache(u32).init(std.testing.allocator, 2);
    defer cache.deinit();

    cache.put("a", 1);
    cache.put("b", 2);
    cache.put("c", 3); // should be silently dropped

    try std.testing.expectEqual(@as(?u32, 1), cache.get("a"));
    try std.testing.expectEqual(@as(?u32, 2), cache.get("b"));
    try std.testing.expect(cache.get("c") == null);
}

test "BoundedCache duplicate key is no-op" {
    var cache = BoundedCache(u32).init(std.testing.allocator, 10);
    defer cache.deinit();

    cache.put("x", 1);
    cache.put("x", 2); // duplicate — should not overwrite or increment count

    try std.testing.expectEqual(@as(?u32, 1), cache.get("x"));
    try std.testing.expectEqual(@as(usize, 1), cache.count);
}
