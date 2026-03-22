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
        items.append(
            (
                urllib.parse.quote(str(key), safe="-_.~"),
                urllib.parse.quote(str(value), safe="-_.~"),
            )
        )
    return "&".join(f"{k}={v}" for k, v in items)


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
        headers = self._signed_headers("HEAD", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("HEAD", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("HeadObject", status, parsed_headers, resp_body)
        out = self._metadata_from_headers(parsed_headers)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

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
        "head_object",
        "put_object",
        "delete_object",
        "copy_object",
        "create_multipart_upload",
        "upload_part",
        "complete_multipart_upload",
        "abort_multipart_upload",
    }:
        return native_result == fallback_result or native_result.get("ResponseMetadata", {}).get("HTTPStatusCode") == fallback_result.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return True
