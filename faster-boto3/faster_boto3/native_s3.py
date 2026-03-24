"""Native-backed S3 client for the first faster-boto3 migration slice."""

from __future__ import annotations

import base64
import concurrent.futures
import datetime
import hashlib
import importlib
import io
import logging
import math
import os
import urllib.parse
import xml.etree.ElementTree as ET
import zlib

from botocore.exceptions import ClientError
from botocore.response import StreamingBody

logger = logging.getLogger("faster_boto3.native_s3")
_MIN_MULTIPART_CHUNK = 5 * 1024 * 1024
_UNSIGNED_PAYLOAD = "UNSIGNED-PAYLOAD"
_S3_XMLNS = "http://s3.amazonaws.com/doc/2006-03-01/"


def _http_accel_module():
    return importlib.import_module("faster_boto3._http_accel")


def _sigv4_accel_module():
    return importlib.import_module("faster_boto3._sigv4_accel")


def _parser_accel_module():
    return importlib.import_module("faster_boto3._parser_accel")


def _utcnow():
    now = datetime.datetime.now(datetime.UTC)
    return now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")


def _escape_key(key: str) -> str:
    return urllib.parse.quote(key, safe="/-_.~")


def _encode_query(params: dict[str, str | int]) -> str:
    items = []
    for key, value in sorted(params.items()):
        encoded_key = urllib.parse.quote(str(key), safe="-_.~")
        if value == "":
            items.append(encoded_key)
        else:
            encoded_value = urllib.parse.quote(str(value), safe="-_.~")
            items.append(f"{encoded_key}={encoded_value}")
    return "&".join(items)


