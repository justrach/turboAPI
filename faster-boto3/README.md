# faster-boto3

Drop-in boto3 acceleration layer powered by Zig. Same API, faster internals.

## Approach

NOT a boto3 rewrite. Instead, we replace the slow Python internals with Zig:

| Component | boto3 (Python) | faster-boto3 (Zig) | Expected speedup |
|-----------|---------------|-------------------|-----------------|
| SigV4 signing | hmac + hashlib | Zig std.crypto.auth.hmac | 5-10x |
| XML parsing (S3) | xml.etree.ElementTree | Zig XML parser | 10-20x |
| JSON parsing (DynamoDB) | json.loads | Zig JSON parser | 5-10x |
| HTTP client | urllib3 (pure Python) | Zig std.http.Client | 3-5x |
| Request serialization | string formatting | Zig bufPrint | 5-10x |

## Architecture

```
faster_boto3/
  __init__.py          # Drop-in: `from faster_boto3 import Session`
  session.py           # Wraps boto3.Session, injects Zig accelerators
  _accel.zig           # Zig native module (SigV4, parsers, HTTP)
  sigv4.zig            # HMAC-SHA256 signing
  parsers.zig          # XML + JSON response parsing
```

## Feature Parity

boto3 has 551 unit tests and 905 functional tests. We use these as our compatibility gate:

```bash
# Run boto3's own tests against faster-boto3
python -m pytest tests/unit/ tests/functional/ -v
```

## Phase 1: SigV4 Signing

The signing hot path runs on every single AWS API call. Moving it to Zig gives
immediate speedup across all services (S3, DynamoDB, Lambda, etc).

## Usage (target API)

```python
# Option 1: Monkey-patch boto3
import faster_boto3
faster_boto3.patch()  # replaces slow internals with Zig

import boto3
s3 = boto3.client('s3')  # now uses Zig signing + parsing

# Option 2: Direct import
from faster_boto3 import Session
session = Session()
s3 = session.client('s3')
```
