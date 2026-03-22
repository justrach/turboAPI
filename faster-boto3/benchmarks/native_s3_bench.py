#!/usr/bin/env python3
"""Benchmark native S3 rollout modes against LocalStack.

This benchmark measures the first native S3 migration slice under three modes:

- legacy: botocore path only
- native_shadow: execute native and botocore, return botocore
- native: native path for supported methods, fallback otherwise

Each mode runs in a fresh subprocess so import-time patching and env flags do not
bleed across measurements.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import boto3

ENDPOINT = "http://localhost:4566"
REGION = "us-east-1"
CREDS = {"aws_access_key_id": "test", "aws_secret_access_key": "testing"}
BUCKET = "native-s3-bench-bucket"

DEFAULT_ITERATIONS = 120
DEFAULT_WARMUP = 20
TRIM_RATIO = 0.05

MODES = ("legacy", "native_shadow", "native", "raw_native")
OPERATIONS = (
    "head_object",
    "get_object_1k",
    "get_object_8m",
    "put_object_1k",
    "put_object_file_1m",
    "put_object_file_8m",
    "list_objects_v2",
    "copy_object",
)


def make_s3():
    return boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)


def setup_bucket():
    s3 = make_s3()
    try:
        s3.create_bucket(Bucket=BUCKET)
    except Exception:
        pass

    s3.put_object(Bucket=BUCKET, Key="bench/head.txt", Body=b"head-body")
    s3.put_object(Bucket=BUCKET, Key="bench/get-1k.bin", Body=os.urandom(1024))
    s3.put_object(Bucket=BUCKET, Key="bench/get-8m.bin", Body=os.urandom(8 * 1024 * 1024))
    s3.put_object(Bucket=BUCKET, Key="bench/copy-source.bin", Body=os.urandom(4096))

    for i in range(50):
        s3.put_object(
            Bucket=BUCKET,
            Key=f"bench/list/item-{i:03d}.txt",
            Body=f"data-{i}".encode(),
        )


def teardown_bucket():
    s3 = make_s3()
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET):
            for obj in page.get("Contents", []):
                s3.delete_object(Bucket=BUCKET, Key=obj["Key"])
        s3.delete_bucket(Bucket=BUCKET)
    except Exception:
        pass


def _trimmed_us(samples: list[float]) -> float:
    ordered = sorted(samples)
    trim = max(1, int(len(ordered) * TRIM_RATIO))
    trimmed = ordered[trim:-trim] if len(ordered) > (trim * 2) else ordered
    return statistics.fmean(trimmed) * 1e6


def _summarize_samples(samples: list[float]) -> dict[str, float]:
    return {
        "avg_us": round(_trimmed_us(samples), 1),
        "median_us": round(statistics.median(samples) * 1e6, 1),
    }


def _parity_summary() -> dict:
    service_model = make_s3().meta.service_model
    operation_names = set(service_model.operation_names)
    implemented = {
        "HeadObject",
        "GetObject",
        "PutObject",
        "ListObjectsV2",
        "DeleteObject",
        "DeleteObjects",
        "CopyObject",
        "CreateMultipartUpload",
        "UploadPart",
        "UploadPartCopy",
        "CompleteMultipartUpload",
        "AbortMultipartUpload",
        "ListParts",
        "ListMultipartUploads",
    }
    missing = sorted(operation_names - implemented)
    return {
        "implemented": len(implemented),
        "total": len(operation_names),
        "coverage_pct": round((len(implemented) / len(operation_names)) * 100, 1),
        "missing_sample": missing[:12],
    }


def _raw_phase_payload(s3) -> dict:
    from faster_boto3 import native_s3 as native_mod

    timings = {
        "head_object": {"prep": [], "transport": [], "parse": [], "total": []},
        "get_object_1k": {"prep": [], "transport": [], "parse": [], "total": []},
        "get_object_8m": {"prep": [], "transport": [], "parse": [], "total": []},
        "put_object_1k": {"prep": [], "transport": [], "parse": [], "total": []},
        "put_object_file_1m": {"prep": [], "transport": [], "parse": [], "total": []},
        "put_object_file_8m": {"prep": [], "transport": [], "parse": [], "total": []},
        "list_objects_v2": {"prep": [], "transport": [], "parse": [], "total": []},
        "copy_object": {"prep": [], "transport": [], "parse": [], "total": []},
    }

    tmp_path = None
    tmp_path_large = None

    def measure(name: str, prepare, transport, parse):
        total_start = time.perf_counter()

        prep_start = total_start
        prepared = prepare()
        prep_end = time.perf_counter()

        transport_start = prep_end
        response = transport(prepared)
        transport_end = time.perf_counter()

        parse_start = transport_end
        parse(prepared, response)
        parse_end = time.perf_counter()

        timings[name]["prep"].append(prep_end - prep_start)
        timings[name]["transport"].append(transport_end - transport_start)
        timings[name]["parse"].append(parse_end - parse_start)
        timings[name]["total"].append(parse_end - total_start)

    def head_prepare():
        path, query, url = s3._build_url(BUCKET, "bench/head.txt")
        payload_hash = native_mod._sigv4_accel_module().sha256_hex(b"")
        headers = s3._signed_headers("HEAD", path, query, payload_hash, body=None)
        return {"path": path, "query": query, "url": url, "headers": headers}

    def head_transport(prepared):
        return native_mod._http_accel_module().request("HEAD", prepared["url"], prepared["headers"], None)

    def head_parse(_prepared, response):
        status, resp_headers, resp_body = response
        parsed_headers = native_mod._parse_headers(resp_headers)
        s3._raise_for_error("HeadObject", status, parsed_headers, resp_body)
        s3._metadata_from_headers(parsed_headers)

    def get_prepare():
        path, query, url = s3._build_url(BUCKET, "bench/get-1k.bin")
        payload_hash = native_mod._sigv4_accel_module().sha256_hex(b"")
        headers = s3._signed_headers("GET", path, query, payload_hash, body=None)
        return {"path": path, "query": query, "url": url, "headers": headers}

    def get_large_prepare():
        path, query, url = s3._build_url(BUCKET, "bench/get-8m.bin")
        payload_hash = native_mod._sigv4_accel_module().sha256_hex(b"")
        headers = s3._signed_headers("GET", path, query, payload_hash, body=None)
        return {"path": path, "query": query, "url": url, "headers": headers}

    def get_transport(prepared):
        return native_mod._http_accel_module().request("GET", prepared["url"], prepared["headers"], None)

    def get_parse(_prepared, response):
        status, resp_headers, resp_body = response
        parsed_headers = native_mod._parse_headers(resp_headers)
        s3._raise_for_error("GetObject", status, parsed_headers, resp_body)
        native_mod.StreamingBody(native_mod.io.BytesIO(resp_body), len(resp_body))
        s3._metadata_from_headers(parsed_headers)

    def put_bytes_prepare():
        path, query, url = s3._build_url(BUCKET, "bench/put-1k.bin")
        body_bytes = b"x" * 1024
        payload_hash = native_mod._sigv4_accel_module().sha256_hex(body_bytes)
        extra_headers = [
            ("x-amz-checksum-crc32", native_mod._base64_crc32(body_bytes)),
            ("x-amz-sdk-checksum-algorithm", "CRC32"),
        ]
        headers = s3._signed_headers("PUT", path, query, payload_hash, body=body_bytes, extra_headers=extra_headers)
        return {"url": url, "headers": headers, "body_bytes": body_bytes, "fd_request": None}

    def put_file_prepare():
        nonlocal tmp_path
        if tmp_path is None:
            fd, tmp_path = tempfile.mkstemp(prefix="native-s3-phase-", suffix=".bin")
            os.close(fd)
            with open(tmp_path, "wb") as handle:
                handle.write(os.urandom(1024 * 1024))
        path, query, url = s3._build_url(BUCKET, "bench/put-file-1m.bin")
        body_handle = open(tmp_path, "rb")
        fd_request = s3._file_request(body_handle)
        headers = s3._signed_headers("PUT", path, query, native_mod._UNSIGNED_PAYLOAD, body=None)
        return {
            "url": url,
            "headers": headers,
            "body_bytes": b"",
            "fd_request": fd_request,
            "body_handle": body_handle,
        }

    def put_file_large_prepare():
        nonlocal tmp_path_large
        if tmp_path_large is None:
            fd, tmp_path_large = tempfile.mkstemp(prefix="native-s3-phase-large-", suffix=".bin")
            os.close(fd)
            with open(tmp_path_large, "wb") as handle:
                handle.write(os.urandom(8 * 1024 * 1024))
        return {
            "body_handle": open(tmp_path_large, "rb"),
        }

    def put_transport(prepared):
        if prepared["fd_request"] is not None:
            return native_mod._http_accel_module().request_fd(
                "PUT",
                prepared["url"],
                prepared["headers"],
                *prepared["fd_request"],
            )
        return native_mod._http_accel_module().request("PUT", prepared["url"], prepared["headers"], prepared["body_bytes"])

    def put_parse(_prepared, response):
        try:
            status, resp_headers, resp_body = response
            parsed_headers = native_mod._parse_headers(resp_headers)
            s3._raise_for_error("PutObject", status, parsed_headers, resp_body)
        finally:
            body_handle = _prepared.get("body_handle")
            if body_handle is not None:
                body_handle.close()

    def multipart_transport(prepared):
        return s3._native_put_object(Bucket=BUCKET, Key="bench/put-file-8m.bin", Body=prepared["body_handle"])

    def multipart_parse(prepared, _response):
        body_handle = prepared.get("body_handle")
        if body_handle is not None:
            body_handle.close()

    def list_prepare():
        path, query, url = s3._build_url(BUCKET, None, params={"list-type": 2, "prefix": "bench/list/"})
        payload_hash = native_mod._sigv4_accel_module().sha256_hex(b"")
        headers = s3._signed_headers("GET", path, query, payload_hash, body=None)
        return {"url": url, "headers": headers}

    def list_transport(prepared):
        return native_mod._http_accel_module().request("GET", prepared["url"], prepared["headers"], None)

    def list_parse(_prepared, response):
        status, resp_headers, resp_body = response
        parsed_headers = native_mod._parse_headers(resp_headers)
        s3._raise_for_error("ListObjectsV2", status, parsed_headers, resp_body)
        s3._parse_list_objects(resp_body)

    def copy_prepare():
        path, query, url = s3._build_url(BUCKET, "bench/copy-target.bin")
        payload_hash = native_mod._sigv4_accel_module().sha256_hex(b"")
        headers = s3._signed_headers(
            "PUT",
            path,
            query,
            payload_hash,
            body=None,
            extra_headers=[("x-amz-copy-source", s3._format_copy_source({"Bucket": BUCKET, "Key": "bench/copy-source.bin"}))],
        )
        return {"url": url, "headers": headers}

    def copy_transport(prepared):
        return native_mod._http_accel_module().request("PUT", prepared["url"], prepared["headers"], None)

    def copy_parse(_prepared, response):
        status, resp_headers, resp_body = response
        parsed_headers = native_mod._parse_headers(resp_headers)
        s3._raise_for_error("CopyObject", status, parsed_headers, resp_body)
        s3._parse_copy_object(resp_body)

    scenarios = {
        "head_object": (head_prepare, head_transport, head_parse),
        "get_object_1k": (get_prepare, get_transport, get_parse),
        "get_object_8m": (get_large_prepare, get_transport, get_parse),
        "put_object_1k": (put_bytes_prepare, put_transport, put_parse),
        "put_object_file_1m": (put_file_prepare, put_transport, put_parse),
        "put_object_file_8m": (put_file_large_prepare, multipart_transport, multipart_parse),
        "list_objects_v2": (list_prepare, list_transport, list_parse),
        "copy_object": (copy_prepare, copy_transport, copy_parse),
    }

    try:
        for name, (prepare, transport, parse) in scenarios.items():
            for _ in range(8):
                measure(name, prepare, transport, parse)
        for name, (prepare, transport, parse) in scenarios.items():
            for _ in range(40):
                measure(name, prepare, transport, parse)
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
        if tmp_path_large is not None:
            try:
                os.unlink(tmp_path_large)
            except FileNotFoundError:
                pass

    return {
        op_name: {
            phase: _summarize_samples(samples)
            for phase, samples in phases.items()
        }
        for op_name, phases in timings.items()
    }


def _worker_payload(mode: str, iterations: int, warmup: int) -> dict:
    import faster_boto3
    from faster_boto3.native_s3 import NativeS3Client

    if mode == "raw_native":
        fallback = boto3.client(
            "s3",
            endpoint_url=ENDPOINT,
            region_name=REGION,
            **CREDS,
        )
        s3 = NativeS3Client.from_botocore_client(fallback, mode="native")
        client_type = f"{type(s3).__name__}._native_*"
    else:
        s3 = faster_boto3.client(
            "s3",
            endpoint_url=ENDPOINT,
            region_name=REGION,
            **CREDS,
        )
        client_type = type(s3).__name__
    tmp_path = None
    tmp_path_large = None
    timings = {name: [] for name in OPERATIONS}

    def invoke(public_name: str, native_name: str, /, **kwargs):
        if mode == "raw_native":
            return getattr(s3, native_name)(**kwargs)
        return getattr(s3, public_name)(**kwargs)

    def op_head_object():
        invoke("head_object", "_native_head_object", Bucket=BUCKET, Key="bench/head.txt")

    def op_get_object_1k():
        invoke("get_object", "_native_get_object", Bucket=BUCKET, Key="bench/get-1k.bin")["Body"].read()

    def op_get_object_8m():
        invoke("get_object", "_native_get_object", Bucket=BUCKET, Key="bench/get-8m.bin")["Body"].read()

    def op_put_object_1k():
        invoke("put_object", "_native_put_object", Bucket=BUCKET, Key="bench/put-1k.bin", Body=b"x" * 1024)

    def op_put_object_file_1m():
        nonlocal tmp_path
        if tmp_path is None:
            fd, tmp_path = tempfile.mkstemp(prefix="native-s3-bench-", suffix=".bin")
            os.close(fd)
            with open(tmp_path, "wb") as handle:
                handle.write(os.urandom(1024 * 1024))
        with open(tmp_path, "rb") as body:
            invoke("put_object", "_native_put_object", Bucket=BUCKET, Key="bench/put-file-1m.bin", Body=body)

    def op_put_object_file_8m():
        nonlocal tmp_path_large
        if tmp_path_large is None:
            fd, tmp_path_large = tempfile.mkstemp(prefix="native-s3-bench-large-", suffix=".bin")
            os.close(fd)
            with open(tmp_path_large, "wb") as handle:
                handle.write(os.urandom(8 * 1024 * 1024))
        with open(tmp_path_large, "rb") as body:
            invoke("put_object", "_native_put_object", Bucket=BUCKET, Key="bench/put-file-8m.bin", Body=body)

    def op_list_objects_v2():
        invoke("list_objects_v2", "_native_list_objects_v2", Bucket=BUCKET, Prefix="bench/list/")

    def op_copy_object():
        invoke(
            "copy_object",
            "_native_copy_object",
            Bucket=BUCKET,
            Key="bench/copy-target.bin",
            CopySource={"Bucket": BUCKET, "Key": "bench/copy-source.bin"},
        )

    ops = {
        "head_object": op_head_object,
        "get_object_1k": op_get_object_1k,
        "get_object_8m": op_get_object_8m,
        "put_object_1k": op_put_object_1k,
        "put_object_file_1m": op_put_object_file_1m,
        "put_object_file_8m": op_put_object_file_8m,
        "list_objects_v2": op_list_objects_v2,
        "copy_object": op_copy_object,
    }

    try:
        for op in ops.values():
            for _ in range(warmup):
                op()

        for name, op in ops.items():
            for _ in range(iterations):
                start = time.perf_counter()
                op()
                timings[name].append(time.perf_counter() - start)
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
        if tmp_path_large is not None:
            try:
                os.unlink(tmp_path_large)
            except FileNotFoundError:
                pass

    return {
        "mode": mode,
        "client_type": client_type,
        "iterations": iterations,
        "warmup": warmup,
        "phase_breakdown": _raw_phase_payload(s3) if mode == "raw_native" else None,
        "results": {
            name: {
                **_summarize_samples(samples),
            }
            for name, samples in timings.items()
        },
    }


def _run_worker(mode: str, iterations: int, warmup: int) -> dict:
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent
    env = os.environ.copy()
    env["FASTER_BOTO3_NATIVE"] = mode
    env["FASTER_BOTO3_MULTIPART_THRESHOLD"] = str(5 * 1024 * 1024)
    env["FASTER_BOTO3_MULTIPART_CHUNKSIZE"] = str(5 * 1024 * 1024)
    env["FASTER_BOTO3_MULTIPART_CONCURRENCY"] = "4"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(project_root), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--worker",
            "--mode",
            mode,
            "--iterations",
            str(iterations),
            "--warmup",
            str(warmup),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"worker mode={mode} failed with exit {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return json.loads(proc.stdout)


def _print_table(payloads: dict[str, dict]):
    print("\nNative S3 Benchmark")
    print(f"Endpoint: {ENDPOINT} | Bucket: {BUCKET}")
    print(
        "Modes: "
        + ", ".join(
            f"{mode}={payloads[mode]['client_type']}" for mode in MODES
        )
    )
    print(
        f"{'Operation':<22} {'Legacy':>10} {'Shadow':>10} {'Native':>10} "
        f"{'Raw':>10} {'N Speedup':>10} {'R Speedup':>10}"
    )
    print(
        f"{'-' * 22} {'-' * 10} {'-' * 10} {'-' * 10} "
        f"{'-' * 10} {'-' * 10} {'-' * 10}"
    )
    for name in OPERATIONS:
        legacy = payloads["legacy"]["results"][name]["avg_us"]
        shadow = payloads["native_shadow"]["results"][name]["avg_us"]
        native = payloads["native"]["results"][name]["avg_us"]
        raw = payloads["raw_native"]["results"][name]["avg_us"]
        native_speedup = legacy / native if native else 0.0
        raw_speedup = legacy / raw if raw else 0.0
        print(
            f"{name:<22} {legacy:>10.1f} {shadow:>10.1f} {native:>10.1f} "
            f"{raw:>10.1f} {native_speedup:>10.3f} {raw_speedup:>10.3f}"
        )
    parity = _parity_summary()
    print(
        "\nS3 parity: "
        f"{parity['implemented']}/{parity['total']} operations "
        f"({parity['coverage_pct']}%) implemented natively"
    )
    print("Missing sample: " + ", ".join(parity["missing_sample"]))

    breakdown = payloads["raw_native"]["phase_breakdown"]
    print("\nRaw native phase breakdown (avg us)")
    print(f"{'Operation':<22} {'Prep':>10} {'Transport':>10} {'Parse':>10} {'Total':>10}")
    print(f"{'-' * 22} {'-' * 10} {'-' * 10} {'-' * 10} {'-' * 10}")
    for name in OPERATIONS:
        phases = breakdown[name]
        print(
            f"{name:<22} "
            f"{phases['prep']['avg_us']:>10.1f} "
            f"{phases['transport']['avg_us']:>10.1f} "
            f"{phases['parse']['avg_us']:>10.1f} "
            f"{phases['total']['avg_us']:>10.1f}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print machine-readable output")
    parser.add_argument("--quick", action="store_true", help="run a smaller benchmark")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=MODES, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.quick:
        args.iterations = min(args.iterations, 40)
        args.warmup = min(args.warmup, 8)

    if args.worker:
        payload = _worker_payload(args.mode, args.iterations, args.warmup)
        print(json.dumps(payload))
        return

    try:
        import urllib.request

        urllib.request.urlopen(f"{ENDPOINT}/_localstack/health", timeout=2)
    except Exception:
        print("ERROR: LocalStack not running. Start with: docker compose up -d", file=sys.stderr)
        sys.exit(1)

    setup_bucket()
    try:
        payloads = {
            mode: _run_worker(mode, args.iterations, args.warmup)
            for mode in MODES
        }
    finally:
        teardown_bucket()

    if args.json:
        print(json.dumps(payloads, indent=2, sort_keys=True))
        return

    _print_table(payloads)


if __name__ == "__main__":
    main()
