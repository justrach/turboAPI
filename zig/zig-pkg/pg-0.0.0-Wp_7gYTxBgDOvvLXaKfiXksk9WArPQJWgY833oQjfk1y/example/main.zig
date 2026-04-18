const std = @import("std");
const builtin = @import("builtin");

const pg = @import("pg");

pub const log = std.log.scoped(.example);

pub fn main() !void {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    const allocator = if (builtin.mode == .Debug) gpa.allocator() else std.heap.c_allocator;

    // While a connection can be created directly, pools should be used in most
    // cases. The pool's `acquire` method, to get a connection is thread-safe.
    // The pool may start 1 background thread to reconnect disconnected
    // connections (or connections in an invalid state).
    var pool = pg.Pool.init(allocator, .{
        .size = 5,
        .connect = .{
            .port = 5432,
            .host = "127.0.0.1",
        },
        .auth = .{
            .username = "postgres",
            .database = "postgres",
            .timeout = 10_000,
        }
    }) catch |err| {
        log.err("Failed to connect: {}", .{err});
        std.posix.exit(1);
    };
    defer pool.deinit();



    // One-off commands can be executed directly using the pool using the
    // exec, execOpts, query, queryOpts, row, rowOpts functions. But, due to
    // Zig's lack of error payloads, if these fail, you won't be able to retrieve
    // a more detailed error
    _ = try pool.exec("drop table if exists pg_example_users", .{});


    // We're using a block to scope the defer conn.release(). In your own code
    // the scope might naturally be a function or if block. Remember that Zig's
    // defer thankfully executes at the end of the block (unlike Go where defer
    // executes at the end of the function).
    {
        // You can acquire/release connections from the pool. Ideal if you want
        // to execute multiple statements and also exposes a more detailed error.
        var conn = try pool.acquire();
        defer conn.release();

        // exec returns the # of rows affected for insert/select/delete
        _ = conn.exec("create table pg_example_users (id integer, name text)", .{}) catch |err| {
            if (conn.err) |pg_err| {
                // conn.err is an optional PostgreSQL error. It has many fields,
                // many of which are nullable, but the `message`, `code` and
                // `severity` are always present.
                log.err("create failure: {s}", .{pg_err.message});
            }
            return err;
        };
    }


    // Of course, exec can take parameters:
    _ = try pool.exec(
        "insert into pg_example_users (id, name) values ($1, $2), ($3, $4)",
        .{1, "Leto", 2, "Ghanima"}
    );


    {
        log.info("Example 1", .{});
        // we can fetch a single row:
        var conn = try pool.acquire();
        defer conn.release();

        var row = (try conn.row("select name from pg_example_users where id = $1", .{1})) orelse unreachable;
        // having to deal with row.deinit() is an unfortunate consequence of the
        // conn.row and pool.row API. Sorry!
        defer row.deinit() catch {};

        // name will become invalid after row.deinit() is called. dupe it if you
        // need it to live longer.
        const name = try row.get([]const u8, 0);
        log.info("User 1: {s}", .{name});
    }

    {
        log.info("\n\nExample 2", .{});
        // or we can fetch multiple rows:
        var conn = try pool.acquire();
        defer conn.release();

        var result = try conn.query("select * from pg_example_users order by id", .{});
        defer result.deinit();

        while (try result.next()) |row| {
            const id = try row.get(i32, 0);
            // string values are only valid until the next call to next()
            // dupe the value if needed
            const name = try row.get([]const u8, 1);
            log.info("User {d}: {s}", .{id, name});
        }
    }

    {
        log.info("\n\nExample 3", .{});
        // pgz uses a configurable read and write buffer to communicate with Postgresql.
        // Larger messages require dynamic allocation. By default this uses the allocator
        // given to `Pool.init` or `Conn.open`. A different allocator can be specified
        // on a per-query basis. For example, if you're using an HTTP framework that
        // gives you a per-request arena, you could use that arena
        var conn = try pool.acquire();
        defer conn.release();

        // Because we pass this allocator to queryOpts, *IF* pg needs to allocate
        // to read the response, it'll use this allocator.
        var arena = std.heap.ArenaAllocator.init(allocator);
        defer arena.deinit();

        // use queryOpts, execOpts or rowOpts when specifying optional parameters
        var result = try conn.queryOpts("select * from pg_example_users order by id", .{}, .{.allocator = arena.allocator()});
        defer result.deinit();

        while (try result.next()) |row| {
            const id = try row.get(i32, 0);
            // string values are only valid until the next call to next()
            // dupe the value if needed
            const name = try row.get([]const u8, 1);
            log.info("User {d}: {s}", .{id, name});
        }
    }

    {
        log.info("\n\nExample 4", .{});
        // We can bind and fetch arrays. This simple statement showcases both:
        var row = (try pool.row("select $1::bool[]", .{[_]bool{true, false, false}})) orelse unreachable;

        // again, sorry that row.deinit() can error.
        defer row.deinit() catch {};

        var it = try row.get(pg.Iterator(bool), 0);
        while (it.next()) |value| {
            log.info("{any}", .{value});
        }

        // There's a `alloc` helper on the iterator too, to turn it into a slice
        // const values = try it.alloc(allocator);
        // defer allocator.free(values);
    }

    {
        log.info("\n\nExample 5", .{});
        // Instead of `row.get`, you can use `row.getCol` to get a column by name
        // But to work, you must tell pgz to load the column_names
        // exec, query and row all have variants that take an option:
        // execOpts, queryOpts and rowOpts
        var row = (try pool.rowOpts("select $1 as name", .{"teg"}, .{.column_names = true})) orelse unreachable;
        defer row.deinit() catch {};

        log.info("{s}", .{try row.getCol([]const u8, "name")});
    }

    {
        log.info("\n\nExample 6", .{});
        // There's a cost to looking up a value by name. If you're going to do
        // it in a loop, consider storing the column_index in a variable:

        var conn = try pool.acquire();
        defer conn.release();

        // again, we have to tell pg to load the column names
        var result = try conn.queryOpts(
            \\ select $1 as id, now() as time
            \\ union all
            \\ select $2, now() + interval '1 hour'
        , .{"25ed0ed1-a35b-41a0-a6bd-89ddb3b8b716", "e2242aa2-db4e-4dd5-8677-76bc19b9e0f5"}, .{.column_names = true},
        );
        defer result.deinit();

        const id_index = result.columnIndex("id").?;
        const time_index = result.columnIndex("time").?;
        while (try result.next()) |row| {
            const id = try row.get([]const u8, id_index);
            const unix_micro = try row.get(i64, time_index);
            log.info("{s} {d}", .{id, unix_micro});
        }
    }

    {
        // There is basic functionality for turning a row into a struct.
        const User = struct {
            name: []const u8,
            power: i32,
        };

        {
            log.info("\n\nExample 7", .{});
            // There are many things to be aware of. By default, the field order
            // and column order is used. By default, any non-primitive value is only
            // valid until the next call to `next()` or `deinit();
            var row = (try pool.row("select 'Goku', 9001", .{})) orelse unreachable;
            defer row.deinit() catch {};

            const user = try row.to(User, .{});
            log.info("{s} {d}", .{user.name, user.power});
        }

        {
            log.info("\n\nExample 8", .{});
            // We can match by name instead, and provide an allocator to dupe
            // any string/iterator. This allows values to live beyond the next
            // call to next/deinit, but we must free the values. Consider using
            // an arena to more easily manage allocated memory.
            var arena = std.heap.ArenaAllocator.init(allocator);
            defer arena.deinit();

            var row = (try pool.rowOpts("select 4000 as power, 'Vegeta' as name", .{}, .{.column_names = true})) orelse unreachable;
            defer row.deinit() catch {};

            const user = try row.to(User, .{.map = .name, .allocator = arena.allocator()});
            log.info("{s} {d}", .{user.name, user.power});
        }

        {
            log.info("\n\nExample 9", .{});
            // As always, there's overhead to doing name lookups. If you're going
            // to map many rows into structures, consider creating a mapper.
            // Also, here rather than providing our own allocator, we're telling
            // pg to use its own result-scoped arena. This has pros and cons.
            // The pro is that it's simple and values will exist beyond each
            // call to next() and will be cleaned up by deinit().
            // The con is that a lot of memory might accumulate in the arena.

            var result = try pool.queryOpts(
                \\ select 4000 as power, 'Vegeta' as name
                \\ union all
                \\ select 9001, 'Goku'
            , .{}, .{.column_names = true});
            defer result.deinit();

            // dupe = true tells the mapper to dupe values using the
            // internal result arena
            var mapper = result.mapper(User, .{.dupe = true});
            while (try mapper.next()) |user| {
                log.info("{s} {d}", .{user.name, user.power});
            }
        }

        {
            log.info("\n\nExample 10", .{});
            // unsafe operations avoid some runtime checks, but can reach
            // "unreachable" if the types are wrong.
            var conn = try pool.acquire();
            defer conn.release();

            var result = try conn.query("select * from pg_example_users order by id", .{});
            defer result.deinit();

            // notice the `nextUsafe`
            while (try result.nextUnsafe()) |row| {
                // unlike the "safe" variant, there's no "try" here. This assumes
                // you're 100% sure column 0 is an i32 and column 1 is a string
                const id = row.get(i32, 0);
                const name = row.get([]const u8, 1);
                log.info("User {d}: {s}", .{id, name});
            }
        }
    }
}
