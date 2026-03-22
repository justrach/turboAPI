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


def test_native_delete_existing_and_missing(native_s3):
    native_s3.put_object(Bucket=BUCKET, Key="delete-me", Body=b"bye")
    resp = native_s3.delete_object(Bucket=BUCKET, Key="delete-me")
    assert resp["ResponseMetadata"]["HTTPStatusCode"] == 204

    resp = native_s3.delete_object(Bucket=BUCKET, Key="never-existed")
    assert resp["ResponseMetadata"]["HTTPStatusCode"] == 204


def test_native_copy_object(native_s3):
    native_s3.put_object(Bucket=BUCKET, Key="copy-src", Body=b"copy-data")
    resp = native_s3.copy_object(
        Bucket=BUCKET,
        Key="copy-dst",
        CopySource={"Bucket": BUCKET, "Key": "copy-src"},
    )
    assert resp["CopyObjectResult"]["ETag"]
    copied = native_s3.get_object(Bucket=BUCKET, Key="copy-dst")["Body"].read()
    assert copied == b"copy-data"


def test_native_missing_key_errors(native_s3):
    import botocore.exceptions

    with pytest.raises(botocore.exceptions.ClientError) as exc:
        native_s3.get_object(Bucket=BUCKET, Key="does-not-exist")
    assert exc.value.response["Error"]["Code"] == "NoSuchKey"
    assert exc.value.response["Error"]["Key"] == "does-not-exist"

    with pytest.raises(botocore.exceptions.ClientError) as exc:
        native_s3.copy_object(
            Bucket=BUCKET,
            Key="copy-missing",
            CopySource={"Bucket": BUCKET, "Key": "does-not-exist"},
        )
    assert exc.value.response["Error"]["Code"] == "NoSuchKey"
    assert exc.value.response["Error"]["Key"] == "does-not-exist"


def test_native_large_get_object(native_s3):
    data = os.urandom(8 * 1024 * 1024)
    native_s3.put_object(Bucket=BUCKET, Key="large-get", Body=data)
    body = native_s3.get_object(Bucket=BUCKET, Key="large-get")["Body"].read()
    assert body == data


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


def test_native_multipart_put_object(setup_bucket, monkeypatch):
    monkeypatch.setenv("FASTER_BOTO3_NATIVE", "s3")
    monkeypatch.setenv("FASTER_BOTO3_MULTIPART_THRESHOLD", str(5 * 1024 * 1024))
    monkeypatch.setenv("FASTER_BOTO3_MULTIPART_CHUNKSIZE", str(5 * 1024 * 1024))
    monkeypatch.setenv("FASTER_BOTO3_MULTIPART_CONCURRENCY", "2")

    import faster_boto3

    faster_boto3.patch()
    s3 = faster_boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)

    data = os.urandom((6 * 1024 * 1024) + 123)
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(data)
        path = f.name
    try:
        with open(path, "rb") as body:
            resp = s3.put_object(Bucket=BUCKET, Key="multipart-native", Body=body)
        assert resp["ResponseMetadata"]["HTTPStatusCode"] == 200
        faster_boto3.unpatch()
        vanilla = boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)
        downloaded = vanilla.get_object(Bucket=BUCKET, Key="multipart-native")["Body"].read()
        assert downloaded == data
    finally:
        os.unlink(path)


def test_native_multipart_put_object_avoids_fallback_control_plane(setup_bucket, monkeypatch):
    monkeypatch.setenv("FASTER_BOTO3_NATIVE", "s3")
    monkeypatch.setenv("FASTER_BOTO3_MULTIPART_THRESHOLD", str(5 * 1024 * 1024))
    monkeypatch.setenv("FASTER_BOTO3_MULTIPART_CHUNKSIZE", str(5 * 1024 * 1024))
    monkeypatch.setenv("FASTER_BOTO3_MULTIPART_CONCURRENCY", "2")

    import faster_boto3

    faster_boto3.patch()
    s3 = faster_boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)

    def fail(*_args, **_kwargs):
        raise AssertionError("fallback multipart control plane should not be used")

    s3._fallback.create_multipart_upload = fail
    s3._fallback.complete_multipart_upload = fail
    s3._fallback.abort_multipart_upload = fail

    data = os.urandom((6 * 1024 * 1024) + 321)
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(data)
        path = f.name
    try:
        with open(path, "rb") as body:
            resp = s3.put_object(Bucket=BUCKET, Key="multipart-native-direct", Body=body)
        assert resp["ResponseMetadata"]["HTTPStatusCode"] == 200
        faster_boto3.unpatch()
        vanilla = boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)
        downloaded = vanilla.get_object(Bucket=BUCKET, Key="multipart-native-direct")["Body"].read()
        assert downloaded == data
    finally:
        os.unlink(path)


def test_operation_override_put_object_only(setup_bucket, monkeypatch):
    monkeypatch.setenv("FASTER_BOTO3_NATIVE", "legacy")
    monkeypatch.setenv("FASTER_BOTO3_NATIVE_S3_OPS", "put_object")

    import faster_boto3
    import faster_boto3.native_s3 as native_mod

    faster_boto3.patch()
    s3 = faster_boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)

    native_calls = []
    fallback_calls = []

    orig_native_put = native_mod.NativeS3Client._native_put_object
    orig_fallback_put = s3._fallback.put_object
    orig_fallback_get = s3._fallback.get_object

    def wrapped_native_put(*args, **kwargs):
        native_calls.append("put")
        return orig_native_put(*args, **kwargs)

    def wrapped_fallback_put(*args, **kwargs):
        fallback_calls.append("put")
        return orig_fallback_put(*args, **kwargs)

    def wrapped_fallback_get(*args, **kwargs):
        fallback_calls.append("get")
        return orig_fallback_get(*args, **kwargs)

    native_mod.NativeS3Client._native_put_object = wrapped_native_put
    s3._fallback.put_object = wrapped_fallback_put
    s3._fallback.get_object = wrapped_fallback_get
    try:
        s3.put_object(Bucket=BUCKET, Key="override-put", Body=b"override")
        assert native_calls == ["put"]
        assert fallback_calls == []

        body = s3.get_object(Bucket=BUCKET, Key="override-put")["Body"].read()
        assert body == b"override"
        assert fallback_calls == ["get"]
    finally:
        native_mod.NativeS3Client._native_put_object = orig_native_put
        s3._fallback.put_object = orig_fallback_put
        s3._fallback.get_object = orig_fallback_get
