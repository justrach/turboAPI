import os
import tempfile

import boto3
import pytest

ENDPOINT = "http://localhost:4566"
REGION = "us-east-1"
CREDS = {"aws_access_key_id": "test", "aws_secret_access_key": "testing"}
BUCKET = "native-s3-test-bucket"


@pytest.fixture(scope="session")
def localstack():
    s3 = boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)
    try:
        s3.list_buckets()
    except Exception:
        pytest.skip("LocalStack not running (docker compose up -d)")


@pytest.fixture(scope="session")
def setup_bucket(localstack):
    s3 = boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)
    try:
        s3.create_bucket(Bucket=BUCKET)
    except Exception:
        pass

    s3.put_object(Bucket=BUCKET, Key="hello.txt", Body=b"Hello World!")
    for i in range(5):
        s3.put_object(Bucket=BUCKET, Key=f"list/item-{i:03d}", Body=f"data-{i}".encode())

    yield

    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET):
            for obj in page.get("Contents", []):
                s3.delete_object(Bucket=BUCKET, Key=obj["Key"])
        s3.delete_bucket(Bucket=BUCKET)
    except Exception:
        pass


@pytest.fixture()
def native_s3(setup_bucket, monkeypatch):
    monkeypatch.setenv("FASTER_BOTO3_NATIVE", "s3")
    import faster_boto3

    faster_boto3.patch()
    return faster_boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)


def test_returns_native_client(native_s3):
    assert type(native_s3).__name__ == "NativeS3Client"


def test_native_head_and_get(native_s3):
    head = native_s3.head_object(Bucket=BUCKET, Key="hello.txt")
    body = native_s3.get_object(Bucket=BUCKET, Key="hello.txt")["Body"].read()
    assert head["ContentLength"] == len(body) == 12


def test_native_put_and_list(native_s3):
    native_s3.put_object(Bucket=BUCKET, Key="native-put", Body=b"native-data", Metadata={"m": "1"})
    head = native_s3.head_object(Bucket=BUCKET, Key="native-put")
    listing = native_s3.list_objects_v2(Bucket=BUCKET, Prefix="list/")
    assert head["Metadata"]["m"] == "1"
    assert listing["KeyCount"] == 5


def test_native_file_upload_uses_fd_path(native_s3):
    import faster_boto3.native_s3 as native_mod

    calls = []
    http_accel = native_mod._http_accel_module()
    orig = http_accel.request_fd

    def wrapped(*args):
        calls.append(args[3:6])
        return orig(*args)

    http_accel.request_fd = wrapped
    try:
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x" * 2048)
            path = f.name
        try:
            with open(path, "rb") as body:
                native_s3.put_object(Bucket=BUCKET, Key="fd-upload", Body=body)
        finally:
            os.unlink(path)
    finally:
        http_accel.request_fd = orig

    assert calls
    assert calls[0][2] == 2048
