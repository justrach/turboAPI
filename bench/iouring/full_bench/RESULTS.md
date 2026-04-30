# io_uring vs blocking-accept — A/B run

> **Scope:** the *only* code path that differs between the two builds is
> the listener accept loop. Per-connection `recv` / `send` still goes
> through the existing thread-pool synchronous syscalls in both
> variants. Treat the deltas accordingly. Per `AGENTS.md`, do not cite
> these numbers in release notes, framework comparison tables, or any
> public copy.

## Environment

- Apple `container` CLI (Linux microVM on macOS)
- Kernel: `Linux 6.18.5 aarch64`
- Python: `3.14.4 free-threaded` (GIL disabled)
- Zig: `0.16.0`, `-Doptimize=ReleaseFast`
- wrk: `t=4 c=64 d=10s` per iteration, 3s warmup
- Iterations: **5 per (variant, workload)**, median reported
- All traffic on loopback inside one container

## Workloads

| name      | request                                      | notes |
|-----------|----------------------------------------------|-------|
| `noargs`  | `GET /`                                      | trivial fast path |
| `user_id` | `GET /user/{id}` with `id` random 1..10M     | path-param parsing every request, defeats per-path caching |
| `query`   | `GET /q?id={id}` with `id` random 1..10M     | query-string parsing every request |
| `items`   | `GET /items` returning a 50-record JSON body | bigger response (~2 KB) |

`user_id` and `query` use `wrk -s vary_user_id.lua` / `vary_query.lua`
which generate a fresh URL per request, so the radix-trie lookup runs
cold every time.

## Median of 5 runs

| workload | variant   | req/s     | Δ vs blocking | p50      | p99      |
|----------|-----------|-----------|---------------|----------|----------|
| noargs   | blocking  | 697,933   | —             | 20 µs    | 86 µs    |
| noargs   | iouring   | 713,240   | **+2.2 %**    | 21 µs    | 59 µs    |
| user_id  | blocking  | 321,439   | —             | 43 µs    | 321 µs   |
| user_id  | iouring   | 366,991   | **+14.2 %**   | 39 µs    | 261 µs   |
| query    | blocking  | 235,954   | —             | 28 µs    | 7.87 ms  |
| query    | iouring   | 235,270   | **−0.3 %**    | 28 µs    | 8.32 ms  |
| items    | blocking  | 124,408   | —             | 170 µs   | 401 µs   |
| items    | iouring   | 130,719   | **+5.1 %**    | 150 µs   | 533 µs   |

Raw per-iteration `wrk` outputs are in `results/`.

## Honest caveats

- 5 samples is enough to spot order-of-magnitude differences but not
  small ones; the `query` and `noargs` deltas are within run-to-run
  noise on this VM.
- p99 jitter is high (`query` shows multi-millisecond tails on both
  builds — likely loopback + `wrk` timing artifacts, not server
  pauses). Don't read the p99 column as a stable signal.
- Single-container, loopback, single client. No multi-host, no
  external network, no multi-worker deployment scenario.
- `wrk -t4` is approaching saturation on the `noargs` route (~700k
  rps). Some of the small delta there may be wrk-bound, not
  server-bound.
- This run was kicked off in a fresh container, so each variant got a
  cold start; results were not interleaved.

## Reproducing

```bash
container build -t turboapi-iouring-bench \
    -f bench/iouring/full_bench/Containerfile \
    bench/iouring/full_bench

container run --rm -m 8G -c 4 \
    -v "$PWD":/work \
    turboapi-iouring-bench
```

Override env vars to scale up:

```bash
container run --rm -m 8G -c 4 \
    -e DURATION=30s -e ITERS=10 -e CONNS=128 \
    -v "$PWD":/work \
    turboapi-iouring-bench
```
