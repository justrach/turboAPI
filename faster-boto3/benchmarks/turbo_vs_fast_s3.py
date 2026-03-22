#!/usr/bin/env python3
"""
TurboAPI + faster-boto3 vs FastAPI + boto3 — end-to-end S3 benchmark.

Spins up two HTTP servers:
  - TurboAPI (port 9100) with faster-boto3 (Zig HTTP transport)
  - FastAPI  (port 9200) with vanilla boto3

Both serve identical S3 endpoints against LocalStack, then benchmarks with wrk.

Usage:
    # Start LocalStack first:
    docker compose up -d

    python benchmarks/turbo_vs_fast_s3.py
    python benchmarks/turbo_vs_fast_s3.py --json
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

LOCALSTACK = "http://localhost:4566"
BUCKET = "turbo-vs-fast"
REGION = "us-east-1"
CREDS = {"aws_access_key_id": "test", "aws_secret_access_key": "testing"}

TURBO_PORT = 9100
FAST_PORT = 9200
WRK_THREADS = 4
WRK_CONNECTIONS = 50
WRK_DURATION = 5
HERE = os.path.dirname(os.path.abspath(__file__))
NATIVE_HANDLER_LIB = os.path.join(HERE, "libnative_s3_handler.dylib")


# ── Server apps (written to temp files, run as subprocesses) ─────────────────

TURBO_APP = f"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import faster_boto3 as boto3

s3 = boto3.client('s3', endpoint_url='{LOCALSTACK}', region_name='{REGION}',
                  aws_access_key_id='test', aws_secret_access_key='testing')

from turboapi import TurboAPI
app = TurboAPI(title="TurboBoto Bench")

@app.get("/health")
def health():
    return {{"status": "ok"}}

@app.get("/s3/get/{{key}}")
def s3_get(key: str):
    resp = s3.get_object(Bucket='{BUCKET}', Key=key)
    return {{"key": key, "size": resp["ContentLength"]}}

@app.get("/s3/head/{{key}}")
def s3_head(key: str):
    resp = s3.head_object(Bucket='{BUCKET}', Key=key)
    return {{"key": key, "size": resp["ContentLength"]}}

@app.get("/s3/list")
def s3_list():
    resp = s3.list_objects_v2(Bucket='{BUCKET}', MaxKeys=20)
    return {{"count": resp.get("KeyCount", 0)}}

app.run(host="127.0.0.1", port={TURBO_PORT})
"""

TURBO_NATIVE_FFI_APP = f"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from turboapi import TurboAPI

app = TurboAPI(title="TurboNativeFFIBench")
app.static_route("GET", "/health", '{{"status":"ok"}}')
app.native_route("GET", "/s3/get/{{key}}", r"{NATIVE_HANDLER_LIB}", "handle_s3_get")
app.native_route("GET", "/s3/head/{{key}}", r"{NATIVE_HANDLER_LIB}", "handle_s3_head")
app.native_route("GET", "/s3/head-bucket", r"{NATIVE_HANDLER_LIB}", "handle_s3_head_bucket")
app.native_route("GET", "/s3/list", r"{NATIVE_HANDLER_LIB}", "handle_s3_list")
app.native_route("DELETE", "/s3/delete/{{key}}", r"{NATIVE_HANDLER_LIB}", "handle_s3_delete")
app.native_route("PUT", "/s3/copy/{{src}}/{{dst}}", r"{NATIVE_HANDLER_LIB}", "handle_s3_copy")
app.run(host="127.0.0.1", port={TURBO_PORT})
"""

FAST_APP = f"""
import boto3
from fastapi import FastAPI
import uvicorn

s3 = boto3.client('s3', endpoint_url='{LOCALSTACK}', region_name='{REGION}',
                  aws_access_key_id='test', aws_secret_access_key='testing')

app = FastAPI()

@app.get("/health")
def health():
    return {{"status": "ok"}}

@app.get("/s3/get/{{key}}")
def s3_get(key: str):
    resp = s3.get_object(Bucket='{BUCKET}', Key=key)
    body = resp["Body"].read()
    return {{"key": key, "size": len(body)}}

@app.get("/s3/head/{{key}}")
def s3_head(key: str):
    resp = s3.head_object(Bucket='{BUCKET}', Key=key)
    return {{"key": key, "size": resp["ContentLength"]}}

