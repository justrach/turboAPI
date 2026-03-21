"""Benchmark: Python SigV4 vs Zig SigV4 signing."""

import time

ITERATIONS = 100_000
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
DATESTAMP = "20260321"
REGION = "us-east-1"
SERVICE = "s3"
STRING_TO_SIGN = (
    "AWS4-HMAC-SHA256\n"
    "20260321T000000Z\n"
    "20260321/us-east-1/s3/aws4_request\n"
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)


def bench_python():
    from faster_boto3.sigv4 import derive_signing_key, sign_string

    # Warmup
    for _ in range(100):
        key = derive_signing_key(SECRET, DATESTAMP, REGION, SERVICE)
        sign_string(key, STRING_TO_SIGN)

    start = time.perf_counter()
    for _ in range(ITERATIONS):
        key = derive_signing_key(SECRET, DATESTAMP, REGION, SERVICE)
        sign_string(key, STRING_TO_SIGN)
    elapsed = time.perf_counter() - start

    ops = ITERATIONS / elapsed
    us = (elapsed / ITERATIONS) * 1_000_000
    print(f"Python SigV4:  {ops:>10,.0f} ops/sec  ({us:.2f}us/op)")
    return ops


def bench_zig():
    try:
        from faster_boto3 import _sigv4_accel as accel
    except ImportError:
        print("Zig SigV4:     not built (run: python build_accel.py)")
        return 0

    # Warmup
    for _ in range(100):
        accel.sign(SECRET, DATESTAMP, REGION, SERVICE, STRING_TO_SIGN)

    start = time.perf_counter()
    for _ in range(ITERATIONS):
        accel.sign(SECRET, DATESTAMP, REGION, SERVICE, STRING_TO_SIGN)
    elapsed = time.perf_counter() - start

    ops = ITERATIONS / elapsed
    us = (elapsed / ITERATIONS) * 1_000_000
    print(f"Zig SigV4:     {ops:>10,.0f} ops/sec  ({us:.2f}us/op)")
    return ops


def bench_zig_split():
    """Bench derive_key + sign_string separately (like botocore does)."""
    try:
        from faster_boto3 import _sigv4_accel as accel
    except ImportError:
        return 0

    for _ in range(100):
        key = accel.derive_signing_key(SECRET, DATESTAMP, REGION, SERVICE)
        accel.sign_string(key, STRING_TO_SIGN)

    start = time.perf_counter()
    for _ in range(ITERATIONS):
        key = accel.derive_signing_key(SECRET, DATESTAMP, REGION, SERVICE)
        accel.sign_string(key, STRING_TO_SIGN)
    elapsed = time.perf_counter() - start

    ops = ITERATIONS / elapsed
    us = (elapsed / ITERATIONS) * 1_000_000
    print(f"Zig SigV4 (split): {ops:>7,.0f} ops/sec  ({us:.2f}us/op)")
    return ops


if __name__ == "__main__":
    print(f"SigV4 Signing Benchmark ({ITERATIONS:,} iterations)")
    print("=" * 55)
    py_ops = bench_python()
    zig_ops = bench_zig()
    zig_split = bench_zig_split()

    if zig_ops > 0:
        print(f"\nSpeedup: {zig_ops/py_ops:.1f}x (combined)")
    if zig_split > 0:
        print(f"Speedup: {zig_split/py_ops:.1f}x (split)")
