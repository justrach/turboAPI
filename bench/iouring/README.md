# io_uring smoke test

End-to-end correctness check for the Linux `io_uring` `IORING_OP_ACCEPT_MULTISHOT`
accept loop in [`zig/src/iouring.zig`](../../zig/src/iouring.zig).

This is **not a benchmark.** It exists to prove that:

1. `zig/src/iouring.zig` compiles cleanly for `aarch64-linux-musl`.
2. `std.os.linux.IoUring` works on the kernel the test is run against.
3. `IORING_OP_ACCEPT_MULTISHOT` actually delivers all expected accepts when
   N clients connect to a listen socket.

The smoke binary opens a TCP listener on `127.0.0.1:18080`, runs the
`AcceptLoop` on a worker thread, dials the listener N times from the main
thread, and asserts the accept callback fired N times. Exits 0 on success,
non-zero otherwise.

## Run

Requires Apple `container` 0.11+ (or any compatible OCI runtime — set
`RUNTIME=docker` / `RUNTIME=podman`). On macOS, start the container service
first:

```bash
container system start
./bench/iouring/run.sh
```

The script:

1. Cross-compiles `iouring_smoke` for `aarch64-linux-musl` on the host.
2. Builds the OCI image from this directory.
3. Runs the smoke binary inside a fresh container.

A passing run prints something like:

```
listening on 127.0.0.1:18080 (fd=3)
  client 1/16 connected
  ...
  client 16/16 connected
io_uring AcceptLoop saw 16 accepts (wanted >= 16)
OK
==> io_uring smoke test PASSED
```

The kernel version reported on a clean `container run alpine:3.20 uname -a`
on macOS 26 / `container` 0.11 is `Linux ... 6.18.5 ... aarch64`, well above
the 5.19 minimum for `IORING_OP_ACCEPT_MULTISHOT`.

## Limitations

* Only the accept loop is exercised. Per-connection `recv` / `send` over
  `io_uring` is not implemented yet — see the staged plan in
  [`zig/src/iouring.zig`](../../zig/src/iouring.zig).
* No request/response payload is sent; the test closes accepted fds
  immediately.
* No latency or throughput numbers are produced. Per `AGENTS.md`, do not
  cite this script in any benchmark table or release note.
