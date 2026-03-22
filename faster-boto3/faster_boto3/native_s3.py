"""Native-backed S3 client for the first faster-boto3 migration slice."""

from __future__ import annotations

import base64
import datetime
import email.utils
import hashlib
import importlib
import io
import os
import urllib.parse
import xml.etree.ElementTree as ET
import zlib

from botocore.exceptions import ClientError
from botocore.response import StreamingBody


def _http_accel_module():
    return importlib.import_module("faster_boto3._http_accel")


def _sigv4_accel_module():
    return importlib.import_module("faster_boto3._sigv4_accel")


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
    ):
        self._fallback = fallback
        self._endpoint_url = endpoint_url.rstrip("/")
        self._region_name = region_name
        self._access_key = access_key
        self._secret_key = secret_key
        self._session_token = session_token
        self.meta = fallback.meta

    @classmethod
    def from_botocore_client(cls, fallback):
        creds = fallback._request_signer._credentials.get_frozen_credentials()
        return cls(
            fallback=fallback,
            endpoint_url=fallback.meta.endpoint_url,
            region_name=fallback.meta.region_name,
            access_key=creds.access_key,
            secret_key=creds.secret_key,
            session_token=creds.token,
        )

    def head_object(self, *, Bucket, Key, **kwargs):
        if kwargs:
            return self._fallback.head_object(Bucket=Bucket, Key=Key, **kwargs)
        path, query, url = self._build_url(Bucket, Key)
        payload_hash = _sigv4_accel_module().sha256_hex(b"")
        headers = self._signed_headers("HEAD", path, query, payload_hash, body=None)
        status, resp_headers, resp_body = _http_accel_module().request("HEAD", url, headers, None)
        parsed_headers = _parse_headers(resp_headers)
        self._raise_for_error("HeadObject", status, parsed_headers, resp_body)
        out = self._metadata_from_headers(parsed_headers)
        out["ResponseMetadata"] = self._response_metadata(status, parsed_headers)
        return out

    def get_object(self, *, Bucket, Key, **kwargs):
        if kwargs:
            return self._fallback.get_object(Bucket=Bucket, Key=Key, **kwargs)
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

    def put_object(self, *, Bucket, Key, Body=b"", Metadata=None, **kwargs):
        if kwargs:
            return self._fallback.put_object(Bucket=Bucket, Key=Key, Body=Body, Metadata=Metadata, **kwargs)
        path, query, url = self._build_url(Bucket, Key)
        body_bytes, fd_request = self._prepare_body(Body)
        payload_hash = _sigv4_accel_module().sha256_hex(body_bytes)
        checksum_crc32 = _base64_crc32(body_bytes)
        extra_headers = []
        if Metadata:
            for key, value in Metadata.items():
                extra_headers.append((f"x-amz-meta-{key}", str(value)))
        extra_headers.extend(
            [
                ("x-amz-checksum-crc32", checksum_crc32),
                ("x-amz-sdk-checksum-algorithm", "CRC32"),
            ]
        )
        headers = self._signed_headers(
            "PUT",
            path,
            query,
            payload_hash,
            body=body_bytes,
            extra_headers=extra_headers,
        )

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

    def list_objects_v2(self, *, Bucket, Prefix=None, MaxKeys=None, **kwargs):
        if kwargs:
            return self._fallback.list_objects_v2(Bucket=Bucket, Prefix=Prefix, MaxKeys=MaxKeys, **kwargs)
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
            out["LastModified"] = email.utils.parsedate_to_datetime(headers["last-modified"])
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
        root = ET.fromstring(body)
        out = {"Contents": []}
        for child in root:
            tag = _strip_ns(child.tag)
            if tag == "KeyCount" and child.text is not None:
                out["KeyCount"] = int(child.text)
            elif tag == "Contents":
                item = {}
                for node in child:
                    node_tag = _strip_ns(node.tag)
                    if node_tag == "Key":
                        item["Key"] = node.text or ""
                    elif node_tag == "Size":
                        item["Size"] = int(node.text or "0")
                    elif node_tag == "ETag":
                        item["ETag"] = node.text or ""
                    elif node_tag == "LastModified" and node.text:
                        item["LastModified"] = email.utils.parsedate_to_datetime(node.text) if "," in node.text else datetime.datetime.fromisoformat(node.text.replace("Z", "+00:00"))
                out["Contents"].append(item)
        out.setdefault("KeyCount", len(out["Contents"]))
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
        code = str(status)
        message = body.decode("utf-8", "replace")
        if body:
            try:
                root = ET.fromstring(body)
            except ET.ParseError:
                pass
            else:
                for child in root:
                    tag = _strip_ns(child.tag)
                    if tag == "Code" and child.text:
                        code = child.text
                    elif tag == "Message" and child.text:
                        message = child.text
        raise ClientError(
            {
                "Error": {"Code": code, "Message": message},
                "ResponseMetadata": self._response_metadata(status, headers),
            },
            operation_name,
        )

    def __getattr__(self, name):
        return getattr(self._fallback, name)


def _base64_crc32(data: bytes) -> str:
    crc = zlib.crc32(data) & 0xFFFFFFFF
    return base64.b64encode(crc.to_bytes(4, "big")).decode("ascii")
