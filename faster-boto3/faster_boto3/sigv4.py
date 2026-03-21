"""
SigV4 signing - pure Python reference implementation.

This is the fallback when the Zig accelerator is not available.
When _sigv4_accel is built, the hot functions (signature, canonical_request)
are replaced with Zig implementations.
"""

import hashlib
import hmac


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sign_hex(key: bytes, msg: str) -> str:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def derive_signing_key(secret_key: str, datestamp: str, region: str, service: str) -> bytes:
    """Derive the SigV4 signing key (4 chained HMAC-SHA256)."""
    k_date = _sign(f"AWS4{secret_key}".encode(), datestamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    k_signing = _sign(k_service, "aws4_request")
    return k_signing


def sha256_hex(data: bytes) -> str:
    """SHA256 hash, hex encoded."""
    return hashlib.sha256(data).hexdigest()


def sign_string(signing_key: bytes, string_to_sign: str) -> str:
    """Sign a string with the derived signing key."""
    return _sign_hex(signing_key, string_to_sign)


# Benchmark helper
def bench_sigv4(iterations: int = 10000):
    """Benchmark SigV4 signing operations."""
    import time

    secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    datestamp = "20260321"
    region = "us-east-1"
    service = "s3"
    string_to_sign = "AWS4-HMAC-SHA256\n20260321T000000Z\n20260321/us-east-1/s3/aws4_request\nabc123"

    # Warmup
    for _ in range(100):
        key = derive_signing_key(secret, datestamp, region, service)
        sign_string(key, string_to_sign)

    start = time.perf_counter()
    for _ in range(iterations):
        key = derive_signing_key(secret, datestamp, region, service)
        sign_string(key, string_to_sign)
    elapsed = time.perf_counter() - start

    ops_per_sec = iterations / elapsed
    us_per_op = (elapsed / iterations) * 1_000_000
    print(f"SigV4 signing: {ops_per_sec:,.0f} ops/sec ({us_per_op:.1f}us/op)")
    return ops_per_sec


if __name__ == "__main__":
    bench_sigv4()
