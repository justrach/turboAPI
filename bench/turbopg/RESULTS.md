# turbopg / pg.zig — blocking vs io_uring transport A/B

> **Scope:** the only code path that differs between the two builds is
> the `Stream` struct in `zig/pg/src/stream.zig`. Everything else
> (wire-protocol codec, `Conn`, `Pool`, result decoding) is identical.
> The io_uring path is **one ring per connection**, single in-flight
> SQE per `read` / `writeAll` (submit + `copy_cqe`). **No scheduler, no
> SQPOLL, no multi-shot, no registered fds.** The real async win
> needs all of those on top. Per `AGENTS.md`, do not cite these
> numbers in release notes, framework comparison tables, or
> marketing copy.

## Environment

- Apple `container` CLI (two Linux microVMs on macOS, shared vnic)
- DB container: `postgres:18`, trust auth, default shm, `192.168.64.14`
- Bench container: `debian:bookworm-slim` + Zig 0.16.0 aarch64-linux
- Kernel (both VMs): `Linux 6.18.5 aarch64`
- pg.zig build: `-Doptimize=ReleaseFast`
- Workload: N worker threads, each owns one `pg.Conn`, hot loop of a
  single query shape for the duration
- Network: container-to-container via the default `container` network

## Variants

| label      | build flag         | transport used           |
|------------|--------------------|--------------------------|
| `blocking` | `-Diouring=false`  | `PlainStream` (read / send via libc syscalls) |
| `iouring`  | `-Diouring=true`   | `IoUringStream` (one ring per conn, `IORING_OP_SEND` / `IORING_OP_RECV`, submit + `copy_cqe`) |

Both variants share the same connect path, auth path, and `Reader`.

## Workloads

| id | SQL                                          | notes |
|----|----------------------------------------------|-------|
| 1  | `SELECT 1`                                   | smallest round trip |
| 2  | `SELECT id FROM generate_series(1, 50) AS id` | 50 rows back per query, ~300 B response |

## Results

4 worker threads, 10 s per run.

### query=1  (`SELECT 1`), median of 3

| variant  | median rps | min     | max     |
|----------|-----------:|--------:|--------:|
| blocking |  14,967.12 | 14,878  | 15,140  |
| iouring  |  15,178.03 | 15,127  | 15,230  |

Δ: **+1.4 %**, well within run-to-run noise with n=3.

### query=2  (`SELECT` generate_series(1,50)), median of 5

| variant  | median rps | min     | max     |
|----------|-----------:|--------:|--------:|
| blocking |  13,903.37 | 13,770  | 14,001  |
| iouring  |  13,849.02 | 13,752  | 13,929  |

Δ: **−0.4 %**, again within noise.

## What this tells us

1. Per-connection single-SQE io_uring is **roughly a wash** on a
   driver that was already blocking-sync. Expected: we trade one
   `recv()` syscall for one `io_uring_enter(submit)` +
   `io_uring_enter(wait_cqe)`, so the per-op syscall cost is
   approximately even. Kernel fastpath for small receives on a local
   TCP loop is already very fast.
2. On q=2 (bigger response, more bytes per recv) io_uring trends
   slightly slower — consistent with the extra ring bookkeeping
   overhead showing up once the per-op cost matters at all.
3. No regressions, no query errors. The abstraction and the ring
   plumbing work correctly for the full `Conn` lifetime (connect,
   startup, simple query, extended query, close).

## What would actually move the needle

The next items (deliberately **not** in this PR):

- **SQPOLL** so submitting no longer needs an `io_uring_enter`
  syscall in the common case.
- **Batched send**: queue up the parse/bind/describe/execute/sync
  packets into one `IORING_OP_SEND` instead of the current per-packet
  writes.
- **A cooperative scheduler** so one ring drives N connections
  concurrently and a waiting query yields the thread rather than
  blocking on `copy_cqe`. This is the real win and turns this from a
  neutral change into an actual throughput improvement.

## Caveats (read these)

- 3–5 iterations, 10 s each, one client, one DB. Enough to catch
  big regressions, not enough to publish percentage claims.
- `postgres:18` with default config, no tuning, `trust` auth.
- Apple `container` runs each container in its own microVM; cross-VM
  network adds a real-ish TCP path but results will not match a
  co-located production setup.
- No TLS. The io_uring path is plaintext-only in this PR;
  `-Dopenssl_lib_name=...` still picks TLS + the old blocking socket.

## Reproducing

```bash
# 1. Start Postgres 18
container run -d --name pg18 -e POSTGRES_HOST_AUTH_METHOD=trust postgres:18

# 2. Build the bench image once
container build -t turbopg-bench \
    -f bench/turbopg/Containerfile bench/turbopg

# 3. Find the pg18 IP (field ADDR in `container ls`)
PG_IP=$(container ls | awk '$1=="pg18" {print $6}' | cut -d/ -f1)

# 4. Run
container run --rm -m 4G -c 4 \
    -e PGHOST="$PG_IP" \
    -e BENCH_QUERY=1 \
    -e BENCH_ITERS=5 \
    -v "$PWD":/work \
    turbopg-bench
```

Override `BENCH_QUERY` (1 or 2), `BENCH_THREADS`, `BENCH_DURATION`,
`BENCH_ITERS` as needed.
