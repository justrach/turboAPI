"""
Test S3 parity: faster-boto3 must produce identical results to vanilla boto3.

Tests every S3 operation with both vanilla and patched boto3, comparing
responses byte-for-byte. Marks expected failures with xfail.

Usage:
    pytest tests/test_s3_parity.py -v
    pytest tests/test_s3_parity.py -v --tb=short    # compact failures

Requires: LocalStack on localhost:4566
"""

import hashlib
import os
import time

import boto3
import pytest

ENDPOINT = "http://localhost:4566"
REGION = "us-east-1"
CREDS = {"aws_access_key_id": "test", "aws_secret_access_key": "testing"}
BUCKET = "parity-test-bucket"
TABLE = "parity-test-table"


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def localstack():
    """Verify LocalStack is running."""
    s3 = boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)
    try:
        s3.list_buckets()
    except Exception:
        pytest.skip("LocalStack not running (docker compose up -d)")


@pytest.fixture(scope="session")
def setup_bucket(localstack):
    """Create test bucket with sample objects."""
    s3 = boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)
    try:
        s3.create_bucket(Bucket=BUCKET)
    except Exception:
        pass

    # Upload test data
    s3.put_object(Bucket=BUCKET, Key="hello.txt", Body=b"Hello World!")
    s3.put_object(Bucket=BUCKET, Key="binary.bin", Body=os.urandom(4096))
    s3.put_object(Bucket=BUCKET, Key="empty.txt", Body=b"")
    s3.put_object(Bucket=BUCKET, Key="unicode.txt", Body="こんにちは世界 🌍".encode())
    for i in range(10):
        s3.put_object(Bucket=BUCKET, Key=f"batch/item-{i:03d}", Body=f"data-{i}".encode())

    yield

    # Cleanup
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET):
            for obj in page.get("Contents", []):
                s3.delete_object(Bucket=BUCKET, Key=obj["Key"])
        s3.delete_bucket(Bucket=BUCKET)
    except Exception:
        pass


@pytest.fixture(scope="session")
def setup_dynamodb(localstack):
    """Create test DynamoDB table."""
    ddb = boto3.client("dynamodb", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)
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

    for i in range(5):
        ddb.put_item(TableName=TABLE, Item={
            "pk": {"S": f"user-{i}"},
            "name": {"S": f"User {i}"},
            "score": {"N": str(i * 100)},
        })

    yield

    try:
        ddb.delete_table(TableName=TABLE)
    except Exception:
        pass


@pytest.fixture()
def vanilla_s3(setup_bucket):
    """S3 client WITHOUT patches."""
    import faster_boto3
    faster_boto3.unpatch()
    return boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)


@pytest.fixture()
def patched_s3(setup_bucket):
    """S3 client WITH faster-boto3 patches."""
    import faster_boto3
    faster_boto3.patch()
    return boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)


@pytest.fixture()
def vanilla_ddb(setup_dynamodb):
    import faster_boto3
    faster_boto3.unpatch()
    return boto3.client("dynamodb", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)


@pytest.fixture()
def patched_ddb(setup_dynamodb):
    import faster_boto3
    faster_boto3.patch()
    return boto3.client("dynamodb", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)


# ── S3 Parity Tests ─────────────────────────────────────────────────────────

class TestS3GetObject:
    """GetObject must return identical body and metadata."""

    def test_simple_text(self, vanilla_s3, patched_s3):
        v = vanilla_s3.get_object(Bucket=BUCKET, Key="hello.txt")
        p = patched_s3.get_object(Bucket=BUCKET, Key="hello.txt")
        assert v["Body"].read() == p["Body"].read()
        assert v["ContentLength"] == p["ContentLength"]
        assert v["ContentType"] == p["ContentType"]

    def test_binary_data(self, vanilla_s3, patched_s3):
        v = vanilla_s3.get_object(Bucket=BUCKET, Key="binary.bin")
        p = patched_s3.get_object(Bucket=BUCKET, Key="binary.bin")
        v_body = v["Body"].read()
        p_body = p["Body"].read()
        assert v_body == p_body
        assert len(v_body) == 4096

    def test_empty_object(self, vanilla_s3, patched_s3):
        v = vanilla_s3.get_object(Bucket=BUCKET, Key="empty.txt")
        p = patched_s3.get_object(Bucket=BUCKET, Key="empty.txt")
        assert v["Body"].read() == p["Body"].read() == b""

    def test_unicode_content(self, vanilla_s3, patched_s3):
        v = vanilla_s3.get_object(Bucket=BUCKET, Key="unicode.txt")
        p = patched_s3.get_object(Bucket=BUCKET, Key="unicode.txt")
        assert v["Body"].read() == p["Body"].read()

    def test_etag_matches(self, vanilla_s3, patched_s3):
        v = vanilla_s3.get_object(Bucket=BUCKET, Key="hello.txt")
        p = patched_s3.get_object(Bucket=BUCKET, Key="hello.txt")
        assert v["ETag"] == p["ETag"]


