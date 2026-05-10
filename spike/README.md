# nanoapi runtime-layer integration spike

Self-contained Zig binary that drives nanoapi's HTTP/1.1 runtime via the
generic `Dispatcher` vtable from [nanoapi#12](https://github.com/justrach/nanoapi/pull/12) — no `App`, no router, no
typed routes, no OpenAPI. The same shape turboAPI's Python FFI dispatcher
will take, minus the FFI itself.

## Run

Requires nanoapi checked out at `~/nanoapi` on a branch with the `Dispatcher`
work (`feat/decouple-runtime-from-app` or later).

```bash
cd spike
zig build
./zig-out/bin/spike
```

Then:

```bash
curl -i http://127.0.0.1:8765/
curl -i http://127.0.0.1:8765/hello
curl -i -X POST http://127.0.0.1:8765/echo-method
curl -i http://127.0.0.1:8765/missing
```

## Why a separate `build.zig`

turboAPI's main `zig/build.zig.zon` pins `pg.zig` at a SHA that doesn't
compile on Zig 0.16 (`addLibraryPath` API change). Wiring nanoapi into the
main turbonet build is blocked on upgrading `pg.zig` first — tracked
separately. The spike avoids the issue by living in its own module with
nanoapi as the only dependency.
