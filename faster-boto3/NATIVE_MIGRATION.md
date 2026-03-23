# Native Boto3 Migration Plan

## Goal

Keep the boto3-facing API stable while replacing botocore's request execution
pipeline with a native Zig path for selected operations.

This is a compatibility migration, not a rewrite that breaks surface area.
The model is closer to a Turborepo-style backend swap:

- keep one user-facing interface
- ship two backends for a while
- run both through the same parity grid
- only expand native coverage when parity gates pass

## Scope

Phase 1 targets S3 first:

- `HeadObject`
- `GetObject`
- `PutObject`
- `ListObjectsV2`
- multipart control plane and part upload APIs

These are enough to prove the architecture on rest-xml, request signing,
streaming/non-streaming bodies, and common error handling.

## Architecture Direction

Current accelerated path:

`boto3 -> botocore serializer/signer/parser -> patched send() -> Zig transport`

Target native path:

`boto3-compatible shim -> native operation serializer/signer/transport/parser in Zig`

The important cutoff is earlier than `AWSRequest`. Once botocore has already
built and signed the request, most of the Python overhead has already happened.

## Rollout Model

Every migrated operation should support three modes:

- `legacy`: full botocore path
- `native_shadow`: execute native path for parity checks but return legacy result
- `native`: return native result

Recommended controls:

- env var gate, e.g. `FASTER_BOTO3_NATIVE=0|shadow|1`
- per-service and per-operation allowlist
- structured parity logging for mismatches

## Parity Grid

Each migrated operation must be checked across the same grid before promotion.

### Request parity

- URI/path encoding
- query serialization and ordering
- required/optional headers
- `Content-Length` behavior
- `x-amz-content-sha256`
- payload hashing for bytes, strings, and file-backed bodies
- SigV4 canonical request and authorization header

### Response parity

- status code
- headers, casing normalized
- parsed output shape
- timestamps
- paging tokens / continuation markers
- streaming body behavior
- error code / message / metadata

### Behavioral parity

- retries and retryable classification
- idempotency behavior
- checksum behavior where applicable
- timeout and connection failure semantics
- empty body / malformed body handling

## Promotion Gates

An operation should not move from `native_shadow` to `native` until all of the
following are true:

- golden parity tests pass against LocalStack and real AWS for the operation
- mismatch rate is zero in the stored parity corpus
- error responses match expected botocore semantics
- perf win is measurable against a clean baseline
- feature matrix in this doc is updated

## Feature Matrix

| Area | Legacy Botocore | Current Accelerated Path | Native Migration Target |
|---|---|---|---|
| Public boto3 API | Full | Full | Full |
| HTTP transport | Python/urllib3 | Zig | Zig |
| SigV4 | Python | Zig hot patch | Zig native |
| JSON parsing | Python | Zig hot patch | Zig native |
| Timestamp parsing | Python | Zig hot patch | Zig native |
| XML parsing | Python | Python | Zig native |
| Request serialization | Python | Python | Zig native |
| Retry policy | Botocore | Botocore | Botocore-compatible native |
| Paginators / waiters | Botocore | Botocore | Legacy first, migrate later |
| Streaming uploads | Botocore | Zig transport + `request_fd` | Native |

## Current Bench Snapshot

Latest quick LocalStack snapshot on branch `native-boto-3` after:

- native multipart upload path
- per-operation rollout controls
- streaming `request_fd` uploads in Zig transport
- preallocated large native response buffers
- file-backed `PutObject` and multipart `UploadPart` using `UNSIGNED-PAYLOAD`
  with fd streaming instead of Python-side full-body hashing

### End-to-end native vs legacy

| Operation | Legacy | Native | Speedup |
|---|---:|---:|---:|
| `HeadObject` | 1139.2 us | 1005.0 us | 1.13x |
| `GetObject` 1 KiB | 1189.1 us | 965.3 us | 1.23x |
| `GetObject` 8 MiB | 47574.0 us | 29944.9 us | 1.59x |
| `PutObject` 1 KiB | 2284.2 us | 1695.1 us | 1.35x |
| `PutObject` file 1 MiB | 11448.2 us | 7104.4 us | 1.61x |
| `PutObject` file 8 MiB | 70812.5 us | 55729.4 us | 1.27x |
| `ListObjectsV2` | 3350.4 us | 1815.7 us | 1.85x |
| `CopyObject` | 2194.0 us | 1711.9 us | 1.28x |

### Upload-path comparison

The older multipart toggle by itself was mostly neutral. The newer meaningful
change was removing Python-side full-body hashing for file-backed native puts.