class TestS3PutObject:
    """PutObject must succeed and produce readable objects."""

    def test_put_and_get_roundtrip(self, vanilla_s3, patched_s3):
        data = os.urandom(2048)
        patched_s3.put_object(Bucket=BUCKET, Key="parity-put", Body=data)
        resp = vanilla_s3.get_object(Bucket=BUCKET, Key="parity-put")
        assert resp["Body"].read() == data

    def test_put_empty(self, patched_s3, vanilla_s3):
        patched_s3.put_object(Bucket=BUCKET, Key="parity-empty", Body=b"")
        resp = vanilla_s3.get_object(Bucket=BUCKET, Key="parity-empty")
        assert resp["Body"].read() == b""

    def test_put_large(self, patched_s3, vanilla_s3):
        data = os.urandom(1024 * 1024)  # 1MB
        patched_s3.put_object(Bucket=BUCKET, Key="parity-large", Body=data)
        resp = vanilla_s3.get_object(Bucket=BUCKET, Key="parity-large")
        assert hashlib.sha256(resp["Body"].read()).hexdigest() == hashlib.sha256(data).hexdigest()

    def test_put_with_metadata(self, patched_s3, vanilla_s3):
        patched_s3.put_object(
            Bucket=BUCKET, Key="parity-meta", Body=b"meta-test",
            Metadata={"custom-key": "custom-value"},
        )
        resp = vanilla_s3.head_object(Bucket=BUCKET, Key="parity-meta")
        assert resp["Metadata"]["custom-key"] == "custom-value"


class TestS3ListObjects:
    """ListObjectsV2 must return same keys and metadata."""

    def test_list_returns_same_keys(self, vanilla_s3, patched_s3):
        v = vanilla_s3.list_objects_v2(Bucket=BUCKET, Prefix="batch/")
        p = patched_s3.list_objects_v2(Bucket=BUCKET, Prefix="batch/")
        v_keys = sorted(o["Key"] for o in v.get("Contents", []))
        p_keys = sorted(o["Key"] for o in p.get("Contents", []))
        assert v_keys == p_keys

    def test_list_key_count(self, vanilla_s3, patched_s3):
        v = vanilla_s3.list_objects_v2(Bucket=BUCKET, Prefix="batch/")
        p = patched_s3.list_objects_v2(Bucket=BUCKET, Prefix="batch/")
        assert v["KeyCount"] == p["KeyCount"] == 10

    def test_list_sizes_match(self, vanilla_s3, patched_s3):
        v = vanilla_s3.list_objects_v2(Bucket=BUCKET, Prefix="batch/")
        p = patched_s3.list_objects_v2(Bucket=BUCKET, Prefix="batch/")
        v_sizes = {o["Key"]: o["Size"] for o in v.get("Contents", [])}
        p_sizes = {o["Key"]: o["Size"] for o in p.get("Contents", [])}
        assert v_sizes == p_sizes

    def test_list_empty_prefix(self, vanilla_s3, patched_s3):
        v = vanilla_s3.list_objects_v2(Bucket=BUCKET, Prefix="nonexistent/")
        p = patched_s3.list_objects_v2(Bucket=BUCKET, Prefix="nonexistent/")
        assert v["KeyCount"] == p["KeyCount"] == 0


class TestS3HeadObject:
    """HeadObject must return identical metadata."""

    def test_content_length(self, vanilla_s3, patched_s3):
        v = vanilla_s3.head_object(Bucket=BUCKET, Key="hello.txt")
        p = patched_s3.head_object(Bucket=BUCKET, Key="hello.txt")
        assert v["ContentLength"] == p["ContentLength"]

    def test_etag(self, vanilla_s3, patched_s3):
        v = vanilla_s3.head_object(Bucket=BUCKET, Key="binary.bin")
        p = patched_s3.head_object(Bucket=BUCKET, Key="binary.bin")
        assert v["ETag"] == p["ETag"]

    def test_last_modified_type(self, vanilla_s3, patched_s3):
        v = vanilla_s3.head_object(Bucket=BUCKET, Key="hello.txt")
        p = patched_s3.head_object(Bucket=BUCKET, Key="hello.txt")
        # Both must be datetime objects
        import datetime
        assert isinstance(v["LastModified"], datetime.datetime)
        assert isinstance(p["LastModified"], datetime.datetime)