def _header_value(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _parse_headers(headers_blob: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in headers_blob.split(b"\r\n"):
        if b": " not in line:
            continue
        key, value = line.split(b": ", 1)
        headers[key.decode("utf-8").lower()] = value.decode("utf-8")
    return headers


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _parse_fast_timestamp(value: str):
    year, month, day, hour, minute, second = _parser_accel_module().parse_timestamp(value)
    return datetime.datetime(year, month, day, hour, minute, second, tzinfo=datetime.UTC)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class NativeS3Client:
    def __init__(
        self,
        *,
        fallback,
        endpoint_url: str,
        region_name: str,
        access_key: str,
        secret_key: str,
        session_token: str | None,
        mode: str,
        operation_modes: dict[str, str] | None = None,
    ):
        self._fallback = fallback
        self._endpoint_url = endpoint_url.rstrip("/")
        self._region_name = region_name
        self._access_key = access_key
        self._secret_key = secret_key
        self._session_token = session_token
        self._mode = mode
        self._operation_modes = operation_modes or {}
        self.meta = fallback.meta

    @classmethod
    def from_botocore_client(cls, fallback, *, mode: str, operation_modes: dict[str, str] | None = None):
        creds = fallback._request_signer._credentials.get_frozen_credentials()
        return cls(
            fallback=fallback,
            endpoint_url=fallback.meta.endpoint_url,
            region_name=fallback.meta.region_name,
            access_key=creds.access_key,
            secret_key=creds.secret_key,
            session_token=creds.token,
            mode=mode,
            operation_modes=operation_modes,
        )

    def head_object(self, *, Bucket, Key, **kwargs):
        if kwargs:
            return self._fallback.head_object(Bucket=Bucket, Key=Key, **kwargs)
        def native():
            return self._native_head_object(Bucket=Bucket, Key=Key)
        def fallback():
            return self._fallback.head_object(Bucket=Bucket, Key=Key)
        return self._run_mode("head_object", native, fallback)

    def head_bucket(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.head_bucket(Bucket=Bucket, **kwargs)
        def native():
            return self._native_head_bucket(Bucket=Bucket)
        def fallback():
            return self._fallback.head_bucket(Bucket=Bucket)
        return self._run_mode("head_bucket", native, fallback)

    def get_object(self, *, Bucket, Key, **kwargs):
        if kwargs:
            return self._fallback.get_object(Bucket=Bucket, Key=Key, **kwargs)
        def native():
            return self._native_get_object(Bucket=Bucket, Key=Key)
        def fallback():
            return self._fallback.get_object(Bucket=Bucket, Key=Key)
        return self._run_mode("get_object", native, fallback)

    def put_object(self, *, Bucket, Key, Body=b"", Metadata=None, **kwargs):
        if kwargs:
            return self._fallback.put_object(Bucket=Bucket, Key=Key, Body=Body, Metadata=Metadata, **kwargs)
        def native():
            return self._native_put_object(Bucket=Bucket, Key=Key, Body=Body, Metadata=Metadata)
        def fallback():
            fallback_kwargs = {
                "Bucket": Bucket,
                "Key": Key,
                "Body": Body,
            }
            if Metadata is not None:
                fallback_kwargs["Metadata"] = Metadata
            return self._fallback.put_object(**fallback_kwargs)
        return self._run_mode("put_object", native, fallback)

    def create_bucket(self, *, Bucket, CreateBucketConfiguration=None, **kwargs):
        if kwargs:
            return self._fallback.create_bucket(
                Bucket=Bucket,
                CreateBucketConfiguration=CreateBucketConfiguration,
                **kwargs,
            )
        def native():
            return self._native_create_bucket(Bucket=Bucket, CreateBucketConfiguration=CreateBucketConfiguration)
        def fallback():
            fallback_kwargs = {"Bucket": Bucket}
            if CreateBucketConfiguration is not None:
                fallback_kwargs["CreateBucketConfiguration"] = CreateBucketConfiguration
            return self._fallback.create_bucket(**fallback_kwargs)
        return self._run_mode("create_bucket", native, fallback)

    def delete_bucket(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.delete_bucket(Bucket=Bucket, **kwargs)
        def native():
            return self._native_delete_bucket(Bucket=Bucket)
        def fallback():
            return self._fallback.delete_bucket(Bucket=Bucket)
        return self._run_mode("delete_bucket", native, fallback)

    def list_buckets(self, **kwargs):
        if kwargs:
            return self._fallback.list_buckets(**kwargs)
        def native():
            return self._native_list_buckets()
        def fallback():
            return self._fallback.list_buckets()
        return self._run_mode("list_buckets", native, fallback)

    def get_bucket_location(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.get_bucket_location(Bucket=Bucket, **kwargs)
        def native():
            return self._native_get_bucket_location(Bucket=Bucket)
        def fallback():
            return self._fallback.get_bucket_location(Bucket=Bucket)
        return self._run_mode("get_bucket_location", native, fallback)

    def get_bucket_tagging(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.get_bucket_tagging(Bucket=Bucket, **kwargs)
        def native():
            return self._native_get_bucket_tagging(Bucket=Bucket)
        def fallback():
            return self._fallback.get_bucket_tagging(Bucket=Bucket)
        return self._run_mode("get_bucket_tagging", native, fallback)

    def put_bucket_tagging(self, *, Bucket, Tagging, **kwargs):
        if kwargs:
            return self._fallback.put_bucket_tagging(Bucket=Bucket, Tagging=Tagging, **kwargs)
        def native():
            return self._native_put_bucket_tagging(Bucket=Bucket, Tagging=Tagging)
        def fallback():
            return self._fallback.put_bucket_tagging(Bucket=Bucket, Tagging=Tagging)
        return self._run_mode("put_bucket_tagging", native, fallback)

    def delete_bucket_tagging(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.delete_bucket_tagging(Bucket=Bucket, **kwargs)
        def native():
            return self._native_delete_bucket_tagging(Bucket=Bucket)
        def fallback():
            return self._fallback.delete_bucket_tagging(Bucket=Bucket)
        return self._run_mode("delete_bucket_tagging", native, fallback)

    def get_bucket_versioning(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.get_bucket_versioning(Bucket=Bucket, **kwargs)
        def native():
            return self._native_get_bucket_versioning(Bucket=Bucket)
        def fallback():
            return self._fallback.get_bucket_versioning(Bucket=Bucket)
        return self._run_mode("get_bucket_versioning", native, fallback)

    def put_bucket_versioning(self, *, Bucket, VersioningConfiguration, **kwargs):
        if kwargs:
            return self._fallback.put_bucket_versioning(
                Bucket=Bucket,
                VersioningConfiguration=VersioningConfiguration,
                **kwargs,
            )
        def native():
            return self._native_put_bucket_versioning(Bucket=Bucket, VersioningConfiguration=VersioningConfiguration)
        def fallback():
            return self._fallback.put_bucket_versioning(
                Bucket=Bucket,
                VersioningConfiguration=VersioningConfiguration,
            )
        return self._run_mode("put_bucket_versioning", native, fallback)

    def get_bucket_policy(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.get_bucket_policy(Bucket=Bucket, **kwargs)
        def native():
            return self._native_get_bucket_policy(Bucket=Bucket)
        def fallback():
            return self._fallback.get_bucket_policy(Bucket=Bucket)
        return self._run_mode("get_bucket_policy", native, fallback)

    def put_bucket_policy(self, *, Bucket, Policy, **kwargs):
        if kwargs:
            return self._fallback.put_bucket_policy(Bucket=Bucket, Policy=Policy, **kwargs)
        def native():
            return self._native_put_bucket_policy(Bucket=Bucket, Policy=Policy)
        def fallback():
            return self._fallback.put_bucket_policy(Bucket=Bucket, Policy=Policy)
        return self._run_mode("put_bucket_policy", native, fallback)

    def delete_bucket_policy(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.delete_bucket_policy(Bucket=Bucket, **kwargs)
        def native():
            return self._native_delete_bucket_policy(Bucket=Bucket)
        def fallback():
            return self._fallback.delete_bucket_policy(Bucket=Bucket)
        return self._run_mode("delete_bucket_policy", native, fallback)

    def get_bucket_request_payment(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.get_bucket_request_payment(Bucket=Bucket, **kwargs)
        def native():
            return self._native_get_bucket_request_payment(Bucket=Bucket)
        def fallback():
            return self._fallback.get_bucket_request_payment(Bucket=Bucket)
        return self._run_mode("get_bucket_request_payment", native, fallback)

    def put_bucket_request_payment(self, *, Bucket, RequestPaymentConfiguration, **kwargs):
        if kwargs:
            return self._fallback.put_bucket_request_payment(
                Bucket=Bucket,
                RequestPaymentConfiguration=RequestPaymentConfiguration,
                **kwargs,
            )
        def native():
            return self._native_put_bucket_request_payment(
                Bucket=Bucket,
                RequestPaymentConfiguration=RequestPaymentConfiguration,
            )
        def fallback():
            return self._fallback.put_bucket_request_payment(
                Bucket=Bucket,
                RequestPaymentConfiguration=RequestPaymentConfiguration,
            )
        return self._run_mode("put_bucket_request_payment", native, fallback)

    def get_public_access_block(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.get_public_access_block(Bucket=Bucket, **kwargs)
        def native():
            return self._native_get_public_access_block(Bucket=Bucket)
        def fallback():
            return self._fallback.get_public_access_block(Bucket=Bucket)
        return self._run_mode("get_public_access_block", native, fallback)

    def put_public_access_block(self, *, Bucket, PublicAccessBlockConfiguration, **kwargs):
        if kwargs:
            return self._fallback.put_public_access_block(
                Bucket=Bucket,
                PublicAccessBlockConfiguration=PublicAccessBlockConfiguration,
                **kwargs,
            )
        def native():
            return self._native_put_public_access_block(
                Bucket=Bucket,
                PublicAccessBlockConfiguration=PublicAccessBlockConfiguration,
            )
        def fallback():
            return self._fallback.put_public_access_block(
                Bucket=Bucket,
                PublicAccessBlockConfiguration=PublicAccessBlockConfiguration,
            )
        return self._run_mode("put_public_access_block", native, fallback)

    def delete_public_access_block(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.delete_public_access_block(Bucket=Bucket, **kwargs)
        def native():
            return self._native_delete_public_access_block(Bucket=Bucket)
        def fallback():
            return self._fallback.delete_public_access_block(Bucket=Bucket)
        return self._run_mode("delete_public_access_block", native, fallback)

    def get_bucket_logging(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.get_bucket_logging(Bucket=Bucket, **kwargs)
        def native():
            return self._native_get_bucket_logging(Bucket=Bucket)
        def fallback():
            return self._fallback.get_bucket_logging(Bucket=Bucket)
        return self._run_mode("get_bucket_logging", native, fallback)

    def put_bucket_logging(self, *, Bucket, BucketLoggingStatus, **kwargs):
        if kwargs:
            return self._fallback.put_bucket_logging(
                Bucket=Bucket,
                BucketLoggingStatus=BucketLoggingStatus,
                **kwargs,
            )
        def native():
            return self._native_put_bucket_logging(Bucket=Bucket, BucketLoggingStatus=BucketLoggingStatus)
        def fallback():
            return self._fallback.put_bucket_logging(Bucket=Bucket, BucketLoggingStatus=BucketLoggingStatus)
        return self._run_mode("put_bucket_logging", native, fallback)
    def get_bucket_encryption(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.get_bucket_encryption(Bucket=Bucket, **kwargs)
        def native():
            return self._native_get_bucket_encryption(Bucket=Bucket)
        def fallback():
            return self._fallback.get_bucket_encryption(Bucket=Bucket)
        return self._run_mode("get_bucket_encryption", native, fallback)

    def put_bucket_encryption(self, *, Bucket, ServerSideEncryptionConfiguration, **kwargs):
        if kwargs:
            return self._fallback.put_bucket_encryption(
                Bucket=Bucket,
                ServerSideEncryptionConfiguration=ServerSideEncryptionConfiguration,
                **kwargs,
            )
        def native():
            return self._native_put_bucket_encryption(
                Bucket=Bucket,
                ServerSideEncryptionConfiguration=ServerSideEncryptionConfiguration,
            )
        def fallback():
            return self._fallback.put_bucket_encryption(
                Bucket=Bucket,
                ServerSideEncryptionConfiguration=ServerSideEncryptionConfiguration,
            )
        return self._run_mode("put_bucket_encryption", native, fallback)

    def delete_bucket_encryption(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.delete_bucket_encryption(Bucket=Bucket, **kwargs)
        def native():
            return self._native_delete_bucket_encryption(Bucket=Bucket)
        def fallback():
            return self._fallback.delete_bucket_encryption(Bucket=Bucket)
        return self._run_mode("delete_bucket_encryption", native, fallback)

    def get_bucket_website(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.get_bucket_website(Bucket=Bucket, **kwargs)
        def native():
            return self._native_get_bucket_website(Bucket=Bucket)
        def fallback():
            return self._fallback.get_bucket_website(Bucket=Bucket)
        return self._run_mode("get_bucket_website", native, fallback)

    def put_bucket_website(self, *, Bucket, WebsiteConfiguration, **kwargs):
        if kwargs:
            return self._fallback.put_bucket_website(
                Bucket=Bucket, WebsiteConfiguration=WebsiteConfiguration, **kwargs
            )
        def native():
            return self._native_put_bucket_website(
                Bucket=Bucket, WebsiteConfiguration=WebsiteConfiguration
            )
        def fallback():
            return self._fallback.put_bucket_website(
                Bucket=Bucket, WebsiteConfiguration=WebsiteConfiguration
            )
        return self._run_mode("put_bucket_website", native, fallback)

    def delete_bucket_website(self, *, Bucket, **kwargs):
        if kwargs:
            return self._fallback.delete_bucket_website(Bucket=Bucket, **kwargs)
        def native():
            return self._native_delete_bucket_website(Bucket=Bucket)
        def fallback():
            return self._fallback.delete_bucket_website(Bucket=Bucket)
        return self._run_mode("delete_bucket_website", native, fallback)


    def list_objects(self, *, Bucket, Prefix=None, Marker=None, MaxKeys=None, Delimiter=None, **kwargs):
        if kwargs:
            return self._fallback.list_objects(
                Bucket=Bucket,
                Prefix=Prefix,
                Marker=Marker,
                MaxKeys=MaxKeys,
                Delimiter=Delimiter,
                **kwargs,
            )
        def native():
            return self._native_list_objects(
                Bucket=Bucket,
                Prefix=Prefix,
                Marker=Marker,
                MaxKeys=MaxKeys,
                Delimiter=Delimiter,
            )
        def fallback():
            fallback_kwargs = {"Bucket": Bucket}
            if Prefix is not None:
                fallback_kwargs["Prefix"] = Prefix
            if Marker is not None:
                fallback_kwargs["Marker"] = Marker
            if MaxKeys is not None:
                fallback_kwargs["MaxKeys"] = MaxKeys
            if Delimiter is not None:
                fallback_kwargs["Delimiter"] = Delimiter
            return self._fallback.list_objects(**fallback_kwargs)
        return self._run_mode("list_objects", native, fallback)

    def list_object_versions(self, *, Bucket, Prefix=None, KeyMarker=None, VersionIdMarker=None, MaxKeys=None, Delimiter=None, **kwargs):
        if kwargs:
            return self._fallback.list_object_versions(
                Bucket=Bucket,
                Prefix=Prefix,
                KeyMarker=KeyMarker,
                VersionIdMarker=VersionIdMarker,
                MaxKeys=MaxKeys,
                Delimiter=Delimiter,
                **kwargs,
            )
        def native():
            return self._native_list_object_versions(
                Bucket=Bucket,
                Prefix=Prefix,
                KeyMarker=KeyMarker,
                VersionIdMarker=VersionIdMarker,
                MaxKeys=MaxKeys,
                Delimiter=Delimiter,
            )
        def fallback():
            fallback_kwargs = {"Bucket": Bucket}
            if Prefix is not None:
                fallback_kwargs["Prefix"] = Prefix
            if KeyMarker is not None:
                fallback_kwargs["KeyMarker"] = KeyMarker
            if VersionIdMarker is not None:
                fallback_kwargs["VersionIdMarker"] = VersionIdMarker
            if MaxKeys is not None:
                fallback_kwargs["MaxKeys"] = MaxKeys
            if Delimiter is not None:
                fallback_kwargs["Delimiter"] = Delimiter
            return self._fallback.list_object_versions(**fallback_kwargs)
        return self._run_mode("list_object_versions", native, fallback)

    def get_object_tagging(self, *, Bucket, Key, **kwargs):
        if kwargs:
            return self._fallback.get_object_tagging(Bucket=Bucket, Key=Key, **kwargs)
        def native():
            return self._native_get_object_tagging(Bucket=Bucket, Key=Key)
        def fallback():
            return self._fallback.get_object_tagging(Bucket=Bucket, Key=Key)
        return self._run_mode("get_object_tagging", native, fallback)

    def put_object_tagging(self, *, Bucket, Key, Tagging, **kwargs):
        if kwargs:
            return self._fallback.put_object_tagging(Bucket=Bucket, Key=Key, Tagging=Tagging, **kwargs)
        def native():
            return self._native_put_object_tagging(Bucket=Bucket, Key=Key, Tagging=Tagging)
        def fallback():
            return self._fallback.put_object_tagging(Bucket=Bucket, Key=Key, Tagging=Tagging)
        return self._run_mode("put_object_tagging", native, fallback)

    def delete_object_tagging(self, *, Bucket, Key, **kwargs):
        if kwargs:
            return self._fallback.delete_object_tagging(Bucket=Bucket, Key=Key, **kwargs)
        def native():
            return self._native_delete_object_tagging(Bucket=Bucket, Key=Key)
        def fallback():
            return self._fallback.delete_object_tagging(Bucket=Bucket, Key=Key)
        return self._run_mode("delete_object_tagging", native, fallback)

    def list_objects_v2(self, *, Bucket, Prefix=None, MaxKeys=None, **kwargs):
        if kwargs:
            return self._fallback.list_objects_v2(Bucket=Bucket, Prefix=Prefix, MaxKeys=MaxKeys, **kwargs)
        def native():
            return self._native_list_objects_v2(Bucket=Bucket, Prefix=Prefix, MaxKeys=MaxKeys)
        def fallback():
            fallback_kwargs = {"Bucket": Bucket}
            if Prefix is not None:
                fallback_kwargs["Prefix"] = Prefix
            if MaxKeys is not None:
                fallback_kwargs["MaxKeys"] = MaxKeys
            return self._fallback.list_objects_v2(**fallback_kwargs)
        return self._run_mode("list_objects_v2", native, fallback)

    def delete_object(self, *, Bucket, Key, **kwargs):
        if kwargs:
            return self._fallback.delete_object(Bucket=Bucket, Key=Key, **kwargs)
        def native():
            return self._native_delete_object(Bucket=Bucket, Key=Key)
        def fallback():
            return self._fallback.delete_object(Bucket=Bucket, Key=Key)
        return self._run_mode("delete_object", native, fallback)

    def delete_objects(self, *, Bucket, Delete, **kwargs):
        if kwargs:
            return self._fallback.delete_objects(Bucket=Bucket, Delete=Delete, **kwargs)
        def native():
            return self._native_delete_objects(Bucket=Bucket, Delete=Delete)
        def fallback():
            return self._fallback.delete_objects(Bucket=Bucket, Delete=Delete)
        return self._run_mode("delete_objects", native, fallback)

    def copy_object(self, *, Bucket, Key, CopySource, **kwargs):
        if kwargs:
            return self._fallback.copy_object(Bucket=Bucket, Key=Key, CopySource=CopySource, **kwargs)
        def native():
            return self._native_copy_object(Bucket=Bucket, Key=Key, CopySource=CopySource)
        def fallback():
            return self._fallback.copy_object(Bucket=Bucket, Key=Key, CopySource=CopySource)
        return self._run_mode("copy_object", native, fallback)

    def create_multipart_upload(self, *, Bucket, Key, Metadata=None, **kwargs):
        if kwargs:
            return self._fallback.create_multipart_upload(Bucket=Bucket, Key=Key, Metadata=Metadata, **kwargs)
        def native():
            return self._native_create_multipart_upload(Bucket=Bucket, Key=Key, Metadata=Metadata)
        def fallback():
            fallback_kwargs = {"Bucket": Bucket, "Key": Key}
            if Metadata is not None:
                fallback_kwargs["Metadata"] = Metadata
            return self._fallback.create_multipart_upload(**fallback_kwargs)
        return self._run_mode("create_multipart_upload", native, fallback)

    def upload_part(self, *, Bucket, Key, UploadId, PartNumber, Body=b"", **kwargs):
        if kwargs:
            return self._fallback.upload_part(
                Bucket=Bucket,
                Key=Key,
                UploadId=UploadId,
                PartNumber=PartNumber,
                Body=Body,
                **kwargs,
            )
        def native():
            return self._native_upload_part(Bucket=Bucket, Key=Key, UploadId=UploadId, PartNumber=PartNumber, Body=Body)
        def fallback():
            return self._fallback.upload_part(
                Bucket=Bucket,
                Key=Key,
                UploadId=UploadId,
                PartNumber=PartNumber,
                Body=Body,
            )
        return self._run_mode("upload_part", native, fallback)

    def upload_part_copy(self, *, Bucket, Key, UploadId, PartNumber, CopySource, **kwargs):
        if kwargs:
            return self._fallback.upload_part_copy(
                Bucket=Bucket,
                Key=Key,
                UploadId=UploadId,
                PartNumber=PartNumber,
                CopySource=CopySource,
                **kwargs,
            )
        def native():
            return self._native_upload_part_copy(
                Bucket=Bucket,
                Key=Key,
                UploadId=UploadId,
                PartNumber=PartNumber,
                CopySource=CopySource,
            )
        def fallback():
            return self._fallback.upload_part_copy(
                Bucket=Bucket,
                Key=Key,
                UploadId=UploadId,
                PartNumber=PartNumber,
                CopySource=CopySource,
            )
        return self._run_mode("upload_part_copy", native, fallback)

    def complete_multipart_upload(self, *, Bucket, Key, UploadId, MultipartUpload, **kwargs):
        if kwargs:
            return self._fallback.complete_multipart_upload(
                Bucket=Bucket,
                Key=Key,
                UploadId=UploadId,
                MultipartUpload=MultipartUpload,
                **kwargs,
            )
        def native():
            return self._native_complete_multipart_upload(
                Bucket=Bucket,
                Key=Key,
                UploadId=UploadId,
                Parts=MultipartUpload["Parts"],
            )
        def fallback():
            return self._fallback.complete_multipart_upload(
                Bucket=Bucket,
                Key=Key,
                UploadId=UploadId,
                MultipartUpload=MultipartUpload,
            )
        return self._run_mode("complete_multipart_upload", native, fallback)

    def abort_multipart_upload(self, *, Bucket, Key, UploadId, **kwargs):
        if kwargs:
            return self._fallback.abort_multipart_upload(Bucket=Bucket, Key=Key, UploadId=UploadId, **kwargs)
        def native():
            return self._native_abort_multipart_upload(Bucket=Bucket, Key=Key, UploadId=UploadId)
        def fallback():
            return self._fallback.abort_multipart_upload(Bucket=Bucket, Key=Key, UploadId=UploadId)
        return self._run_mode("abort_multipart_upload", native, fallback)

    def list_parts(self, *, Bucket, Key, UploadId, MaxParts=None, PartNumberMarker=None, **kwargs):
        if kwargs:
            return self._fallback.list_parts(
                Bucket=Bucket,
                Key=Key,
                UploadId=UploadId,
                MaxParts=MaxParts,
                PartNumberMarker=PartNumberMarker,
                **kwargs,
            )
        def native():
            return self._native_list_parts(
                Bucket=Bucket,
                Key=Key,
                UploadId=UploadId,
                MaxParts=MaxParts,
                PartNumberMarker=PartNumberMarker,
            )
        def fallback():
            fallback_kwargs = {
                "Bucket": Bucket,
                "Key": Key,
                "UploadId": UploadId,
            }
            if MaxParts is not None:
                fallback_kwargs["MaxParts"] = MaxParts
            if PartNumberMarker is not None:
                fallback_kwargs["PartNumberMarker"] = PartNumberMarker
            return self._fallback.list_parts(**fallback_kwargs)
        return self._run_mode("list_parts", native, fallback)

    def list_multipart_uploads(
        self,
        *,
        Bucket,
        Prefix=None,
        MaxUploads=None,
        KeyMarker=None,
        UploadIdMarker=None,
        Delimiter=None,
        EncodingType=None,
        **kwargs,
    ):
        if kwargs:
            return self._fallback.list_multipart_uploads(
                Bucket=Bucket,
                Prefix=Prefix,
                MaxUploads=MaxUploads,
                KeyMarker=KeyMarker,
                UploadIdMarker=UploadIdMarker,
                Delimiter=Delimiter,
                EncodingType=EncodingType,
                **kwargs,
            )
        def native():
            return self._native_list_multipart_uploads(
                Bucket=Bucket,
                Prefix=Prefix,
                MaxUploads=MaxUploads,
                KeyMarker=KeyMarker,
                UploadIdMarker=UploadIdMarker,
                Delimiter=Delimiter,
                EncodingType=EncodingType,
            )
        def fallback():
            fallback_kwargs = {"Bucket": Bucket}
            if Prefix is not None:
                fallback_kwargs["Prefix"] = Prefix
            if MaxUploads is not None:
                fallback_kwargs["MaxUploads"] = MaxUploads
            if KeyMarker is not None:
                fallback_kwargs["KeyMarker"] = KeyMarker
            if UploadIdMarker is not None:
                fallback_kwargs["UploadIdMarker"] = UploadIdMarker
            if Delimiter is not None:
                fallback_kwargs["Delimiter"] = Delimiter
            if EncodingType is not None:
                fallback_kwargs["EncodingType"] = EncodingType
            return self._fallback.list_multipart_uploads(**fallback_kwargs)
        return self._run_mode("list_multipart_uploads", native, fallback)

    def _run_mode(self, operation_name: str, native_call, fallback_call):
        mode = self._operation_modes.get(operation_name, self._mode)
        if mode == "native":
            return native_call()
        if mode == "native_shadow":
            native_result = native_exc = None
            fallback_result = fallback_exc = None
            try:
                native_result = native_call()
            except Exception as exc:  # pragma: no cover
                native_exc = exc
            try:
                fallback_result = fallback_call()
            except Exception as exc:
                fallback_exc = exc
            self._log_shadow_result(operation_name, native_result, native_exc, fallback_result, fallback_exc)
            if fallback_exc is not None:
                raise fallback_exc
            return fallback_result
        return fallback_call()

    def _log_shadow_result(self, operation_name, native_result, native_exc, fallback_result, fallback_exc):
        if type(native_exc) is not type(fallback_exc):
            logger.warning("native_shadow mismatch for %s: native_exc=%r fallback_exc=%r", operation_name, native_exc, fallback_exc)
            return
        if native_exc is not None:
            return
        if not _results_equal(operation_name, native_result, fallback_result):
            logger.warning("native_shadow mismatch for %s", operation_name)

    def _native_head_object(self, *, Bucket, Key):
        path, query, url = self._build_url(Bucket, Key)
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        # The Zig HEAD transport path is still unstable on 3.14t against LocalStack.
        # Use a byte-range GET so we stay on the native wire path without crashing.
        headers = self._signed_headers(
            "GET",
            path,
            query,
            payload_hash,
            body=None,
            extra_headers=[("range", "bytes=0-0")],
        )
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("HeadObject", status, parsed_headers, resp_body)
        out = self._metadata_from_headers(parsed_headers)
        content_range = parsed_headers.get("content-range")
        if content_range and "/" in content_range:
            total_size = content_range.rsplit("/", 1)[1]
            if total_size.isdigit():
                out["ContentLength"] = int(total_size)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_head_bucket(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None)
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("HEAD", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("HEAD", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("HeadBucket", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_get_object(self, *, Bucket, Key):
        path, query, url = self._build_url(Bucket, Key)
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("GetObject", status, parsed_headers, resp_body)
        out = self._metadata_from_headers(parsed_headers)
        out["Body"] = StreamingBody(io.BytesIO(resp_body), len(resp_body))
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_put_object(self, *, Bucket, Key, Body=b"", Metadata=None):
        file_request = self._file_request(Body)
        multipart_cfg = self._multipart_config()
        if file_request is not None and self._should_use_multipart(file_request[2], multipart_cfg):
            return self._native_multipart_put_object(
                Bucket=Bucket,
                Key=Key,
                Body=Body,
                Metadata=Metadata,
                fd_request=file_request,
                multipart_cfg=multipart_cfg,
            )
        path, query, url = self._build_url(Bucket, Key)
        body_bytes = b""
        fd_request = file_request
        if fd_request is not None:
            payload_hash = _UNSIGNED_PAYLOAD
        else:
            body_bytes, fd_request = self._prepare_body(Body)
            payload_hash = _sigv4_accel_module().sha256_hex(body_bytes)
        extra_headers = []
        if Metadata:
            for key, value in Metadata.items():
                extra_headers.append((f"x-amz-meta-{key}", str(value)))
        if fd_request is None:
            checksum_crc32 = _base64_crc32(body_bytes)
            extra_headers.extend([("x-amz-checksum-crc32", checksum_crc32), ("x-amz-sdk-checksum-algorithm", "CRC32")])
        headers = self._signed_headers("PUT", path, query, payload_hash, body=body_bytes, extra_headers=extra_headers)
        if fd_request is not None:
            status, resp_headers, resp_body = _http_accel_module().request_fd("PUT", url, headers, *fd_request)
        else:
            status, resp_headers, resp_body = _http_accel_module().request("PUT", url, headers, body_bytes)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("PutObject", status, parsed_headers, resp_body)
        out = {"ResponseMetadata": self._response_metadata(status, parsed_headers)}
        if "etag" in parsed_headers:
            out["ETag"] = parsed_headers["etag"]
        return out

    def _native_create_bucket(self, *, Bucket, CreateBucketConfiguration=None):
        path, query, url = self._build_url(Bucket, None)
        body = b""
        if CreateBucketConfiguration is not None:
            body = self._encode_create_bucket_xml(CreateBucketConfiguration)
        payload_hash = _sigv4_accel_module().sha256_hex(body)
        headers = self._signed_headers("PUT", path, query, payload_hash, body=body)
        status, resp_headers, resp_body = _http_accel_module().request("PUT", url, headers, body)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("CreateBucket", status, parsed_headers, resp_body)
        out = {"ResponseMetadata": self._response_metadata(status, parsed_headers)}
        location = parsed_headers.get("location") or self._parse_text_xml_field(resp_body, "Location")
        if location:
            out["Location"] = location
        return out

    def _native_delete_bucket(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None)
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("DELETE", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("DELETE", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("DeleteBucket", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_list_buckets(self):
        path, query, url = self._build_service_url()
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("ListBuckets", status, parsed_headers, resp_body)
        out = self._parse_list_buckets(resp_body)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_get_bucket_location(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None, params={"location": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("GetBucketLocation", status, parsed_headers, resp_body)
        location = self._parse_text_xml_field(resp_body, "LocationConstraint")
        return {
            "LocationConstraint": location,
            "ResponseMetadata": self._response_metadata(status, parsed_headers),
        }

    def _native_get_bucket_tagging(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None, params={"tagging": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("GetBucketTagging", status, parsed_headers, resp_body)
        out = self._parse_tagging(resp_body)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_put_bucket_tagging(self, *, Bucket, Tagging):
        path, query, url = self._build_url(Bucket, None, params={"tagging": ""})
        body = self._encode_tagging_xml(Tagging)
        payload_hash = _sigv4_accel_module().sha256_hex(body)
        headers = self._signed_headers("PUT", path, query, payload_hash, body=body)
        status, resp_headers, resp_body = _http_accel_module().request("PUT", url, headers, body)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("PutBucketTagging", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_delete_bucket_tagging(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None, params={"tagging": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("DELETE", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("DELETE", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("DeleteBucketTagging", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_get_bucket_versioning(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None, params={"versioning": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("GetBucketVersioning", status, parsed_headers, resp_body)
        out = self._parse_versioning(resp_body)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_put_bucket_versioning(self, *, Bucket, VersioningConfiguration):
        path, query, url = self._build_url(Bucket, None, params={"versioning": ""})
        body = self._encode_versioning_xml(VersioningConfiguration)
        payload_hash = _sigv4_accel_module().sha256_hex(body)
        headers = self._signed_headers("PUT", path, query, payload_hash, body=body)
        status, resp_headers, resp_body = _http_accel_module().request("PUT", url, headers, body)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("PutBucketVersioning", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_get_bucket_policy(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None, params={"policy": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("GetBucketPolicy", status, parsed_headers, resp_body)
        return {
            "Policy": resp_body.decode("utf-8"),
            "ResponseMetadata": self._response_metadata(status, parsed_headers),
        }

    def _native_put_bucket_policy(self, *, Bucket, Policy):
        path, query, url = self._build_url(Bucket, None, params={"policy": ""})
        body = Policy.encode("utf-8") if isinstance(Policy, str) else Policy
        payload_hash = _sigv4_accel_module().sha256_hex(body)
        headers = self._signed_headers("PUT", path, query, payload_hash, body=body)
        status, resp_headers, resp_body = _http_accel_module().request("PUT", url, headers, body)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("PutBucketPolicy", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_delete_bucket_policy(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None, params={"policy": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("DELETE", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("DELETE", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("DeleteBucketPolicy", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_get_bucket_request_payment(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None, params={"requestPayment": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("GetBucketRequestPayment", status, parsed_headers, resp_body)
        out = self._parse_request_payment(resp_body)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_put_bucket_request_payment(self, *, Bucket, RequestPaymentConfiguration):
        path, query, url = self._build_url(Bucket, None, params={"requestPayment": ""})
        body = self._encode_request_payment_xml(RequestPaymentConfiguration)
        payload_hash = _sigv4_accel_module().sha256_hex(body)
        headers = self._signed_headers("PUT", path, query, payload_hash, body=body)
        status, resp_headers, resp_body = _http_accel_module().request("PUT", url, headers, body)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("PutBucketRequestPayment", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_get_public_access_block(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None, params={"publicAccessBlock": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("GetPublicAccessBlock", status, parsed_headers, resp_body)
        out = self._parse_public_access_block(resp_body)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_put_public_access_block(self, *, Bucket, PublicAccessBlockConfiguration):
        path, query, url = self._build_url(Bucket, None, params={"publicAccessBlock": ""})
        body = self._encode_public_access_block_xml(PublicAccessBlockConfiguration)
        payload_hash = _sigv4_accel_module().sha256_hex(body)
        headers = self._signed_headers("PUT", path, query, payload_hash, body=body)
        status, resp_headers, resp_body = _http_accel_module().request("PUT", url, headers, body)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("PutPublicAccessBlock", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_delete_public_access_block(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None, params={"publicAccessBlock": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("DELETE", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("DELETE", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("DeletePublicAccessBlock", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_get_bucket_logging(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None, params={"logging": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("GetBucketLogging", status, parsed_headers, resp_body)
        out = self._parse_bucket_logging(resp_body)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_put_bucket_logging(self, *, Bucket, BucketLoggingStatus):
        path, query, url = self._build_url(Bucket, None, params={"logging": ""})
        body = self._encode_bucket_logging_xml(BucketLoggingStatus)
        payload_hash = _sigv4_accel_module().sha256_hex(body)
        headers = self._signed_headers("PUT", path, query, payload_hash, body=body)
        status, resp_headers, resp_body = _http_accel_module().request("PUT", url, headers, body)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("PutBucketLogging", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}
    def _native_get_bucket_encryption(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None, params={"encryption": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("GetBucketEncryption", status, parsed_headers, resp_body)
        out = self._parse_encryption(resp_body)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_put_bucket_encryption(self, *, Bucket, ServerSideEncryptionConfiguration):
        path, query, url = self._build_url(Bucket, None, params={"encryption": ""})
        body = self._encode_encryption_xml(ServerSideEncryptionConfiguration)
        payload_hash = _sigv4_accel_module().sha256_hex(body)
        headers = self._signed_headers("PUT", path, query, payload_hash, body=body)
        status, resp_headers, resp_body = _http_accel_module().request("PUT", url, headers, body)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("PutBucketEncryption", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_delete_bucket_encryption(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None, params={"encryption": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("DELETE", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("DELETE", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("DeleteBucketEncryption", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_get_bucket_website(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None, params={"website": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("GetBucketWebsite", status, parsed_headers, resp_body)
        out = self._parse_bucket_website(resp_body)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_put_bucket_website(self, *, Bucket, WebsiteConfiguration):
        path, query, url = self._build_url(Bucket, None, params={"website": ""})
        body = self._encode_bucket_website_xml(WebsiteConfiguration)
        payload_hash = _sigv4_accel_module().sha256_hex(body)
        headers = self._signed_headers("PUT", path, query, payload_hash, body=body)
        status, resp_headers, resp_body = _http_accel_module().request("PUT", url, headers, body)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("PutBucketWebsite", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_delete_bucket_website(self, *, Bucket):
        path, query, url = self._build_url(Bucket, None, params={"website": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("DELETE", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("DELETE", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("DeleteBucketWebsite", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}


    def _native_multipart_put_object(self, *, Bucket, Key, Body, Metadata, fd_request, multipart_cfg):
        chunk_size = multipart_cfg["chunk_size"]
        concurrency = multipart_cfg["concurrency"]
        created = self._native_create_multipart_upload(Bucket=Bucket, Key=Key, Metadata=Metadata)
        upload_id = created["UploadId"]
        parts = []
        try:
            total_size = fd_request[2]
            total_parts = math.ceil(total_size / chunk_size)
            for part_start in range(0, total_parts, concurrency):
                batch = []
                for idx in range(part_start, min(part_start + concurrency, total_parts)):
                    part_number = idx + 1
                    offset = fd_request[1] + (idx * chunk_size)
                    length = min(chunk_size, total_size - (idx * chunk_size))
                    batch.append(self._multipart_part_request(Bucket, Key, upload_id, part_number, fd_request[0], offset, length))
                parts.extend(self._execute_multipart_batch(batch))
            parts.sort(key=lambda part: part["PartNumber"])
            return self._native_complete_multipart_upload(
                Bucket=Bucket,
                Key=Key,
                UploadId=upload_id,
                Parts=parts,
            )
        except Exception:
            try:
                self._native_abort_multipart_upload(Bucket=Bucket, Key=Key, UploadId=upload_id)
            except Exception:
                pass
            raise

    def _multipart_part_request(self, bucket: str, key: str, upload_id: str, part_number: int, fd: int, offset: int, length: int):
        path, query, url = self._build_url(
            bucket,
            key,
            params={"partNumber": part_number, "uploadId": upload_id},
        )
        headers = self._signed_headers("PUT", path, query, _UNSIGNED_PAYLOAD, body=None)
        return {
            "part_number": part_number,
            "method": "PUT",
            "url": url,
            "headers": headers,
            "fd_request": (fd, offset, length),
        }

    def _execute_multipart_batch(self, batch):
        if len(batch) == 1:
            item = batch[0]
            status, resp_headers, resp_body = self._send_batch_item(item)
            return [self._parse_upload_part_result(item["part_number"], status, resp_headers, resp_body)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as pool:
            results = [future.result() for future in [pool.submit(self._send_batch_item, item) for item in batch]]
        parts = []
        for item, result in zip(batch, results, strict=True):
            status, resp_headers, resp_body = result
            parts.append(self._parse_upload_part_result(item["part_number"], status, resp_headers, resp_body))
        return parts

    def _send_batch_item(self, item):
        fd_request = item.get("fd_request")
        if fd_request is not None:
            return _http_accel_module().request_fd(
                item["method"],
                item["url"],
                item["headers"],
                *fd_request,
            )
        return _http_accel_module().request(
            item["method"],
            item["url"],
            item["headers"],
            item["body"],
        )

    def _parse_upload_part_result(self, part_number: int, status, resp_headers, resp_body):
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("UploadPart", status, parsed_headers, resp_body)
        etag = parsed_headers.get("etag")
        if not etag:
            raise ClientError(
                {
                    "Error": {"Code": "MissingETag", "Message": "UploadPart response missing ETag"},
                    "ResponseMetadata": self._response_metadata(status, parsed_headers),
                },
                "UploadPart",
            )
        return {"ETag": etag, "PartNumber": part_number}

    def _native_list_objects_v2(self, *, Bucket, Prefix=None, MaxKeys=None):
        params = {"list-type": 2}
        if Prefix is not None:
            params["prefix"] = Prefix
        if MaxKeys is not None:
            params["max-keys"] = MaxKeys
        path, query, url = self._build_url(Bucket, None, params=params)
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("ListObjectsV2", status, parsed_headers, resp_body)
        parsed = self._parse_list_objects(resp_body)
        parsed["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return parsed

    def _native_list_objects(self, *, Bucket, Prefix=None, Marker=None, MaxKeys=None, Delimiter=None):
        params = {}
        if Prefix is not None:
            params["prefix"] = Prefix
        if Marker is not None:
            params["marker"] = Marker
        if MaxKeys is not None:
            params["max-keys"] = MaxKeys
        if Delimiter is not None:
            params["delimiter"] = Delimiter
        path, query, url = self._build_url(Bucket, None, params=params)
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("ListObjects", status, parsed_headers, resp_body)
        parsed = self._parse_list_objects_v1(resp_body)
        parsed["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return parsed

    def _native_list_object_versions(self, *, Bucket, Prefix=None, KeyMarker=None, VersionIdMarker=None, MaxKeys=None, Delimiter=None):
        params = {"versions": ""}
        if Prefix is not None:
            params["prefix"] = Prefix
        if KeyMarker is not None:
            params["key-marker"] = KeyMarker
        if VersionIdMarker is not None:
            params["version-id-marker"] = VersionIdMarker
        if MaxKeys is not None:
            params["max-keys"] = MaxKeys
        if Delimiter is not None:
            params["delimiter"] = Delimiter
        path, query, url = self._build_url(Bucket, None, params=params)
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("ListObjectVersions", status, parsed_headers, resp_body)
        out = self._parse_list_object_versions(resp_body)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_get_object_tagging(self, *, Bucket, Key):
        path, query, url = self._build_url(Bucket, Key, params={"tagging": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("GetObjectTagging", status, parsed_headers, resp_body)
        out = self._parse_tagging(resp_body)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_put_object_tagging(self, *, Bucket, Key, Tagging):
        path, query, url = self._build_url(Bucket, Key, params={"tagging": ""})
        body = self._encode_tagging_xml(Tagging)
        payload_hash = _sigv4_accel_module().sha256_hex(body)
        headers = self._signed_headers("PUT", path, query, payload_hash, body=body)
        status, resp_headers, resp_body = _http_accel_module().request("PUT", url, headers, body)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("PutObjectTagging", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_delete_object_tagging(self, *, Bucket, Key):
        path, query, url = self._build_url(Bucket, Key, params={"tagging": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("DELETE", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("DELETE", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("DeleteObjectTagging", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_delete_object(self, *, Bucket, Key):
        path, query, url = self._build_url(Bucket, Key)
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("DELETE", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("DELETE", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("DeleteObject", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_delete_objects(self, *, Bucket, Delete):
        path, query, url = self._build_url(Bucket, None, params={"delete": ""})
        body = self._encode_delete_objects_xml(Delete)
        payload_hash = _sigv4_accel_module().sha256_hex(body)
        headers = self._signed_headers("POST", path, query, payload_hash, body=body)
        status, resp_headers, resp_body = _http_accel_module().request("POST", url, headers, body)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("DeleteObjects", status, parsed_headers, resp_body)
        out = self._parse_delete_objects(resp_body)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_copy_object(self, *, Bucket, Key, CopySource):
        path, query, url = self._build_url(Bucket, Key)
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        extra_headers = [("x-amz-copy-source", self._format_copy_source(CopySource))]
        headers = self._signed_headers("PUT", path, query, payload_hash, body=None, extra_headers=extra_headers)
        status, resp_headers, resp_body = _http_accel_module().request("PUT", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("CopyObject", status, parsed_headers, resp_body)
        out = self._parse_copy_object(resp_body)
        if "x-amz-server-side-encryption" in parsed_headers:
            out["ServerSideEncryption"] = parsed_headers["x-amz-server-side-encryption"]
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_upload_part(self, *, Bucket, Key, UploadId, PartNumber, Body=b""):
        file_request = self._file_request(Body)
        path, query, url = self._build_url(
            Bucket,
            Key,
            params={"partNumber": PartNumber, "uploadId": UploadId},
        )
        if file_request is not None:
            headers = self._signed_headers("PUT", path, query, _UNSIGNED_PAYLOAD, body=None)
            status, resp_headers, resp_body = _http_accel_module().request_fd("PUT", url, headers, *file_request)
        else:
            body_bytes, _ = self._prepare_body(Body)
            payload_hash = _sigv4_accel_module().sha256_hex(body_bytes)
            headers = self._signed_headers("PUT", path, query, payload_hash, body=body_bytes)
            status, resp_headers, resp_body = _http_accel_module().request("PUT", url, headers, body_bytes)
        return self._parse_upload_part_result(PartNumber, status, resp_headers, resp_body)

    def _native_upload_part_copy(self, *, Bucket, Key, UploadId, PartNumber, CopySource):
        path, query, url = self._build_url(
            Bucket,
            Key,
            params={"partNumber": PartNumber, "uploadId": UploadId},
        )
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers(
            "PUT",
            path,
            query,
            payload_hash,
            body=None,
            extra_headers=[("x-amz-copy-source", self._format_copy_source(CopySource))],
        )
        status, resp_headers, resp_body = _http_accel_module().request("PUT", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("UploadPartCopy", status, parsed_headers, resp_body)
        out = self._parse_upload_part_copy(resp_body)
        if "x-amz-server-side-encryption" in parsed_headers:
            out["ServerSideEncryption"] = parsed_headers["x-amz-server-side-encryption"]
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_create_multipart_upload(self, *, Bucket, Key, Metadata=None):
        path, query, url = self._build_url(Bucket, Key, params={"uploads": ""})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        extra_headers = []
        if Metadata:
            for key, value in Metadata.items():
                extra_headers.append((f"x-amz-meta-{key}", str(value)))
        headers = self._signed_headers("POST", path, query, payload_hash, body=None, extra_headers=extra_headers)
        status, resp_headers, resp_body = _http_accel_module().request("POST", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("CreateMultipartUpload", status, parsed_headers, resp_body)
        upload_id = self._parse_text_xml_field(resp_body, "UploadId")
        if not upload_id:
            raise ClientError(
                {
                    "Error": {"Code": "MissingUploadId", "Message": "CreateMultipartUpload response missing UploadId"},
                    "ResponseMetadata": self._response_metadata(status, parsed_headers),
                },
                "CreateMultipartUpload",
            )
        return {
            "UploadId": upload_id,
            "ResponseMetadata": self._response_metadata(status, parsed_headers),
        }

    def _native_complete_multipart_upload(self, *, Bucket, Key, UploadId, Parts):
        path, query, url = self._build_url(Bucket, Key, params={"uploadId": UploadId})
        body = self._encode_complete_multipart_xml(Parts)
        payload_hash = _sigv4_accel_module().sha256_hex(body)
        headers = self._signed_headers("POST", path, query, payload_hash, body=body)
        status, resp_headers, resp_body = _http_accel_module().request("POST", url, headers, body)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("CompleteMultipartUpload", status, parsed_headers, resp_body)
        out = self._parse_complete_multipart_upload(resp_body)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_abort_multipart_upload(self, *, Bucket, Key, UploadId):
        path, query, url = self._build_url(Bucket, Key, params={"uploadId": UploadId})
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("DELETE", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("DELETE", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("AbortMultipartUpload", status, parsed_headers, resp_body)
        return {"ResponseMetadata": self._response_metadata(status, parsed_headers)}

    def _native_list_parts(self, *, Bucket, Key, UploadId, MaxParts=None, PartNumberMarker=None):
        params = {"uploadId": UploadId}
        if MaxParts is not None:
            params["max-parts"] = MaxParts
        if PartNumberMarker is not None:
            params["part-number-marker"] = PartNumberMarker
        path, query, url = self._build_url(Bucket, Key, params=params)
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("ListParts", status, parsed_headers, resp_body)
        out = self._parse_list_parts(resp_body)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _native_list_multipart_uploads(
        self,
        *,
        Bucket,
        Prefix=None,
        MaxUploads=None,
        KeyMarker=None,
        UploadIdMarker=None,
        Delimiter=None,
        EncodingType=None,
    ):
        params = {"uploads": ""}
        if Prefix is not None:
            params["prefix"] = Prefix
        if MaxUploads is not None:
            params["max-uploads"] = MaxUploads
        if KeyMarker is not None:
            params["key-marker"] = KeyMarker
        if UploadIdMarker is not None:
            params["upload-id-marker"] = UploadIdMarker
        if Delimiter is not None:
            params["delimiter"] = Delimiter
        if EncodingType is not None:
            params["encoding-type"] = EncodingType
        path, query, url = self._build_url(Bucket, None, params=params)
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("GET", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("GET", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("ListMultipartUploads", status, parsed_headers, resp_body)
        out = self._parse_list_multipart_uploads(resp_body)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def _prepare_body(self, body):
        if body is None:
            return b"", None
        if isinstance(body, str):
            body = body.encode("utf-8")
        if isinstance(body, (bytes, bytearray, memoryview)):
            body_bytes = bytes(body)
            return body_bytes, None
        if hasattr(body, "read"):
            if hasattr(body, "fileno") and hasattr(body, "tell"):
                offset = body.tell()
                try:
                    fd = body.fileno()
                except (AttributeError, OSError, io.UnsupportedOperation):
                    fd = None
                else:
                    size = self._remaining_length(body, offset)
                    body_bytes = self._read_all_from_offset(body, offset)
                    body.seek(offset)
                    return body_bytes, (fd, offset, size)
            return body.read(), None
        raise TypeError(f"unsupported Body type: {type(body)!r}")

    def _file_request(self, body):
        if body is None or not hasattr(body, "fileno") or not hasattr(body, "tell"):
            return None
        offset = body.tell()
        try:
            fd = body.fileno()
        except (AttributeError, OSError, io.UnsupportedOperation):
            return None
        size = self._remaining_length(body, offset)
        return fd, offset, size

    def _multipart_config(self):
        threshold = _env_int("FASTER_BOTO3_MULTIPART_THRESHOLD", 0)
        chunk_size = max(_env_int("FASTER_BOTO3_MULTIPART_CHUNKSIZE", 8 * 1024 * 1024), _MIN_MULTIPART_CHUNK)
        concurrency = max(1, _env_int("FASTER_BOTO3_MULTIPART_CONCURRENCY", 4))
        return {
            "threshold": threshold,
            "chunk_size": chunk_size,
            "concurrency": concurrency,
        }

    def _should_use_multipart(self, size: int, multipart_cfg) -> bool:
        threshold = multipart_cfg["threshold"]
        return threshold > 0 and size >= max(threshold, _MIN_MULTIPART_CHUNK)

    def _remaining_length(self, fileobj, offset: int) -> int:
        current = fileobj.tell()
        fileobj.seek(0, os.SEEK_END)
        end = fileobj.tell()
        fileobj.seek(current)
        return max(0, end - offset)

    def _read_all_from_offset(self, fileobj, offset: int) -> bytes:
        current = fileobj.tell()
        fileobj.seek(offset)
        data = fileobj.read()
        fileobj.seek(current)
        return data

    def _build_url(self, bucket: str, key: str | None, params: dict | None = None):
        base_parts = urllib.parse.urlsplit(self._endpoint_url)
        base_path = base_parts.path.rstrip("/")
        path = f"{base_path}/{bucket}"
        if key is not None:
            path = f"{path}/{_escape_key(key)}"
        if not path:
            path = "/"
        query = _encode_query(params or {})
        url = urllib.parse.urlunsplit((base_parts.scheme, base_parts.netloc, path, query, ""))
        return path, query, url

    def _build_service_url(self, params: dict | None = None):
        base_parts = urllib.parse.urlsplit(self._endpoint_url)
        path = base_parts.path.rstrip("/") or "/"
        query = _encode_query(params or {})
        url = urllib.parse.urlunsplit((base_parts.scheme, base_parts.netloc, path, query, ""))
        return path, query, url

    def _format_copy_source(self, copy_source):
        if isinstance(copy_source, str):
            return copy_source.lstrip("/")
        bucket = copy_source["Bucket"]
        key = copy_source["Key"]
        return f"{bucket}/{_escape_key(key)}"

    def _signed_headers(
        self,
        method: str,
        canonical_uri: str,
        canonical_query: str,
        payload_hash: str,
        *,
        body,
        extra_headers=None,
        unsigned_headers=None,
    ):
        amz_date, date_stamp = _utcnow()
        host = urllib.parse.urlsplit(self._endpoint_url).netloc
        header_map = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if self._session_token:
            header_map["x-amz-security-token"] = self._session_token
        for key, value in extra_headers or []:
            header_map[key.lower()] = _header_value(value)
        outbound_headers = dict(header_map)
        for key, value in unsigned_headers or []:
            outbound_headers[key.lower()] = _header_value(value)

        signed_header_names = sorted(header_map)
        canonical_headers = "".join(f"{name}:{' '.join(header_map[name].strip().split())}\n" for name in signed_header_names)
        signed_headers = ";".join(signed_header_names)
        canonical_request = "\n".join(
            [
                method,
                canonical_uri,
                canonical_query,
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        credential_scope = f"{date_stamp}/{self._region_name}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signature = _sigv4_accel_module().sign(
            self._secret_key,
            date_stamp,
            self._region_name,
            "s3",
            string_to_sign,
        )
        header_map["authorization"] = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self._access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )
        outbound_headers["authorization"] = header_map["authorization"]
        return list(outbound_headers.items())

    def _metadata_from_headers(self, headers):
        out = {}
        if "content-length" in headers:
            out["ContentLength"] = int(headers["content-length"])
        if "content-type" in headers:
            out["ContentType"] = headers["content-type"]
        if "etag" in headers:
            out["ETag"] = headers["etag"]
        if "last-modified" in headers:
            out["LastModified"] = _parse_fast_timestamp(headers["last-modified"])
        metadata = {
            key.removeprefix("x-amz-meta-"): value
            for key, value in headers.items()
            if key.startswith("x-amz-meta-")
        }
        if metadata:
            out["Metadata"] = metadata
        else:
            out["Metadata"] = {}
        return out

    def _parse_list_objects(self, body: bytes):
        if not body:
            return {"KeyCount": 0, "Contents": []}
        out = {"Contents": []}
        current = None
        for raw_key, raw_value in _parser_accel_module().parse_xml_tags(body):
            tag = _strip_ns(raw_key.decode("utf-8"))
            value = raw_value.decode("utf-8")
            if tag == "KeyCount":
                out["KeyCount"] = int(value)
                continue
            if tag == "Key":
                if current is not None:
                    out["Contents"].append(current)
                current = {"Key": value}
                continue
            if current is None:
                continue
            if tag == "Size":
                current["Size"] = int(value or "0")
            elif tag == "ETag":
                current["ETag"] = value
            elif tag == "LastModified" and value:
                current["LastModified"] = _parse_fast_timestamp(value)
        if current is not None:
            out["Contents"].append(current)
        out.setdefault("KeyCount", len(out["Contents"]))
        if out["Contents"] or b"<Contents>" not in body:
            return out
        return self._parse_list_objects_v2_xml(body)

    def _parse_list_objects_v2_xml(self, body: bytes):
        root = ET.fromstring(body)
        out = {"Contents": []}
        for child in root:
            tag = _strip_ns(child.tag)
            text = child.text
            if tag in {"Name", "Prefix", "StartAfter", "ContinuationToken", "NextContinuationToken", "Delimiter", "EncodingType"} and text is not None:
                out[tag] = text
            elif tag in {"KeyCount", "MaxKeys"} and text:
                out[tag] = int(text)
            elif tag in {"IsTruncated"} and text is not None:
                out[tag] = text.lower() == "true"
            elif tag == "Contents":
                out["Contents"].append(self._parse_list_object_entry(child))
            elif tag == "CommonPrefixes":
                prefix = self._parse_text_xml_field(ET.tostring(child, encoding="utf-8"), "Prefix")
                if prefix is not None:
                    out.setdefault("CommonPrefixes", []).append({"Prefix": prefix})
        out.setdefault("KeyCount", len(out["Contents"]))
        return out

    def _parse_list_objects_v1(self, body: bytes):
        if not body:
            return {"Contents": []}
        root = ET.fromstring(body)
        out = {"Contents": []}
        for child in root:
            tag = _strip_ns(child.tag)
            text = child.text
            if tag in {"Name", "Prefix", "Marker", "NextMarker", "Delimiter", "EncodingType"} and text is not None:
                out[tag] = text
            elif tag == "MaxKeys" and text:
                out[tag] = int(text)
            elif tag == "IsTruncated" and text is not None:
                out[tag] = text.lower() == "true"
            elif tag == "Contents":
                out["Contents"].append(self._parse_list_object_entry(child))
            elif tag == "CommonPrefixes":
                prefix = self._parse_text_xml_field(ET.tostring(child, encoding="utf-8"), "Prefix")
                if prefix is not None:
                    out.setdefault("CommonPrefixes", []).append({"Prefix": prefix})
        return out

    def _parse_list_object_entry(self, node):
        out = {}
        for child in node:
            tag = _strip_ns(child.tag)
            text = child.text
            if tag == "Size" and text:
                out["Size"] = int(text)
            elif tag == "LastModified" and text:
                out["LastModified"] = _parse_fast_timestamp(text)
            elif tag in {"Owner", "Initiator"}:
                out[tag] = self._parse_person(child)
            elif text is not None:
                out[tag] = text
        return out

    def _parse_list_buckets(self, body: bytes):
        if not body:
            return {"Buckets": []}
        root = ET.fromstring(body)
        out = {"Buckets": []}
        owner = root.find(".//{*}Owner")
        if owner is not None:
            out["Owner"] = self._parse_person(owner)
        buckets = root.find(".//{*}Buckets")
        if buckets is not None:
            for bucket in buckets.findall("{*}Bucket"):
                item = {}
                for child in bucket:
                    tag = _strip_ns(child.tag)
                    if tag == "CreationDate" and child.text:
                        item[tag] = _parse_fast_timestamp(child.text)
                    elif child.text is not None:
                        item[tag] = child.text
                out["Buckets"].append(item)
        return out

    def _parse_tagging(self, body: bytes):
        if not body:
            return {"TagSet": []}
        root = ET.fromstring(body)
        out = {"TagSet": []}
        for tag_node in root.findall(".//{*}Tag"):
            item = {}
            for child in tag_node:
                text = child.text
                if text is not None:
                    item[_strip_ns(child.tag)] = text
            if item:
                out["TagSet"].append(item)
        return out

    def _parse_versioning(self, body: bytes):
        if not body:
            return {}
        root = ET.fromstring(body)
        out = {}
        for child in root:
            text = child.text
            if text is not None:
                out[_strip_ns(child.tag)] = text
        return out

    def _parse_request_payment(self, body: bytes):
        if not body:
            return {}
        root = ET.fromstring(body)
        out = {}
        for child in root:
            text = child.text
            if text is not None:
                out[_strip_ns(child.tag)] = text
        return out

    def _parse_public_access_block(self, body: bytes):
        if not body:
            return {"PublicAccessBlockConfiguration": {}}
        root = ET.fromstring(body)
        out = {}
        for child in root:
            text = child.text
            if text is not None:
                out[_strip_ns(child.tag)] = text.lower() == "true"
        return {"PublicAccessBlockConfiguration": out}

    def _parse_bucket_logging(self, body: bytes):
        if not body:
            return {}
        root = ET.fromstring(body)
        logging_enabled = root.find(".//{*}LoggingEnabled")
        if logging_enabled is None:
            return {}
        out = {}
        for child in logging_enabled:
            tag = _strip_ns(child.tag)
            if tag in {"TargetBucket", "TargetPrefix"} and child.text is not None:
                out[tag] = child.text
            elif tag == "TargetGrants":
                grants = []
                for grant_node in child.findall("{*}Grant"):
                    grant = {}
                    grantee_node = grant_node.find("{*}Grantee")
                    if grantee_node is not None:
                        grantee = {}
                        for g_child in grantee_node:
                            g_tag = _strip_ns(g_child.tag)
                            if g_child.text is not None:
                                grantee[g_tag] = g_child.text
                        xsi_type = grantee_node.get("{http://www.w3.org/2001/XMLSchema-instance}type")
                        if xsi_type:
                            grantee["Type"] = xsi_type.split(":")[-1] if ":" in xsi_type else xsi_type
                        grant["Grantee"] = grantee
                    perm_node = grant_node.find("{*}Permission")
                    if perm_node is not None and perm_node.text is not None:
                        grant["Permission"] = perm_node.text
                    grants.append(grant)
                out["TargetGrants"] = grants
        return {"LoggingEnabled": out}

    def _parse_list_object_versions(self, body: bytes):
        if not body:
            return {"Versions": [], "DeleteMarkers": []}
        root = ET.fromstring(body)
        out = {"Versions": [], "DeleteMarkers": []}
        for child in root:
            tag = _strip_ns(child.tag)
            text = child.text
            if tag in {
                "Name",
                "Prefix",
                "Delimiter",
                "KeyMarker",
                "VersionIdMarker",
                "NextKeyMarker",
                "NextVersionIdMarker",
                "EncodingType",
            } and text is not None:
                out[tag] = text
            elif tag == "MaxKeys" and text:
                out[tag] = int(text)
            elif tag == "IsTruncated" and text is not None:
                out[tag] = text.lower() == "true"
            elif tag == "Version":
                out["Versions"].append(self._parse_version_entry(child))
            elif tag == "DeleteMarker":
                out["DeleteMarkers"].append(self._parse_version_entry(child))
            elif tag == "CommonPrefixes":
                prefix = self._parse_text_xml_field(ET.tostring(child, encoding="utf-8"), "Prefix")
                if prefix is not None:
                    out.setdefault("CommonPrefixes", []).append({"Prefix": prefix})
        return out

    def _parse_version_entry(self, node):
        out = {}
        for child in node:
            tag = _strip_ns(child.tag)
            text = child.text
            if tag in {"Owner", "Initiator"}:
                out[tag] = self._parse_person(child)
            elif tag in {"IsLatest", "IsDeleteMarker"} and text is not None:
                out[tag] = text.lower() == "true"
            elif tag == "Size" and text:
                out[tag] = int(text)
            elif tag == "LastModified" and text:
                out[tag] = _parse_fast_timestamp(text)
            elif text is not None:
                out[tag] = text
        return out

    def _parse_copy_object(self, body: bytes):
        if not body:
            return {}
        root = ET.fromstring(body)
        result = {}
        copy_result = {}
        for child in root:
            tag = _strip_ns(child.tag)
            if tag == "ETag" and child.text is not None:
                copy_result["ETag"] = child.text
            elif tag == "LastModified" and child.text:
                copy_result["LastModified"] = datetime.datetime.fromisoformat(child.text.replace("Z", "+00:00"))
            elif tag.startswith("Checksum") and child.text is not None:
                copy_result[tag] = child.text
        result["CopyObjectResult"] = copy_result
        return result

    def _parse_complete_multipart_upload(self, body: bytes):
        if not body:
            return {}
        root = ET.fromstring(body)
        out = {}
        for child in root:
            tag = _strip_ns(child.tag)
            if tag == "Bucket" and child.text is not None:
                out["Bucket"] = child.text
            elif tag == "Key" and child.text is not None:
                out["Key"] = child.text
            elif tag == "ETag" and child.text is not None:
                out["ETag"] = child.text
            elif tag.startswith("Checksum") and child.text is not None:
                out[tag] = child.text
        return out

    def _parse_upload_part_copy(self, body: bytes):
        if not body:
            return {}
        root = ET.fromstring(body)
        out = {"CopyPartResult": {}}
        for child in root:
            tag = _strip_ns(child.tag)
            if tag == "ETag" and child.text is not None:
                out["CopyPartResult"]["ETag"] = child.text
            elif tag == "LastModified" and child.text:
                out["CopyPartResult"]["LastModified"] = datetime.datetime.fromisoformat(child.text.replace("Z", "+00:00"))
        return out

    def _parse_text_xml_field(self, body: bytes, name: str):
        if not body:
            return None
        root = ET.fromstring(body)
        for child in root.iter():
            if _strip_ns(child.tag) == name:
                return child.text
        return None

    def _encode_complete_multipart_xml(self, parts):
        root = ET.Element("CompleteMultipartUpload")
        for part in parts:
            part_el = ET.SubElement(root, "Part")
            ET.SubElement(part_el, "PartNumber").text = str(part["PartNumber"])
            ET.SubElement(part_el, "ETag").text = part["ETag"]
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _encode_create_bucket_xml(self, config):
        root = ET.Element("CreateBucketConfiguration", xmlns=_S3_XMLNS)
        location = config.get("LocationConstraint")
        if location is not None:
            ET.SubElement(root, "LocationConstraint").text = str(location)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _encode_tagging_xml(self, tagging):
        root = ET.Element("Tagging", xmlns=_S3_XMLNS)
        tag_set = ET.SubElement(root, "TagSet")
        for item in tagging.get("TagSet", []):
            tag = ET.SubElement(tag_set, "Tag")
            ET.SubElement(tag, "Key").text = str(item["Key"])
            ET.SubElement(tag, "Value").text = str(item["Value"])
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _encode_versioning_xml(self, config):
        root = ET.Element("VersioningConfiguration", xmlns=_S3_XMLNS)
        for key in ("Status", "MFADelete"):
            value = config.get(key)
            if value is not None:
                ET.SubElement(root, key).text = str(value)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _encode_request_payment_xml(self, config):
        root = ET.Element("RequestPaymentConfiguration", xmlns=_S3_XMLNS)
        payer = config.get("Payer")
        if payer is not None:
            ET.SubElement(root, "Payer").text = str(payer)
        return ET.tostring(root, encoding="utf-8")

    def _encode_public_access_block_xml(self, config):
        root = ET.Element("PublicAccessBlockConfiguration", xmlns=_S3_XMLNS)
        for key in (
            "BlockPublicAcls",
            "IgnorePublicAcls",
            "BlockPublicPolicy",
            "RestrictPublicBuckets",
        ):
            value = config.get(key)
            if value is not None:
                ET.SubElement(root, key).text = "true" if value else "false"
        return ET.tostring(root, encoding="utf-8")

    def _encode_bucket_logging_xml(self, config):
        root = ET.Element("BucketLoggingStatus", xmlns=_S3_XMLNS)
        logging_enabled = config.get("LoggingEnabled")
        if logging_enabled:
            le_el = ET.SubElement(root, "LoggingEnabled")
            target_bucket = logging_enabled.get("TargetBucket")
            if target_bucket is not None:
                ET.SubElement(le_el, "TargetBucket").text = str(target_bucket)
            target_prefix = logging_enabled.get("TargetPrefix")
            if target_prefix is not None:
                ET.SubElement(le_el, "TargetPrefix").text = str(target_prefix)
            target_grants = logging_enabled.get("TargetGrants")
            if target_grants:
                tg_el = ET.SubElement(le_el, "TargetGrants")
                for grant in target_grants:
                    grant_el = ET.SubElement(tg_el, "Grant")
                    grantee = grant.get("Grantee", {})
                    if grantee:
                        grantee_el = ET.SubElement(grant_el, "Grantee")
                        grantee_type = grantee.get("Type")
                        if grantee_type:
                            grantee_el.set("{http://www.w3.org/2001/XMLSchema-instance}type", grantee_type)
                        for g_key, g_value in grantee.items():
                            if g_key != "Type":
                                ET.SubElement(grantee_el, g_key).text = str(g_value)
                    perm = grant.get("Permission")
                    if perm is not None:
                        ET.SubElement(grant_el, "Permission").text = str(perm)
        return ET.tostring(root, encoding="utf-8")

    def _encode_encryption_xml(self, config):
        root = ET.Element("ServerSideEncryptionConfiguration", xmlns=_S3_XMLNS)
        for rule in config.get("Rules", []):
            rule_el = ET.SubElement(root, "Rule")
            default = rule.get("ApplyServerSideEncryptionByDefault")
            if default is not None:
                default_el = ET.SubElement(rule_el, "ApplyServerSideEncryptionByDefault")
                for key in ("SSEAlgorithm", "KMSMasterKeyID"):
                    value = default.get(key)
                    if value is not None:
                        ET.SubElement(default_el, key).text = str(value)
            bucket_key = rule.get("BucketKeyEnabled")
            if bucket_key is not None:
                ET.SubElement(rule_el, "BucketKeyEnabled").text = "true" if bucket_key else "false"
        return ET.tostring(root, encoding="utf-8")

    def _parse_encryption(self, body: bytes):
        if not body:
            return {"ServerSideEncryptionConfiguration": {"Rules": []}}
        root = ET.fromstring(body)
        rules = []
        for rule_node in root.findall(".//{*}Rule"):
            rule = {}
            default_node = rule_node.find("{*}ApplyServerSideEncryptionByDefault")
            if default_node is not None:
                default = {}
                for child in default_node:
                    tag = _strip_ns(child.tag)
                    if child.text is not None:
                        default[tag] = child.text
                rule["ApplyServerSideEncryptionByDefault"] = default
            bucket_key_node = rule_node.find("{*}BucketKeyEnabled")
            if bucket_key_node is not None and bucket_key_node.text is not None:
                rule["BucketKeyEnabled"] = bucket_key_node.text.lower() == "true"
            rules.append(rule)
        return {"ServerSideEncryptionConfiguration": {"Rules": rules}}


    def _encode_delete_objects_xml(self, delete):
        root = ET.Element("Delete")
        if delete.get("Quiet"):
            ET.SubElement(root, "Quiet").text = "true"
        for obj in delete.get("Objects", []):
            obj_el = ET.SubElement(root, "Object")
            ET.SubElement(obj_el, "Key").text = obj["Key"]
            if obj.get("VersionId") is not None:
                ET.SubElement(obj_el, "VersionId").text = obj["VersionId"]
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _encode_bucket_website_xml(self, config):
        root = ET.Element("WebsiteConfiguration", xmlns=_S3_XMLNS)
        index_doc = config.get("IndexDocument")
        if index_doc:
            idx_el = ET.SubElement(root, "IndexDocument")
            if "Suffix" in index_doc:
                ET.SubElement(idx_el, "Suffix").text = str(index_doc["Suffix"])
        error_doc = config.get("ErrorDocument")
        if error_doc:
            err_el = ET.SubElement(root, "ErrorDocument")
            if "Key" in error_doc:
                ET.SubElement(err_el, "Key").text = str(error_doc["Key"])
        redirect_all = config.get("RedirectAllRequestsTo")
        if redirect_all:
            redir_el = ET.SubElement(root, "RedirectAllRequestsTo")
            if "HostName" in redirect_all:
                ET.SubElement(redir_el, "HostName").text = str(redirect_all["HostName"])
            if "Protocol" in redirect_all:
                ET.SubElement(redir_el, "Protocol").text = str(redirect_all["Protocol"])
        routing_rules = config.get("RoutingRules", [])
        if routing_rules:
            rules_el = ET.SubElement(root, "RoutingRules")
            for rule in routing_rules:
                rule_el = ET.SubElement(rules_el, "RoutingRule")
                condition = rule.get("Condition")
                if condition:
                    cond_el = ET.SubElement(rule_el, "Condition")
                    for k, v in condition.items():
                        ET.SubElement(cond_el, k).text = str(v)
                redirect = rule.get("Redirect")
                if redirect:
                    redir_rule_el = ET.SubElement(rule_el, "Redirect")
                    for k, v in redirect.items():
                        ET.SubElement(redir_rule_el, k).text = str(v)
        return ET.tostring(root, encoding="utf-8")

    def _parse_bucket_website(self, body: bytes):
        if not body:
            return {}
        root = ET.fromstring(body)
        out = {}
        for child in root:
            tag = _strip_ns(child.tag)
            if tag == "IndexDocument":
                out["IndexDocument"] = {_strip_ns(c.tag): c.text for c in child if c.text}
            elif tag == "ErrorDocument":
                out["ErrorDocument"] = {_strip_ns(c.tag): c.text for c in child if c.text}
            elif tag == "RedirectAllRequestsTo":
                out["RedirectAllRequestsTo"] = {_strip_ns(c.tag): c.text for c in child if c.text}
            elif tag == "RoutingRules":
                rules = []
                for rule_node in child:
                    rule = {}
                    for part in rule_node:
                        part_tag = _strip_ns(part.tag)
                        rule[part_tag] = {_strip_ns(c.tag): c.text for c in part if c.text}
                    rules.append(rule)
                out["RoutingRules"] = rules
        return out

    def _parse_delete_objects(self, body: bytes):
        if not body:
            return {"Deleted": []}
        root = ET.fromstring(body)
        out = {"Deleted": []}
        for child in root:
            tag = _strip_ns(child.tag)
            if tag == "Deleted":
                item = {}
                for field in child:
                    field_tag = _strip_ns(field.tag)
                    if field.text is not None:
                        item[field_tag] = field.text
                out["Deleted"].append(item)
            elif tag == "Error":
                item = {}
                for field in child:
                    field_tag = _strip_ns(field.tag)
                    if field.text is not None:
                        item[field_tag] = field.text
                out.setdefault("Errors", []).append(item)
        return out

    def _parse_list_parts(self, body: bytes):
        if not body:
            return {"Parts": []}
        root = ET.fromstring(body)
        out = {"Parts": []}
        for child in root:
            tag = _strip_ns(child.tag)
            text = child.text
            if tag in {"Bucket", "Key", "UploadId", "StorageClass"} and text is not None:
                out[tag] = text
            elif tag in {"PartNumberMarker", "NextPartNumberMarker", "MaxParts"} and text:
                out[tag] = int(text)
            elif tag == "IsTruncated" and text is not None:
                out[tag] = text.lower() == "true"
            elif tag in {"Initiator", "Owner"}:
                out[tag] = self._parse_person(child)
            elif tag == "Part":
                out["Parts"].append(self._parse_list_part(child))
        out.setdefault("IsTruncated", False)
        return out

    def _parse_list_part(self, node):
        out = {}
        for child in node:
            tag = _strip_ns(child.tag)
            text = child.text
            if tag in {"PartNumber", "Size"} and text:
                out[tag] = int(text)
            elif tag == "LastModified" and text:
                out[tag] = _parse_fast_timestamp(text)
            elif text is not None:
                out[tag] = text
        return out

    def _parse_list_multipart_uploads(self, body: bytes):
        if not body:
            return {"Uploads": []}
        root = ET.fromstring(body)
        out = {"Uploads": []}
        for child in root:
            tag = _strip_ns(child.tag)
            text = child.text
            if tag in {
                "Bucket",
                "KeyMarker",
                "UploadIdMarker",
                "NextKeyMarker",
                "Prefix",
                "Delimiter",
                "NextUploadIdMarker",
                "EncodingType",
            } and text is not None:
                out[tag] = text
            elif tag == "MaxUploads" and text:
                out[tag] = int(text)
            elif tag == "IsTruncated" and text is not None:
                out[tag] = text.lower() == "true"
            elif tag == "Upload":
                out["Uploads"].append(self._parse_upload(child))
            elif tag == "CommonPrefixes":
                prefix = self._parse_text_xml_field(ET.tostring(child, encoding="utf-8"), "Prefix")
                if prefix is not None:
                    out.setdefault("CommonPrefixes", []).append({"Prefix": prefix})
        out.setdefault("IsTruncated", False)
        return out

    def _parse_upload(self, node):
        out = {}
        for child in node:
            tag = _strip_ns(child.tag)
            text = child.text
            if tag in {"UploadId", "Key", "StorageClass"} and text is not None:
                out[tag] = text
            elif tag == "Initiated" and text:
                out[tag] = _parse_fast_timestamp(text)
            elif tag in {"Owner", "Initiator"}:
                out[tag] = self._parse_person(child)
        return out

    def _parse_person(self, node):
        out = {}
        for child in node:
            if child.text is not None:
                out[_strip_ns(child.tag)] = child.text
        return out

    def _response_metadata(self, status, headers):
        return {
            "HTTPStatusCode": status,
            "HTTPHeaders": headers,
            "RequestId": headers.get("x-amz-request-id", ""),
        }

    def _raise_for_error(self, operation_name, status, headers, body: bytes):
        if status < 300:
            return
        error = {"Code": str(status), "Message": body.decode("utf-8", "replace")}
        if body:
            try:
                root = ET.fromstring(body)
            except ET.ParseError:
                pass
            else:
                for child in root:
                    tag = _strip_ns(child.tag)
                    if tag == "Code" and child.text:
                        error["Code"] = child.text
                    elif child.text is not None:
                        error[tag] = child.text
        raise ClientError(
            {
                "Error": error,
                "ResponseMetadata": self._response_metadata(status, headers),
            },
            operation_name,
        )

    def __getattr__(self, name):
        return getattr(self._fallback, name)


def _base64_crc32(data: bytes) -> str:
    crc = zlib.crc32(data) & 0xFFFFFFFF
    return _base64_crc32_int(crc)


def _base64_crc32_int(crc: int) -> str:
    return base64.b64encode((crc & 0xFFFFFFFF).to_bytes(4, "big")).decode("ascii")


def _results_equal(operation_name: str, native_result, fallback_result) -> bool:
    if operation_name == "get_object":
        native_body = native_result["Body"].read()
        fallback_body = fallback_result["Body"].read()
        return (
            native_body == fallback_body
            and native_result.get("ContentLength") == fallback_result.get("ContentLength")
            and native_result.get("ETag") == fallback_result.get("ETag")
        )
    if operation_name == "list_objects_v2":
        native_keys = [item.get("Key") for item in native_result.get("Contents", [])]
        fallback_keys = [item.get("Key") for item in fallback_result.get("Contents", [])]
        return native_keys == fallback_keys and native_result.get("KeyCount") == fallback_result.get("KeyCount")
    if operation_name == "list_objects":
        native_keys = [item.get("Key") for item in native_result.get("Contents", [])]
        fallback_keys = [item.get("Key") for item in fallback_result.get("Contents", [])]
        return native_keys == fallback_keys
    if operation_name == "list_buckets":
        native_buckets = [item.get("Name") for item in native_result.get("Buckets", [])]
        fallback_buckets = [item.get("Name") for item in fallback_result.get("Buckets", [])]
        return native_buckets == fallback_buckets
    if operation_name == "list_object_versions":
        native_versions = [(item.get("Key"), item.get("VersionId")) for item in native_result.get("Versions", [])]
        fallback_versions = [(item.get("Key"), item.get("VersionId")) for item in fallback_result.get("Versions", [])]
        return native_versions == fallback_versions
    if operation_name in {"get_bucket_tagging", "get_object_tagging"}:
        return native_result.get("TagSet") == fallback_result.get("TagSet")
    if operation_name == "get_bucket_location":
        return native_result.get("LocationConstraint") == fallback_result.get("LocationConstraint")
    if operation_name == "get_bucket_versioning":
        return native_result.get("Status") == fallback_result.get("Status")
    if operation_name == "get_bucket_encryption":
        return native_result.get("ServerSideEncryptionConfiguration") == fallback_result.get("ServerSideEncryptionConfiguration")
    if operation_name == "get_bucket_logging":
        return native_result.get("LoggingEnabled") == fallback_result.get("LoggingEnabled")
    if operation_name == "delete_objects":
        native_deleted = [item.get("Key") for item in native_result.get("Deleted", [])]
        fallback_deleted = [item.get("Key") for item in fallback_result.get("Deleted", [])]
        return native_deleted == fallback_deleted
    if operation_name == "list_parts":
        native_parts = [item.get("PartNumber") for item in native_result.get("Parts", [])]
        fallback_parts = [item.get("PartNumber") for item in fallback_result.get("Parts", [])]
        return native_parts == fallback_parts and native_result.get("UploadId") == fallback_result.get("UploadId")
    if operation_name == "list_multipart_uploads":
        native_uploads = [(item.get("Key"), item.get("UploadId")) for item in native_result.get("Uploads", [])]
        fallback_uploads = [(item.get("Key"), item.get("UploadId")) for item in fallback_result.get("Uploads", [])]
        return native_uploads == fallback_uploads
    if operation_name in {
        "head_bucket",
        "head_object",
        "create_bucket",
        "delete_bucket",
        "put_bucket_tagging",
        "delete_bucket_tagging",
        "put_bucket_versioning",
        "put_object_tagging",
        "delete_object_tagging",
        "put_object",
        "delete_object",
        "copy_object",
        "create_multipart_upload",
        "upload_part",
        "upload_part_copy",
        "complete_multipart_upload",
        "abort_multipart_upload",
        "put_bucket_encryption",
        "delete_bucket_encryption",
        "put_bucket_logging",
    }:
        return native_result == fallback_result or native_result.get("ResponseMetadata", {}).get("HTTPStatusCode") == fallback_result.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return True
