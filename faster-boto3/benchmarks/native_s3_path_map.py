#!/usr/bin/env python3
"""Exact request-path map for the current S3 benchmark modes.

This is intentionally static and explicit. The point is to have a single place
where the request path is spelled out step-by-step so optimization work can
target named stages rather than vague "overhead".
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Stage:
    name: str
    layer: str
    file: str
    detail: str


PATHS: dict[str, list[Stage]] = {
    "fastapi_boto3_get": [
        Stage("accept_http", "framework", "benchmarks/turbo_vs_fast_s3.py", "Uvicorn accepts HTTP request and routes to FastAPI handler."),
        Stage("python_route", "framework", "benchmarks/turbo_vs_fast_s3.py", "FastAPI Python route function executes."),
        Stage("boto3_client_call", "sdk", "benchmarks/turbo_vs_fast_s3.py", "Route calls boto3 S3 client."),
        Stage("botocore_serialize", "sdk", "botocore", "Botocore builds request shape, URL, headers, and auth context."),
        Stage("botocore_sign", "sdk", "botocore", "Botocore SigV4 signing runs in Python."),
        Stage("urllib3_send", "transport", "botocore/urllib3", "urllib3-backed HTTP transport sends request."),
        Stage("localstack_s3", "service", "LocalStack", "LocalStack handles S3 request and returns payload."),
        Stage("botocore_parse", "sdk", "botocore", "Botocore parses headers/body into Python objects."),
        Stage("python_json_response", "framework", "benchmarks/turbo_vs_fast_s3.py", "FastAPI serializes Python dict back to JSON."),
    ],
    "turbo_faster_boto3_get": [
        Stage("accept_http", "framework", "zig/src/server.zig", "TurboNet Zig HTTP server accepts request."),
        Stage("python_route_dispatch", "framework", "python/turboapi/zig_integration.py", "TurboAPI dispatches to Python route handler."),
        Stage("python_route", "framework", "benchmarks/turbo_vs_fast_s3.py", "Python route calls faster_boto3 client."),
        Stage("native_s3_shim", "sdk", "faster_boto3/native_s3.py", "NativeS3Client builds S3 path/query and chooses operation path."),
        Stage("sign_headers", "sdk", "faster_boto3/native_s3.py", "Python-native S3 shim computes SigV4 headers."),
        Stage("http_accel_send", "transport", "zig/src/http_py.zig", "Zig HTTP accelerator sends request through extension module."),
        Stage("localstack_s3", "service", "LocalStack", "LocalStack handles S3 request and returns payload."),
        Stage("native_parse", "sdk", "faster_boto3/native_s3.py", "Native shim parses headers/body into boto3-shaped result."),
        Stage("python_json_response", "framework", "benchmarks/turbo_vs_fast_s3.py", "Turbo Python route returns JSON dict."),
    ],
    "turbo_native_ffi_get": [
        Stage("accept_http", "framework", "zig/src/server.zig", "TurboNet Zig HTTP server accepts request."),
        Stage("ffi_route_match", "framework", "zig/src/server.zig", "Native FFI route matched without entering Python."),
        Stage("ffi_handler", "sdk", "benchmarks/native_s3_handler.zig", "Zig FFI handler extracts params and builds canonical S3 request."),
        Stage("sign_headers", "sdk", "benchmarks/native_s3_handler.zig", "Stack-buffer signer builds canonical request and Authorization header."),
        Stage("threadlocal_http_client", "transport", "benchmarks/native_s3_handler.zig", "Thread-local Zig std.http.Client sends request."),
        Stage("localstack_s3", "service", "LocalStack", "LocalStack handles S3 request and returns payload."),
        Stage("ffi_parse", "sdk", "benchmarks/native_s3_handler.zig", "Zig FFI handler parses headers/body into small JSON payload."),
        Stage("write_http_response", "framework", "zig/src/server.zig", "TurboNet writes prebuilt JSON response bytes back to client."),
    ],
    "turbo_native_ffi_head": [
        Stage("accept_http", "framework", "zig/src/server.zig", "TurboNet Zig HTTP server accepts request."),
        Stage("ffi_route_match", "framework", "zig/src/server.zig", "Native FFI route matched without entering Python."),
        Stage("ffi_handler", "sdk", "benchmarks/native_s3_handler.zig", "Zig FFI head handler extracts key and builds canonical HEAD request."),
        Stage("sign_headers", "sdk", "benchmarks/native_s3_handler.zig", "Thread-local signer cache provides date-keyed signing material."),
        Stage("threadlocal_http_client", "transport", "benchmarks/native_s3_handler.zig", "Thread-local Zig std.http.Client sends HEAD request."),
        Stage("localstack_s3", "service", "LocalStack", "LocalStack handles S3 HEAD and returns headers."),
        Stage("ffi_header_parse", "sdk", "benchmarks/native_s3_handler.zig", "Zig FFI handler parses Content-Length and emits JSON."),
        Stage("write_http_response", "framework", "zig/src/server.zig", "TurboNet writes JSON response directly."),
    ],
    "turbo_native_ffi_list": [
        Stage("accept_http", "framework", "zig/src/server.zig", "TurboNet Zig HTTP server accepts request."),
        Stage("ffi_route_match", "framework", "zig/src/server.zig", "Native FFI route matched without entering Python."),
        Stage("ffi_handler", "sdk", "benchmarks/native_s3_handler.zig", "Zig FFI list handler builds list-type=2 request."),
        Stage("sign_headers", "sdk", "benchmarks/native_s3_handler.zig", "Stack-buffer signer builds canonical query and auth header."),
        Stage("threadlocal_http_client", "transport", "benchmarks/native_s3_handler.zig", "Thread-local Zig std.http.Client sends GET request."),
        Stage("localstack_s3", "service", "LocalStack", "LocalStack handles S3 list call and returns XML."),
        Stage("xml_tag_count", "sdk", "benchmarks/native_s3_handler.zig", "Zig FFI handler counts <Contents> tags in XML response."),
        Stage("write_http_response", "framework", "zig/src/server.zig", "TurboNet writes compact JSON response directly."),
    ],
}


def render_text() -> str:
    lines: list[str] = []
    for name, stages in PATHS.items():
        lines.append(name)
        for idx, stage in enumerate(stages, start=1):
            lines.append(
                f"  {idx}. {stage.name} [{stage.layer}] "
                f"{stage.file} - {stage.detail}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.json:
        print(json.dumps({k: [asdict(s) for s in v] for k, v in PATHS.items()}, indent=2))
    else:
        print(render_text())


if __name__ == "__main__":
    main()