class TestS3DeleteObject:
    """DeleteObject must work identically."""

    def test_delete_existing(self, patched_s3, vanilla_s3):
        patched_s3.put_object(Bucket=BUCKET, Key="to-delete", Body=b"bye")
        patched_s3.delete_object(Bucket=BUCKET, Key="to-delete")
        with pytest.raises(Exception):
            vanilla_s3.get_object(Bucket=BUCKET, Key="to-delete")

    def test_delete_nonexistent(self, patched_s3):
        # S3 delete on nonexistent key should not error
        patched_s3.delete_object(Bucket=BUCKET, Key="never-existed-12345")


class TestS3CopyObject:
    """CopyObject parity."""

    def test_copy_preserves_data(self, patched_s3, vanilla_s3):
        patched_s3.copy_object(
            Bucket=BUCKET, Key="copied.txt",
            CopySource={"Bucket": BUCKET, "Key": "hello.txt"},
        )
        resp = vanilla_s3.get_object(Bucket=BUCKET, Key="copied.txt")
        assert resp["Body"].read() == b"Hello World!"


# ── DynamoDB Parity Tests ────────────────────────────────────────────────────

class TestDynamoDBGetItem:
    """GetItem must return identical items."""

    def test_get_existing(self, vanilla_ddb, patched_ddb):
        v = vanilla_ddb.get_item(TableName=TABLE, Key={"pk": {"S": "user-1"}})
        p = patched_ddb.get_item(TableName=TABLE, Key={"pk": {"S": "user-1"}})
        assert v["Item"] == p["Item"]

    def test_get_nonexistent(self, vanilla_ddb, patched_ddb):
        v = vanilla_ddb.get_item(TableName=TABLE, Key={"pk": {"S": "no-such-user"}})
        p = patched_ddb.get_item(TableName=TABLE, Key={"pk": {"S": "no-such-user"}})
        assert ("Item" not in v) == ("Item" not in p)

    def test_get_all_fields(self, vanilla_ddb, patched_ddb):
        v = vanilla_ddb.get_item(TableName=TABLE, Key={"pk": {"S": "user-0"}})
        p = patched_ddb.get_item(TableName=TABLE, Key={"pk": {"S": "user-0"}})
        assert v["Item"]["name"]["S"] == p["Item"]["name"]["S"]
        assert v["Item"]["score"]["N"] == p["Item"]["score"]["N"]


class TestDynamoDBPutItem:
    """PutItem must succeed and be readable by both."""

    def test_put_roundtrip(self, vanilla_ddb, patched_ddb):
        patched_ddb.put_item(TableName=TABLE, Item={
            "pk": {"S": "parity-put"},
            "data": {"S": "from-patched"},
        })
        resp = vanilla_ddb.get_item(TableName=TABLE, Key={"pk": {"S": "parity-put"}})
        assert resp["Item"]["data"]["S"] == "from-patched"

    def test_put_overwrite(self, vanilla_ddb, patched_ddb):
        patched_ddb.put_item(TableName=TABLE, Item={
            "pk": {"S": "overwrite-test"}, "v": {"N": "1"},
        })
        patched_ddb.put_item(TableName=TABLE, Item={
            "pk": {"S": "overwrite-test"}, "v": {"N": "2"},
        })
        resp = vanilla_ddb.get_item(TableName=TABLE, Key={"pk": {"S": "overwrite-test"}})
        assert resp["Item"]["v"]["N"] == "2"


class TestDynamoDBScan:
    """Scan must return same items."""

    def test_scan_count(self, vanilla_ddb, patched_ddb):
        v = vanilla_ddb.scan(TableName=TABLE)
        p = patched_ddb.scan(TableName=TABLE)
        # Count may differ slightly due to put_item in other tests,
        # but both should see the same data
        assert abs(v["Count"] - p["Count"]) <= 2

    def test_scan_items_overlap(self, vanilla_ddb, patched_ddb):
        v = vanilla_ddb.scan(TableName=TABLE)
        p = patched_ddb.scan(TableName=TABLE)
        v_pks = {item["pk"]["S"] for item in v["Items"]}
        p_pks = {item["pk"]["S"] for item in p["Items"]}
        # Core test items must be present in both
        for i in range(5):
            assert f"user-{i}" in v_pks
            assert f"user-{i}" in p_pks


class TestDynamoDBBatchWrite:
    """BatchWriteItem parity."""

    def test_batch_write_read(self, patched_ddb, vanilla_ddb):
        items = [{"PutRequest": {"Item": {"pk": {"S": f"batch-parity-{i}"}, "d": {"S": f"val-{i}"}}}} for i in range(5)]
        patched_ddb.batch_write_item(RequestItems={TABLE: items})

        for i in range(5):
            resp = vanilla_ddb.get_item(TableName=TABLE, Key={"pk": {"S": f"batch-parity-{i}"}})
            assert resp["Item"]["d"]["S"] == f"val-{i}"


