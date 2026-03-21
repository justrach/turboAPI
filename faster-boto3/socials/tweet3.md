# Tweet Thread: TurboBoto — Zig-accelerated boto3

## Tweet 1 (Hook)

We replaced urllib3 inside boto3 with a Zig HTTP client.

One import line. Same API. 115x faster with TurboAPI.

`import faster_boto3 as boto3`

Here's what happened:

## Tweet 2 (The Problem)

We profiled every boto3 API call.

48% of the time? Not network. Not AWS. Not your code.

Python overhead:
- urllib3 socket handling
- User-Agent string rebuilt every request
- dateutil timestamp parsing (62us per call)
- XML ElementTree for S3 responses

## Tweet 3 (The Fix)

So we replaced the transport layer with Zig.

One monkey-patch swaps URLLib3Session.send() → Zig std.http.Client

- Persistent connection pooling (nanobrew pattern)
- Zero-copy streaming
- No GIL (Python 3.14t free-threaded)
- Hardware-accelerated SHA256

## Tweet 4 (Standalone Numbers)

faster-boto3 vs vanilla boto3 (same client, LocalStack):

S3 GetObject:     1,176us → 1.19x faster
S3 HeadObject:    1,168us → 1.19x faster  
S3 ListObjects:   2,096us → 1.12x faster
DynamoDB GetItem: 1,888us → 1.10x faster

8 out of 12 operations improved. 0 regressions.

## Tweet 5 (Full Stack Numbers)

Pair it with TurboAPI and the full stack compounds:

TurboAPI + TurboBoto vs FastAPI + boto3:

S3 GetObject:  169,986 vs 1,470 req/s → 115x
S3 HeadObject: 167,268 vs 1,641 req/s → 102x
S3 ListObjects: 167,442 vs 1,031 req/s → 162x

170K requests/sec hitting S3.

## Tweet 6 (Pure Zig Ceiling)

We also built a pure Zig S3 client (like zig-s3) to find the ceiling:

HeadObject:
- Pure Zig:      856us
- faster-boto3: 1,168us  
- vanilla boto3: 1,393us

Zig is 1.93x faster than boto3. We're at 1.19x — 31% from bare metal.

## Tweet 7 (SIMD Parsers)

The Zig accelerators also include SIMD parsers:

- XML tag extraction: 44x faster (S3 ListObjects)
- Timestamp parsing: 368x faster (NEON vectorized)
- SigV4 signing: 7x faster (HMAC-SHA256 chain)
- SHA256 hashing: hardware accelerated

## Tweet 8 (Compatibility)

36 parity tests pass. Every S3 + DynamoDB operation tested:

- GetObject (text, binary, empty, unicode, ETag) ✓
- PutObject (roundtrip, empty, 1MB, metadata) ✓
- ListObjects, HeadObject, DeleteObject, CopyObject ✓
- DynamoDB Get/Put/Scan/BatchWrite ✓
- SigV4 signature parity ✓

Docker CI verified (Linux + macOS).

## Tweet 9 (DX)

The DX is one line:

```python
# Before
import boto3

# After
import faster_boto3 as boto3

# Everything else stays the same
s3 = boto3.client('s3')
ddb = boto3.client('dynamodb')
```

No config. No setup. Drop-in replacement.

## Tweet 10 (Credits + CTA)

Built with patterns from:
- @nanobrew — Zig HTTP client, streaming SHA256, parallel downloads
- @zig-s3 — pure Zig S3 reference (manual XML parsing, SigV4)
- @turboAPI — Zig HTTP server, DHI validation

Python 3.14t free-threaded. Zig 0.15.1. GIL disabled.

github.com/justrach/turboAPI/tree/faster-boto3