| File size | Legacy | Native | Delta |
|---|---:|---:|---:|
| 1 MiB | 11448.2 us | 7104.4 us | 1.61x faster |
| 8 MiB | 70812.5 us | 55729.4 us | 1.27x faster |

### Raw native phase breakdown

`raw_native` isolates native prep, transport, and parse time without the public
wrapper dispatch. The current file-backed upload path is much cheaper in prep
than the older read-and-hash approach.

| Operation | Prep | Transport | Parse | Total |
|---|---:|---:|---:|---:|
| `GetObject` 8 MiB | 56.9 us | 29288.2 us | 42.1 us | 29387.0 us |
| `PutObject` file 1 MiB | 127.1 us | 6702.7 us | 29.8 us | 6888.3 us |
| `PutObject` file 8 MiB | 64.0 us | 55665.8 us | 13.1 us | 55742.8 us |
| `ListObjectsV2` | 29.4 us | 1705.6 us | 115.6 us | 1851.3 us |

### Notes

- The current native path is materially faster than legacy on the implemented
  S3 operations, but LocalStack transport latency still dominates total wall
  time.
- Public native S3 coverage is now 29 operations: `CreateBucket`,
  `DeleteBucket`, `HeadBucket`, `ListBuckets`, `GetBucketLocation`,
  `GetBucketTagging`, `PutBucketTagging`, `DeleteBucketTagging`,
  `GetBucketVersioning`, `PutBucketVersioning`, `ListObjects`,
  `ListObjectsV2`, `ListObjectVersions`, `HeadObject`, `GetObject`,
  `GetObjectTagging`, `PutObject`, `PutObjectTagging`, `DeleteObject`,
  `DeleteObjectTagging`, `DeleteObjects`, `CopyObject`,
  `CreateMultipartUpload`, `UploadPart`, `UploadPartCopy`,
  `CompleteMultipartUpload`, `AbortMultipartUpload`, `ListParts`, and
  `ListMultipartUploads`.
- `AbortMultipartUpload` now returns cleanly on the native transport after the
  no-body response handling fix in the Zig HTTP client.
- The larger upload win is now coming from the native request path plus the
  streaming fd transport and unsigned file-backed payload path, not from
  multipart orchestration alone.
- For 1 MiB file-backed puts, raw native prep is now about `127 us`, down from
  the previous roughly `700+ us` range when Python read and hashed the full
  body before send.
- Real AWS measurements are still needed before treating these upload numbers as
  the final shape of the optimization.

## Full-Stack Throughput Snapshot

The end-to-end `TurboAPI + faster-boto3` benchmark is sensitive to runtime
mode. On free-threaded CPython 3.14, the Turbo subprocess must be launched with
`PYTHON_GIL=0`, otherwise the interpreter silently re-enables the GIL when the
native modules load and the throughput numbers collapse.

The benchmark harness in [benchmarks/turbo_vs_fast_s3.py](benchmarks/turbo_vs_fast_s3.py)
now forces `PYTHON_GIL=0` for the Turbo subprocess so the measured path matches
the intended runtime.

### Default load

Command:

```bash
TURBO_DISABLE_CACHE=1 \
TURBO_DISABLE_DB_CACHE=1 \
TURBO_DISABLE_RATE_LIMITING=1 \
FASTER_BOTO3_AUTOPATCH=0 \
FASTER_BOTO3_NATIVE=native \
python benchmarks/turbo_vs_fast_s3.py --duration 5
```

Load: `wrk -t4 -c50 -d5s`

| Operation | Turbo RPS | Fast RPS | Speedup | Turbo p99 |
|---|---:|---:|---:|---:|
| `S3 GetObject (1KB)` | 1331 | 1096 | 1.21x | 33.4 ms |
| `S3 GetObject (10KB)` | 1209 | 935 | 1.29x | 46.2 ms |
| `S3 HeadObject` | 982 | 1113 | 0.88x | 57.8 ms |
| `S3 ListObjects (20)` | 760 | 592 | 1.28x | 71.2 ms |

### Higher load

Command:

```bash
TURBO_DISABLE_CACHE=1 \
TURBO_DISABLE_DB_CACHE=1 \
TURBO_DISABLE_RATE_LIMITING=1 \
FASTER_BOTO3_AUTOPATCH=0 \
FASTER_BOTO3_NATIVE=native \
python benchmarks/turbo_vs_fast_s3.py --duration 5 --threads 8 --connections 200
```

Load: `wrk -t8 -c200 -d5s`

