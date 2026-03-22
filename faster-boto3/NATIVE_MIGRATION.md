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
- Public native S3 coverage is now 14 operations: `HeadObject`, `GetObject`,
  `PutObject`, `ListObjectsV2`, `DeleteObject`, `DeleteObjects`,
  `CopyObject`, `CreateMultipartUpload`, `UploadPart`,
  `UploadPartCopy`, `CompleteMultipartUpload`, `AbortMultipartUpload`,
  `ListParts`, and `ListMultipartUploads`.
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
