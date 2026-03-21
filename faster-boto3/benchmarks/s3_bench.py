#!/usr/bin/env python3
"""
s3-bench: S3 acceleration benchmarks for faster-boto3.

Measures end-to-end speedup of faster-boto3 patches on real S3 operations
against LocalStack. Uses interleaved A/B testing to control for server variance.

Usage:
    python benchmarks/s3_bench.py                  # full suite
    python benchmarks/s3_bench.py --json            # machine-readable output
    python benchmarks/s3_bench.py --ci              # fail on regressions
    python benchmarks/s3_bench.py --quick           # reduced iterations

Requires: LocalStack running on localhost:4566
    docker compose up -d
"""

import argparse
import json as json_mod
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

import boto3

# ── Configuration ────────────────────────────────────────────────────────────

ENDPOINT = "http://localhost:4566"
REGION = "us-east-1"
CREDS = {"aws_access_key_id": "test", "aws_secret_access_key": "testing"}
BUCKET = "s3-bench-bucket"
TABLE = "s3-bench-table"


@dataclass
class BenchResult:
    name: str
    vanilla_us: float
    patched_us: float
    speedup: float
    saved_us: float
    iterations: int
    status: str = "pass"  # pass, regression, improvement


@dataclass
class BenchSuite:
    python_version: str
    gil_enabled: bool
    patches: list
    results: list = field(default_factory=list)
    timestamp: str = ""

    @property
    def total_vanilla(self):
        return sum(r.vanilla_us for r in self.results)

    @property
    def total_patched(self):
        return sum(r.patched_us for r in self.results)

    @property
    def overall_speedup(self):
        return self.total_vanilla / self.total_patched if self.total_patched > 0 else 0


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_s3():
    return boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)

def make_ddb():
    return boto3.client("dynamodb", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)


def interleaved_bench(name, vanilla_fn, patched_fn, n=200, warmup=30):
    """A/B benchmark with interleaving to cancel server variance.
    
    Calls unpatch/patch between each pair to ensure vanilla_fn truly
    runs unpatched botocore and patched_fn runs patched botocore.
    """
    import faster_boto3

    # Warmup both paths
    for _ in range(warmup):
        faster_boto3.unpatch()
        vanilla_fn()
        faster_boto3.patch()
        patched_fn()

    v_times = []
    p_times = []

    for _ in range(n):
        faster_boto3.unpatch()
        t = time.perf_counter()
        vanilla_fn()
        v_times.append(time.perf_counter() - t)

        faster_boto3.patch()
        t = time.perf_counter()
        patched_fn()
        p_times.append(time.perf_counter() - t)

    # Trim outliers (top/bottom 5%)
    trim = max(1, n // 20)
    v_times.sort()
    p_times.sort()
    v_trimmed = v_times[trim:-trim]
    p_trimmed = p_times[trim:-trim]

    v_avg = sum(v_trimmed) / len(v_trimmed) * 1e6
    p_avg = sum(p_trimmed) / len(p_trimmed) * 1e6
    speedup = v_avg / p_avg if p_avg > 0 else 0
    saved = v_avg - p_avg

    status = "improvement" if speedup > 1.03 else "regression" if speedup < 0.95 else "pass"

    return BenchResult(
        name=name, vanilla_us=round(v_avg, 1), patched_us=round(p_avg, 1),
        speedup=round(speedup, 3), saved_us=round(saved, 1),
        iterations=n, status=status,
    )
# ── Setup / Teardown ────────────────────────────────────────────────────────

def setup():
    s3 = make_s3()
    try:
        s3.create_bucket(Bucket=BUCKET)
    except Exception:
        pass

    # Test objects at various sizes
    for size_label, size in [("1k", 1024), ("10k", 10240), ("100k", 102400)]:
        s3.put_object(Bucket=BUCKET, Key=f"obj-{size_label}", Body=os.urandom(size))

    # Objects for ListObjects
    for i in range(20):
        s3.put_object(Bucket=BUCKET, Key=f"list/item-{i:03d}.txt", Body=f"data-{i}".encode())

    # DynamoDB table
    ddb = make_ddb()
    try:
        ddb.delete_table(TableName=TABLE)
        ddb.get_waiter("table_not_exists").wait(TableName=TABLE)
    except Exception:
        pass

    ddb.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.get_waiter("table_exists").wait(TableName=TABLE)

    for i in range(30):
        ddb.put_item(TableName=TABLE, Item={
            "pk": {"S": f"user-{i}"},
            "name": {"S": f"User {i}"},
            "email": {"S": f"user{i}@example.com"},
            "score": {"N": str(i * 100)},
            "active": {"BOOL": True},
        })


def teardown():
    s3 = make_s3()
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET):
            for obj in page.get("Contents", []):
                s3.delete_object(Bucket=BUCKET, Key=obj["Key"])
        s3.delete_bucket(Bucket=BUCKET)
    except Exception:
        pass

    try:
        make_ddb().delete_table(TableName=TABLE)
    except Exception:
        pass


# ── Benchmark Suite ──────────────────────────────────────────────────────────