| Operation | Turbo RPS | Fast RPS | Speedup | Turbo p99 |
|---|---:|---:|---:|---:|
| `S3 GetObject (1KB)` | 1527 | 1254 | 1.22x | 27.5 ms |
| `S3 GetObject (10KB)` | 1423 | 1224 | 1.16x | 42.6 ms |
| `S3 HeadObject` | 1436 | 1465 | 0.98x | 48.1 ms |
| `S3 ListObjects (20)` | 1100 | 741 | 1.49x | 46.7 ms |

### Notes

- The earlier “Turbo slower than FastAPI” throughput runs were mostly measuring
  the wrong runtime mode. Once the Turbo subprocess stayed on the intended
  `PYTHON_GIL=0` path, the `get` and `list` lanes flipped back in favor of the
  native stack.
- `HeadObject` is still the clear outlier because the current native
  implementation is on a stability workaround in `native_s3.py`: it uses a
  signed byte-range `GET` instead of a true native `HEAD` transport path.
- These are still LocalStack numbers. They are useful for relative comparisons
  inside this repo, but not a substitute for real AWS measurements.

## Native FFI Route Spike

To test what happens when the S3 route hot path moves out of Python entirely,
the benchmark harness now also supports a `native-ffi` mode. In that mode,
TurboAPI serves the S3 endpoints from a Zig FFI handler library instead of a
Python route function.

This is a spike, not a parity-complete backend. It currently focuses on the
fully native route path for a small S3 slice. The current validated FFI handlers
are `GetObject`, `HeadObject`, `ListObjectsV2`, `HeadBucket`, `ListBuckets`,
`GetBucketLocation`, `DeleteObject`, and `CopyObject`.

Command:

```bash
PYTHON_GIL=0 \
python benchmarks/turbo_vs_fast_s3.py \
  --duration 3 \
  --threads 8 \
  --connections 200 \
  --turbo-mode native-ffi
```

Load: `wrk -t8 -c200 -d3s`

| Operation | Turbo RPS | Fast RPS | Speedup | Turbo p99 |
|---|---:|---:|---:|---:|
| `S3 GetObject (1KB)` | 1420 | 1113 | 1.28x | 33.7 ms |
| `S3 GetObject (10KB)` | 1415 | 1133 | 1.25x | 30.1 ms |
| `S3 HeadObject` | 1479 | 1343 | 1.10x | 55.1 ms |
| `S3 ListObjects (20)` | 956 | 685 | 1.40x | 86.7 ms |

### Notes

- The first native-ffi run looked dramatically faster because the handler was
  returning fast `400` responses while still surfacing `200` at the route
  level. After fixing outbound `Host` handling and checking the route against
  real objects, these are the corrected numbers.
- The current FFI handler now reuses a thread-local Zig `std.http.Client` and
  caches the derived SigV4 signing key by date per worker thread.
- The handler also now caches the computed `Host` value at init time instead of
  reparsing the endpoint URI on every request just to rebuild canonical
  headers.
- The common-path signer/header builder now uses fixed stack buffers instead of
  rebuilding maps and heap arrays per request.
- `HeadObject` is back on a true `HEAD` request in the FFI spike.

### Turbo thread-pool sweep

To check whether the native S3 route is worker-starved inside Turbo itself, the
benchmark harness now accepts `--turbo-thread-pool-size` and
`--turbo-thread-pool-sweep`.

Command:

```bash
TURBO_DISABLE_CACHE=1 \
TURBO_DISABLE_DB_CACHE=1 \
TURBO_DISABLE_RATE_LIMITING=1 \
PYTHON_GIL=0 \
python benchmarks/turbo_vs_fast_s3.py \
  --duration 2 \
  --threads 8 \
  --connections 200 \
  --turbo-mode native-ffi \
  --turbo-thread-pool-sweep 12,24,48 \
  --json
```

| Turbo pool | Get 1KB | Get 10KB | Head | List (20) |
|---|---:|---:|---:|---:|
| `12` | `1.36x` | `1.17x` | `1.13x` | `1.46x` |
| `24` | `1.28x` | `1.13x` | `1.14x` | `1.47x` |
| `48` | `1.29x` | `1.24x` | `1.16x` | `1.35x` |

What this means:

- Turbo's worker count is not the dominant bottleneck on this S3 slice.
- The native route already scales well enough at `12` workers that pushing to
  `24` or `48` mostly stays in the same band.
- The remaining costs are inside the request path itself: LocalStack/network
  time, fixed signing/request setup, and list parsing.
- This is different from the DB path, where per-thread connections remove a
  bigger source of lock/pool overhead. For S3 here, per-thread client reuse is
  already in place and the next wins are more about reducing per-request work
  than adding more server threads.

