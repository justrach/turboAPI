# String Builder / Buffer For Zig

Behaves a lot like a `std.ArrayList(u8)` but with a cleaner interface and pooling capabilities.

```zig
const Buffer = @import("buffer").Buffer;

// Starts off with a static buffer of 100 bytes
// If you go over this, memory will be dynamically allocated 
// It's like calling ensureTotalCapacity on an ArrrayList, but
// those 100 bytes (aka the static portion of the buffer) are 
// re-used when pooling is used

var buf = try Buffer.init(allocator, 100);

try buf.writeByte('o');
try buf.write("ver 9000!1");
buf.truncate(1);

buf.len();  // 10
buf.string(); // "over 9000!"
```

You can access `&buf.interface` to get an `*std.io.Writer`.

You can use `writeU16Big`, `writeU32Big`, `writeU64Big` and `writeU16Little`, `writeU32Little`, `writeU64Little` to write integer values.

## Views
A common pattern is to include a 2 or 4 byte payload length prefix to messages. However, this length might not until after the message is generated. The `skip` functions exist specifically to solve the problem:

```zig
var buf = try Buffer.init(allocator, 100);

// skip 4 bytes, reserving a "view" to the start of the skipped location
var view = buf.skip(4);
try buf.write("hello world");
try buf.writeByte('!');

// fill in those first 4 bytes with the lenght (which we now know.)
view.writeU32Little(@intCast(buf.len());
```

The `view` exposes most of the same methods as the Buffer, but cannot grow and does not perform bound checking.

## Pooling

```zig
const Pool = @import("string_builder").Pool;


// Creates pool of 100 Buffers, each configured with a static buffer
// of 10000 bytes
var pool = try Pool.init(allocator, 100, 10000);
var buf = try pool.acquire();
defer pool.release(buf);
```

The `Pool` is thread-safe. The `Buffer` is not thread safe.

For a more advanced use case, `pool.acquireWithAllocator(std.mem.Allocator)` can be used. This has a specific purpose: to allocate the static buffer upfront using [probably] a general purpose allocator, but for any dynamic allocation to happen with a [probably] arena allocator. This is meant for the case where an arena allocator is available which outlives the checked out buffer. In such cases, using the arena allocator for any potential dynamic allocation by the buffer will offer better performance.
