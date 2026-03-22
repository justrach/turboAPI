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