@app.get("/s3/list")
def s3_list():
    resp = s3.list_objects_v2(Bucket='{BUCKET}', MaxKeys=20)
    return {{"count": resp.get("KeyCount", 0)}}

uvicorn.run(app, host="127.0.0.1", port={FAST_PORT}, log_level="warning")
"""


# ── Helpers ──────────────────────────────────────────────────────────────────

def parse_wrk(output):
    """Parse wrk output into structured data."""
    rps = 0
    lat_avg = 0
    lat_p99 = 0
    errors = 0

    for line in output.split('\n'):
        if 'Requests/sec' in line:
            m = re.search(r'([\d.]+)', line)
            if m:
                rps = float(m.group(1))
        if 'Latency' in line and 'Distribution' not in line:
            parts = re.findall(r'([\d.]+)(us|ms|s)', line)
            if parts:
                val, unit = float(parts[0][0]), parts[0][1]
                if unit == 's':
                    lat_avg = val * 1000
                elif unit == 'ms':
                    lat_avg = val
                elif unit == 'us':
                    lat_avg = val / 1000
        if '99%' in line:
            parts = re.findall(r'([\d.]+)(us|ms|s)', line)
            if parts:
                val, unit = float(parts[0][0]), parts[0][1]
                if unit == 's':
                    lat_p99 = val * 1000
                elif unit == 'ms':
                    lat_p99 = val
                elif unit == 'us':
                    lat_p99 = val / 1000
        if 'Socket errors' in line:
            nums = re.findall(r'\d+', line)
            errors = sum(int(n) for n in nums)

    return {"rps": rps, "lat_avg_ms": lat_avg, "lat_p99_ms": lat_p99, "errors": errors}


def run_wrk(port, path, duration=WRK_DURATION, threads=WRK_THREADS, connections=WRK_CONNECTIONS):
    cmd = [
        "wrk", f"-t{threads}", f"-c{connections}", f"-d{duration}s",
        "--latency", f"http://127.0.0.1:{port}{path}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 30)
        return parse_wrk(result.stdout + result.stderr)
    except FileNotFoundError:
        print("ERROR: wrk not found. Install with: brew install wrk", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        return {"rps": 0, "lat_avg_ms": 0, "lat_p99_ms": 0, "errors": -1}


def start_server(code, name):
    """Write server code to temp file and start as subprocess."""
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, prefix=f'{name}_')
    f.write(code)
    f.close()
    # Set PYTHONPATH so subprocesses can find turboapi + faster_boto3
    env = os.environ.copy()
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parent_root = os.path.dirname(project_root)
    paths = [
        project_root,                          # faster-boto3/
        os.path.join(parent_root, "python"),   # turboAPI/python/
    ]
    env["PYTHONPATH"] = ":".join(paths) + ":" + env.get("PYTHONPATH", "")
    if name == "turbo":
        # Free-threaded CPython will silently re-enable the GIL for subprocesses
        # unless the interpreter is launched with PYTHON_GIL=0. That completely
        # changes TurboAPI throughput under load, so force the intended runtime.
        env.setdefault("PYTHON_GIL", "0")
    proc = subprocess.Popen(
        [sys.executable, f.name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=env,
    )
    return proc, f.name


def build_native_handler():
    subprocess.run([sys.executable, os.path.join(HERE, "build_native_s3_handler.py")], check=True)
def wait_for_server(port, timeout=15):
    """Wait for server to be ready."""
    import urllib.request
    url = f"http://127.0.0.1:{port}/health"
    for _ in range(timeout * 10):
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def setup_s3():
    """Create test bucket and objects."""
    import boto3
    s3 = boto3.client('s3', endpoint_url=LOCALSTACK, region_name=REGION, **CREDS)
    try:
        s3.create_bucket(Bucket=BUCKET)
    except Exception:
        pass
    s3.put_object(Bucket=BUCKET, Key="bench-1k", Body=os.urandom(1024))
    s3.put_object(Bucket=BUCKET, Key="bench-10k", Body=os.urandom(10240))
    for i in range(20):
        s3.put_object(Bucket=BUCKET, Key=f"list/item-{i:03d}", Body=f"data-{i}".encode())


def cleanup_s3():
    import boto3
    s3 = boto3.client('s3', endpoint_url=LOCALSTACK, region_name=REGION, **CREDS)
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET):
            for obj in page.get("Contents", []):
                s3.delete_object(Bucket=BUCKET, Key=obj["Key"])
        s3.delete_bucket(Bucket=BUCKET)
    except Exception:
        pass


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--duration", type=int, default=WRK_DURATION)
    parser.add_argument("--threads", type=int, default=WRK_THREADS)
    parser.add_argument("--connections", type=int, default=WRK_CONNECTIONS)
    parser.add_argument("--turbo-mode", choices=("python", "native-ffi"), default="python")
    args = parser.parse_args()

    # Check LocalStack
    try:
        import urllib.request
        urllib.request.urlopen(f"{LOCALSTACK}/_localstack/health", timeout=2)
    except Exception:
        print("ERROR: LocalStack not running. Start with: docker compose up -d", file=sys.stderr)
        sys.exit(1)

    setup_s3()

    if args.turbo_mode == "native-ffi":
        build_native_handler()

    # Start servers
    turbo_code = TURBO_NATIVE_FFI_APP if args.turbo_mode == "native-ffi" else TURBO_APP
    turbo_proc, turbo_file = start_server(turbo_code, "turbo")
    fast_proc, fast_file = start_server(FAST_APP, "fast")

    try:
        if not wait_for_server(TURBO_PORT):
            print("ERROR: TurboAPI server failed to start", file=sys.stderr)
            stderr = turbo_proc.stderr.read().decode() if turbo_proc.stderr else ""
            print(stderr[:500], file=sys.stderr)
            sys.exit(1)
        if not wait_for_server(FAST_PORT):
            print("ERROR: FastAPI server failed to start", file=sys.stderr)
            stderr = fast_proc.stderr.read().decode() if fast_proc.stderr else ""
            print(stderr[:500], file=sys.stderr)
            sys.exit(1)

        tests = [
            ("S3 GetObject (1KB)", "/s3/get/bench-1k"),
            ("S3 GetObject (10KB)", "/s3/get/bench-10k"),
            ("S3 HeadObject", "/s3/head/bench-1k"),
            ("S3 ListObjects (20)", "/s3/list"),
        ]
        results = []
        for name, path in tests:
            turbo_r = run_wrk(
                TURBO_PORT,
                path,
                duration=args.duration,
                threads=args.threads,
                connections=args.connections,
            )
            fast_r = run_wrk(
                FAST_PORT,
                path,
                duration=args.duration,
                threads=args.threads,
                connections=args.connections,
            )
            speedup = turbo_r["rps"] / fast_r["rps"] if fast_r["rps"] > 0 else 0
            results.append({
                "name": name,
                "turbo": turbo_r,
                "fastapi": fast_r,
                "speedup": round(speedup, 2),
            })

        if args.json:
            print(json.dumps({"results": results}, indent=2))
        else:
            print()
            print(f"  Load: wrk -t{args.threads} -c{args.connections} -d{args.duration}s")
            turbo_label = "TurboAPI + native FFI S3" if args.turbo_mode == "native-ffi" else "TurboAPI + faster-boto3"
            print(f"  {turbo_label}  vs  FastAPI + boto3")
            print("  " + "═" * 66)
            fmt = "  {:<25} {:>10} {:>10} {:>8} {:>8}"
            print(fmt.format("Operation", "Turbo RPS", "Fast RPS", "Speedup", "p99 lat"))
            print(fmt.format("─" * 25, "─" * 10, "─" * 10, "─" * 8, "─" * 8))
            for r in results:
                t, f = r["turbo"], r["fastapi"]
                print(fmt.format(
                    r["name"],
                    f'{t["rps"]:.0f}',
                    f'{f["rps"]:.0f}',
                    f'{r["speedup"]:.2f}x',
                    f'{t["lat_p99_ms"]:.1f}ms',
                ))
            print()

    finally:
        turbo_proc.terminate()
        fast_proc.terminate()
        turbo_proc.wait(timeout=5)
        fast_proc.wait(timeout=5)
        os.unlink(turbo_file)
        os.unlink(fast_file)
        cleanup_s3()


if __name__ == "__main__":
    main()