### Batching signal

The strongest next lever is batching/coalescing, not just shaving a few more
microseconds off a single S3 call. To test that, the benchmark harness now has a
`BatchHead` lane that performs 8 internal `HeadObject` calls behind one external
HTTP request.

Command:

```bash
TURBO_DISABLE_CACHE=1 \
TURBO_DISABLE_DB_CACHE=1 \
TURBO_DISABLE_RATE_LIMITING=1 \
PYTHON_GIL=0 \
python benchmarks/turbo_vs_fast_s3.py \
  --duration 1 \
  --threads 4 \
  --connections 50 \
  --turbo-mode native-ffi \
  --json
```

Result from the short validation run:

| Operation | Turbo RPS | Fast RPS | Speedup |
|---|---:|---:|---:|
| `S3 BatchHead (8x1KB)` | `182.47` | `104.15` | `1.75x` |

Interpretation:

- Single-op native S3 lanes are mostly in the `1.1x` to `1.5x` range.
- Once 8 S3 operations are collapsed behind one route, the win grows because
  route/framework overhead is amortized and the native handler keeps its shared
  per-thread client/signing state hot.
- This is the same basic reason `aws s3 sync` and transfer-manager style
  orchestration often beat naive per-file upload loops: the scheduler and the
  shared execution context matter as much as the single request path.

## Cost Model

There is now a small explicit model in
[benchmarks/native_s3_cost_model.py](benchmarks/native_s3_cost_model.py) for
the current native-FFI measurements. It is not trying to be a perfect fit. It
exists to make the current bottlenecks legible and to let us reason about
counterfactuals.

Current derived estimates from that script:

- fixed native path from `HeadObject`: about `0.629 ms`
- incremental transfer cost from `1 KiB -> 10 KiB` `GetObject`: effectively
  negligible in this LocalStack setup, about `0.00023 ms/KB`
- incremental `ListObjectsV2` cost vs `HeadObject`: about `0.582 ms`
- implied list parse overhead per returned item: about `0.029 ms/item`

That model points at the same practical conclusion as the benchmarks:

- shaving more bytes off the `get` path will not move the needle much here
- the fixed request path and list parsing are better optimization targets
- if we halve the current fixed path, `HeadObject` projects to about `3181 RPS`
- if we halve the current list-specific parse cost, `ListObjectsV2` projects to
  about `1088 RPS`

There is also an explicit path map in
[benchmarks/native_s3_path_map.py](benchmarks/native_s3_path_map.py). That file
lists the exact request stages for:

- `FastAPI + boto3`
- `TurboAPI + faster-boto3`
- `TurboAPI + native-ffi` for `get`, `head`, and `list`

The point is to make optimization targets concrete. The fastest-path question is
no longer “where is overhead in general?” but “which named stage do we remove or
shrink next?”

There is also a small optimizer in
[benchmarks/native_s3_linear_opt.py](benchmarks/native_s3_linear_opt.py). It
uses ridge-regularized least squares on the trusted benchmark snapshots to fit a
small stage-cost model and then chooses the cheapest currently-measured path per
operation.

Current recommendation:

- `HeadObject` -> `turbo_native_ffi`
- `GetObject` -> `turbo_faster_boto3`
- `ListObjectsV2` -> `turbo_faster_boto3`

That recommendation is also checked in as
[benchmarks/native_s3_best_path_policy.json](benchmarks/native_s3_best_path_policy.json)
so the current “best path” is explicit.

## What Gets Checked

For each migrated operation, store:

- canonical input cases
- expected request wire shape
- expected parsed success output
- expected parsed error output
- known unsupported features

This should live in versioned fixtures so the native path is always compared
against an explicit contract, not just ad hoc benchmarks.

## Suggested Execution Order

1. Build a native S3 operation dispatcher behind a feature flag.
2. Implement `HeadObject` end-to-end first.
3. Add parity fixtures and shadow execution logging.
4. Implement `GetObject` and `PutObject`.
5. Implement `ListObjectsV2` with XML parity fixtures.
6. Add real-AWS validation for the migrated operations.
7. Expand service coverage only after S3 passes the grid.

## Non-Goals For Phase 1

- replacing every botocore service at once
- waiters and paginators in native form
- event streams
- multipart upload manager parity
- presigned URL parity

## Open Risks

- botocore has service-specific edge cases hidden in serializers/parsers
- rest-xml error handling is less trivial than happy-path parsing
- exact parity for streaming and retries can regress subtly
- LocalStack can hide real AWS differences if used as the only oracle