def run_suite(n=200, quick=False):
    if quick:
        n = 50

    import faster_boto3

    suite = BenchSuite(
        python_version=sys.version.split()[0],
        gil_enabled=sys._is_gil_enabled() if hasattr(sys, "_is_gil_enabled") else True,
        patches=[],
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )

    # Discover patches by doing a trial patch
    suite.patches = faster_boto3.patch() or []
    faster_boto3.unpatch()

    # Single set of clients — the bench function handles patch/unpatch
    s3 = make_s3()
    ddb = make_ddb()

    data_1k = os.urandom(1024)
    data_10k = os.urandom(10240)
    data_100k = os.urandom(102400)

    # ── S3 GET ───────────────────────────────────────────────────────
    for label, key in [("1KB", "obj-1k"), ("10KB", "obj-10k"), ("100KB", "obj-100k")]:
        fn = lambda k=key: s3.get_object(Bucket=BUCKET, Key=k)["Body"].read()
        suite.results.append(interleaved_bench(f"S3 GetObject ({label})", fn, fn, n=n))

    # ── S3 PUT ───────────────────────────────────────────────────────
    for label, data in [("1KB", data_1k), ("10KB", data_10k), ("100KB", data_100k)]:
        fn = lambda d=data: s3.put_object(Bucket=BUCKET, Key="bench-put", Body=d)
        suite.results.append(interleaved_bench(f"S3 PutObject ({label})", fn, fn, n=n))

    # ── S3 LIST ──────────────────────────────────────────────────────
    fn = lambda: s3.list_objects_v2(Bucket=BUCKET, Prefix="list/")
    suite.results.append(interleaved_bench("S3 ListObjectsV2 (20 keys)", fn, fn, n=n))

    # ── S3 HEAD ──────────────────────────────────────────────────────
    fn = lambda: s3.head_object(Bucket=BUCKET, Key="obj-1k")
    suite.results.append(interleaved_bench("S3 HeadObject", fn, fn, n=n))

    # ── DynamoDB GET ─────────────────────────────────────────────────
    fn = lambda: ddb.get_item(TableName=TABLE, Key={"pk": {"S": "user-1"}})
    suite.results.append(interleaved_bench("DynamoDB GetItem", fn, fn, n=n))

    # ── DynamoDB PUT ─────────────────────────────────────────────────
    fn = lambda: ddb.put_item(TableName=TABLE, Item={"pk": {"S": "bench"}, "n": {"S": "x"}, "v": {"N": "1"}})
    suite.results.append(interleaved_bench("DynamoDB PutItem", fn, fn, n=n))

    # ── DynamoDB SCAN ────────────────────────────────────────────────
    fn = lambda: ddb.scan(TableName=TABLE)
    suite.results.append(interleaved_bench("DynamoDB Scan (30 items)", fn, fn, n=n))

    # ── DynamoDB BatchWrite ──────────────────────────────────────────
    batch_items = [{"PutRequest": {"Item": {"pk": {"S": f"batch-{i}"}, "d": {"S": "x"}}}} for i in range(25)]
    fn = lambda: ddb.batch_write_item(RequestItems={TABLE: batch_items})
    suite.results.append(interleaved_bench("DynamoDB BatchWrite (25)", fn, fn, n=n))

    return suite
# ── Output ───────────────────────────────────────────────────────────────────

def print_table(suite):
    print(f"\nfaster-boto3 S3 Benchmark Suite")
    print(f"Python {suite.python_version} | GIL={'on' if suite.gil_enabled else 'off'} | Patches: {suite.patches}")
    print(f"{'─' * 78}")
    fmt = "{:<30} {:>10} {:>10} {:>8} {:>8} {:>6}"
    print(fmt.format("Operation", "Vanilla", "Patched", "Speedup", "Saved", "Status"))
    print(fmt.format("─" * 30, "─" * 10, "─" * 10, "─" * 8, "─" * 8, "─" * 6))

    for r in suite.results:
        status_icon = {"improvement": "+", "regression": "!", "pass": "="}[r.status]
        print(fmt.format(
            r.name,
            f"{r.vanilla_us:.0f}us",
            f"{r.patched_us:.0f}us",
            f"{r.speedup:.2f}x",
            f"{r.saved_us:+.0f}us",
            f"[{status_icon}]",
        ))

    print(fmt.format("─" * 30, "─" * 10, "─" * 10, "─" * 8, "─" * 8, "─" * 6))
    print(fmt.format(
        "TOTAL",
        f"{suite.total_vanilla:.0f}us",
        f"{suite.total_patched:.0f}us",
        f"{suite.overall_speedup:.2f}x",
        f"{suite.total_vanilla - suite.total_patched:+.0f}us",
        "",
    ))


def print_json(suite):
    out = {
        "python_version": suite.python_version,
        "gil_enabled": suite.gil_enabled,
        "patches": suite.patches,
        "timestamp": suite.timestamp,
        "overall_speedup": suite.overall_speedup,
        "results": [asdict(r) for r in suite.results],
    }
    print(json_mod.dumps(out, indent=2))


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="S3 acceleration benchmarks")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--ci", action="store_true", help="Fail on regressions")
    parser.add_argument("--quick", action="store_true", help="Reduced iterations")
    parser.add_argument("-n", type=int, default=200, help="Iterations per test")
    args = parser.parse_args()

    # Check LocalStack is running
    try:
        make_s3().list_buckets()
    except Exception as e:
        print(f"ERROR: LocalStack not reachable at {ENDPOINT}: {e}", file=sys.stderr)
        print("Start it with: docker compose up -d", file=sys.stderr)
        sys.exit(1)

    setup()
    try:
        suite = run_suite(n=args.n, quick=args.quick)
    finally:
        teardown()

    if args.json:
        print_json(suite)
    else:
        print_table(suite)

    if args.ci:
        regressions = [r for r in suite.results if r.status == "regression"]
        if regressions:
            print(f"\nFAILED: {len(regressions)} regression(s) detected:", file=sys.stderr)
            for r in regressions:
                print(f"  {r.name}: {r.speedup:.2f}x (expected >= 0.95x)", file=sys.stderr)
            sys.exit(1)
        else:
            improvements = [r for r in suite.results if r.status == "improvement"]
            print(f"\nPASSED: {len(improvements)} improvement(s), 0 regressions")


if __name__ == "__main__":
    main()