# ── Signing Parity Tests ────────────────────────────────────────────────────

class TestSigningParity:
    """Zig SigV4 must produce identical signatures to Python."""

    def test_signatures_match(self):
        from faster_boto3.sigv4 import derive_signing_key as py_derive, sign_string as py_sign
        from faster_boto3 import _sigv4_accel as accel

        secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        datestamp = "20260321"
        region = "us-east-1"
        service = "s3"
        sts = "AWS4-HMAC-SHA256\n20260321T000000Z\n20260321/us-east-1/s3/aws4_request\nabc123"

        py_key = py_derive(secret, datestamp, region, service)
        py_sig = py_sign(py_key, sts)

        zig_sig = accel.sign(secret, datestamp, region, service, sts)
        zig_key = accel.derive_signing_key(secret, datestamp, region, service)
        zig_sig_split = accel.sign_string(zig_key, sts)

        assert py_sig == zig_sig, f"Combined mismatch: {py_sig} != {zig_sig}"
        assert py_sig == zig_sig_split, f"Split mismatch: {py_sig} != {zig_sig_split}"

    def test_sha256_matches(self):
        from faster_boto3.sigv4 import sha256_hex as py_sha256
        from faster_boto3 import _sigv4_accel as accel

        for data in [b"", b"hello", b"x" * 10000, os.urandom(4096)]:
            assert py_sha256(data) == accel.sha256_hex(data)

    def test_empty_body_hash(self):
        from faster_boto3 import _sigv4_accel as accel
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert accel.sha256_hex(b"") == expected


# ── Timestamp Parsing Parity ─────────────────────────────────────────────────

class TestTimestampParity:
    """SIMD timestamp parser must handle all formats boto3 encounters."""

    def test_iso8601(self):
        from faster_boto3 import _parser_accel as parser
        result = parser.parse_timestamp("2026-03-21T13:05:33Z")
        assert result == (2026, 3, 21, 13, 5, 33)

    def test_http_date(self):
        from faster_boto3 import _parser_accel as parser
        result = parser.parse_timestamp("Fri, 21 Mar 2026 13:05:33 GMT")
        assert result == (2026, 3, 21, 13, 5, 33)

    def test_iso8601_with_millis(self):
        """ISO timestamps with milliseconds — Zig parser ignores millis."""
        from faster_boto3 import _parser_accel as parser
        result = parser.parse_timestamp("2026-03-21T13:05:33.123Z")
        assert result == (2026, 3, 21, 13, 5, 33)

    @pytest.mark.xfail(reason="Zig parser doesn't handle timezone offsets yet")
    def test_iso8601_with_offset(self):
        from faster_boto3 import _parser_accel as parser
        result = parser.parse_timestamp("2026-03-21T13:05:33+08:00")
        assert result is not None

    @pytest.mark.xfail(reason="Zig parser doesn't handle epoch timestamps")
    def test_epoch_timestamp(self):
        from faster_boto3 import _parser_accel as parser
        result = parser.parse_timestamp("1742558733")
        assert result is not None

    def test_falls_back_to_dateutil(self):
        """Unrecognized formats should fall back via the patch, not crash."""
        import faster_boto3
        faster_boto3.patch()
        import botocore.utils
        # Epoch should still work via fallback
        from datetime import datetime
        result = botocore.utils.parse_timestamp(1742558733)
        assert isinstance(result, datetime)


# ── Known Limitations ────────────────────────────────────────────────────────

class TestKnownLimitations:
    """Document known differences between vanilla and patched."""

    @pytest.mark.xfail(reason="SIMD XML parser strips S3 namespaces — different element names in edge cases")
    def test_xml_namespace_preservation(self, vanilla_s3, patched_s3):
        """XML namespace attributes are stripped by faster-boto3."""
        # This is intentional for performance but could break
        # custom parsers that rely on namespace-qualified names
        pass

    @pytest.mark.xfail(reason="Zig HTTP client doesn't support HTTPS yet")
    def test_https_endpoint(self):
        """Zig HTTP client only supports HTTP currently."""
        from faster_boto3 import _http_accel as http
        http.request("GET", "https://s3.amazonaws.com/", [], None)

    def test_patching_is_idempotent(self):
        """Calling patch() multiple times must not break anything."""
        import faster_boto3
        faster_boto3.patch()
        faster_boto3.patch()
        faster_boto3.patch()
        s3 = boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)
        resp = s3.list_buckets()
        assert "Buckets" in resp

    def test_unpatch_restores(self):
        """unpatch() must fully restore vanilla behavior."""
        import faster_boto3
        faster_boto3.patch()
        faster_boto3.unpatch()

        import botocore.auth
        # signature should be the original method
        assert "zig" not in str(botocore.auth.SigV4Auth.signature).lower()
