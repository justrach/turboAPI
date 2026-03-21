"""
Test vanilla boto3 against LocalStack — baseline correctness tests.

These ensure our LocalStack setup works and boto3 behaves as expected
before any faster-boto3 patching. If these fail, the parity tests
are meaningless.

Usage:
    pytest tests/test_boto3_baseline.py -v

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
BUCKET = "boto3-baseline-bucket"
TABLE = "boto3-baseline-table"


@pytest.fixture(scope="session")
def localstack():
    s3 = boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)
    try:
        s3.list_buckets()
    except Exception:
        pytest.skip("LocalStack not running (docker compose up -d)")


@pytest.fixture(scope="session")
def s3(localstack):
    client = boto3.client("s3", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)
    try:
        client.create_bucket(Bucket=BUCKET)
    except Exception:
        pass
    yield client
    # Cleanup
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET):
            for obj in page.get("Contents", []):
                client.delete_object(Bucket=BUCKET, Key=obj["Key"])
        client.delete_bucket(Bucket=BUCKET)
    except Exception:
        pass


@pytest.fixture(scope="session")
def ddb(localstack):
    client = boto3.client("dynamodb", endpoint_url=ENDPOINT, region_name=REGION, **CREDS)
    try:
        client.delete_table(TableName=TABLE)
        client.get_waiter("table_not_exists").wait(TableName=TABLE)
    except Exception:
        pass
    client.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=TABLE)
    yield client
    try:
        client.delete_table(TableName=TABLE)
    except Exception:
        pass


# ── S3 Baseline Tests ───────────────────────────────────────────────────────

class TestS3Baseline:
    def test_put_get_roundtrip(self, s3):
        data = os.urandom(2048)
        s3.put_object(Bucket=BUCKET, Key="baseline-rt", Body=data)
        resp = s3.get_object(Bucket=BUCKET, Key="baseline-rt")
        assert resp["Body"].read() == data

    def test_put_get_empty(self, s3):
        s3.put_object(Bucket=BUCKET, Key="baseline-empty", Body=b"")
        resp = s3.get_object(Bucket=BUCKET, Key="baseline-empty")
        assert resp["Body"].read() == b""

    def test_put_get_large(self, s3):
        data = os.urandom(512 * 1024)
        s3.put_object(Bucket=BUCKET, Key="baseline-large", Body=data)
        resp = s3.get_object(Bucket=BUCKET, Key="baseline-large")
        got = resp["Body"].read()
        assert hashlib.sha256(got).hexdigest() == hashlib.sha256(data).hexdigest()

    def test_put_with_content_type(self, s3):
        s3.put_object(Bucket=BUCKET, Key="baseline-ct", Body=b'{"a":1}', ContentType="application/json")
        resp = s3.head_object(Bucket=BUCKET, Key="baseline-ct")
        assert resp["ContentType"] == "application/json"

    def test_put_with_metadata(self, s3):
        s3.put_object(Bucket=BUCKET, Key="baseline-meta", Body=b"x", Metadata={"foo": "bar"})
        resp = s3.head_object(Bucket=BUCKET, Key="baseline-meta")
        assert resp["Metadata"]["foo"] == "bar"

    def test_head_object(self, s3):
        s3.put_object(Bucket=BUCKET, Key="baseline-head", Body=b"hello")
        resp = s3.head_object(Bucket=BUCKET, Key="baseline-head")
        assert resp["ContentLength"] == 5
        assert "ETag" in resp
        import datetime
        assert isinstance(resp["LastModified"], datetime.datetime)

    def test_head_nonexistent(self, s3):
        from botocore.exceptions import ClientError
        with pytest.raises(ClientError) as exc:
            s3.head_object(Bucket=BUCKET, Key="no-such-key-12345")
        assert exc.value.response["Error"]["Code"] in ("404", "NoSuchKey")

    def test_list_objects(self, s3):
        for i in range(5):
            s3.put_object(Bucket=BUCKET, Key=f"baseline-list/{i}", Body=f"val{i}".encode())
        resp = s3.list_objects_v2(Bucket=BUCKET, Prefix="baseline-list/")
        keys = sorted(o["Key"] for o in resp.get("Contents", []))
        assert keys == [f"baseline-list/{i}" for i in range(5)]
        assert resp["KeyCount"] == 5

    def test_list_objects_empty_prefix(self, s3):
        resp = s3.list_objects_v2(Bucket=BUCKET, Prefix="nonexistent-prefix/")
        assert resp["KeyCount"] == 0

    def test_delete_object(self, s3):
        s3.put_object(Bucket=BUCKET, Key="baseline-del", Body=b"bye")
        s3.delete_object(Bucket=BUCKET, Key="baseline-del")
        from botocore.exceptions import ClientError
        with pytest.raises(ClientError):
            s3.get_object(Bucket=BUCKET, Key="baseline-del")

    def test_delete_nonexistent(self, s3):
        # Should not raise
        s3.delete_object(Bucket=BUCKET, Key="never-existed-xyz")

    def test_copy_object(self, s3):
        s3.put_object(Bucket=BUCKET, Key="baseline-src", Body=b"copy me")
        s3.copy_object(Bucket=BUCKET, Key="baseline-dst", CopySource={"Bucket": BUCKET, "Key": "baseline-src"})
        resp = s3.get_object(Bucket=BUCKET, Key="baseline-dst")
        assert resp["Body"].read() == b"copy me"

    def test_list_buckets(self, s3):
        resp = s3.list_buckets()
        assert "Buckets" in resp
        names = [b["Name"] for b in resp["Buckets"]]
        assert BUCKET in names

    def test_multipart_upload(self, s3):
        """Multipart upload roundtrip."""
        import io
        from boto3.s3.transfer import TransferConfig
        data = os.urandom(6 * 1024 * 1024)  # 6MB
        config = TransferConfig(multipart_threshold=5 * 1024 * 1024, multipart_chunksize=5 * 1024 * 1024)
        s3.upload_fileobj(io.BytesIO(data), BUCKET, "baseline-multipart", Config=config)
        buf = io.BytesIO()
        s3.download_fileobj(BUCKET, "baseline-multipart", buf)
        assert hashlib.sha256(buf.getvalue()).hexdigest() == hashlib.sha256(data).hexdigest()


# ── DynamoDB Baseline Tests ──────────────────────────────────────────────────

class TestDynamoDBBaseline:
    def test_put_get_item(self, ddb):
        ddb.put_item(TableName=TABLE, Item={
            "pk": {"S": "base-1"},
            "name": {"S": "Alice"},
            "score": {"N": "100"},
        })
        resp = ddb.get_item(TableName=TABLE, Key={"pk": {"S": "base-1"}})
        assert resp["Item"]["name"]["S"] == "Alice"
        assert resp["Item"]["score"]["N"] == "100"

    def test_get_nonexistent(self, ddb):
        resp = ddb.get_item(TableName=TABLE, Key={"pk": {"S": "no-such-user"}})
        assert "Item" not in resp

    def test_put_overwrite(self, ddb):
        ddb.put_item(TableName=TABLE, Item={"pk": {"S": "base-ow"}, "v": {"N": "1"}})
        ddb.put_item(TableName=TABLE, Item={"pk": {"S": "base-ow"}, "v": {"N": "2"}})
        resp = ddb.get_item(TableName=TABLE, Key={"pk": {"S": "base-ow"}})
        assert resp["Item"]["v"]["N"] == "2"

    def test_delete_item(self, ddb):
        ddb.put_item(TableName=TABLE, Item={"pk": {"S": "base-del"}, "v": {"S": "x"}})
        ddb.delete_item(TableName=TABLE, Key={"pk": {"S": "base-del"}})
        resp = ddb.get_item(TableName=TABLE, Key={"pk": {"S": "base-del"}})
        assert "Item" not in resp

    def test_scan(self, ddb):
        for i in range(5):
            ddb.put_item(TableName=TABLE, Item={"pk": {"S": f"base-scan-{i}"}, "v": {"N": str(i)}})
        resp = ddb.scan(TableName=TABLE)
        assert resp["Count"] >= 5
        pks = {item["pk"]["S"] for item in resp["Items"]}
        for i in range(5):
            assert f"base-scan-{i}" in pks

    def test_batch_write(self, ddb):
        items = [{"PutRequest": {"Item": {"pk": {"S": f"base-bw-{i}"}, "d": {"S": f"v{i}"}}}} for i in range(10)]
        ddb.batch_write_item(RequestItems={TABLE: items})
        for i in range(10):
            resp = ddb.get_item(TableName=TABLE, Key={"pk": {"S": f"base-bw-{i}"}})
            assert resp["Item"]["d"]["S"] == f"v{i}"

    def test_query_not_supported_without_gsi(self, ddb):
        """Query on hash-only table requires exact key — just verifying it works."""
        # Can't really query without a sort key, but we can do a GetItem
        ddb.put_item(TableName=TABLE, Item={"pk": {"S": "base-q"}, "v": {"S": "test"}})
        resp = ddb.get_item(TableName=TABLE, Key={"pk": {"S": "base-q"}})
        assert resp["Item"]["v"]["S"] == "test"

    def test_update_item(self, ddb):
        ddb.put_item(TableName=TABLE, Item={"pk": {"S": "base-upd"}, "v": {"N": "1"}})
        ddb.update_item(
            TableName=TABLE,
            Key={"pk": {"S": "base-upd"}},
            UpdateExpression="SET v = :val",
            ExpressionAttributeValues={":val": {"N": "42"}},
        )
        resp = ddb.get_item(TableName=TABLE, Key={"pk": {"S": "base-upd"}})
        assert resp["Item"]["v"]["N"] == "42"

    def test_conditional_put(self, ddb):
        from botocore.exceptions import ClientError
        ddb.put_item(TableName=TABLE, Item={"pk": {"S": "base-cond"}, "v": {"S": "first"}})
        with pytest.raises(ClientError):
            ddb.put_item(
                TableName=TABLE,
                Item={"pk": {"S": "base-cond"}, "v": {"S": "second"}},
                ConditionExpression="attribute_not_exists(pk)",
            )
