"""
faster-boto3: Replace hot botocore internals with Zig.

The current acceleration layer patches:
- HTTP transport via _http_accel
- SigV4 signature derivation via _sigv4_accel
- JSON/timestamp parsing via _parser_accel
"""

import datetime
import io
import logging
import os

logger = logging.getLogger("faster_boto3")

_patched = False
_originals = {}
_active_patches = []


def patch_all():
    """Replace botocore's HTTP transport with Zig."""
    global _patched, _active_patches
    if _patched:
        return list(_active_patches)

    patched = []

    if _patch_http_transport():
        patched.append("zig-http-transport")
    if _patch_sigv4():
        patched.append("zig-sigv4")
    if _patch_parsers():
        patched.append("zig-parsers")
    if _patch_useragent():
        patched.append("UA-cache")

    _active_patches = patched
    _patched = True
    if patched:
        logger.info(f"faster-boto3: patched {', '.join(patched)}")
    return patched


def unpatch_all():
    """Restore original botocore."""
    global _patched, _active_patches
    for key, (obj, attr, original) in _originals.items():
        setattr(obj, attr, original)
    _originals.clear()
    _active_patches = []
    _patched = False


def _save_original(obj, attr):
    key = f"{id(obj)}.{attr}"
    if key not in _originals:
        _originals[key] = (obj, attr, getattr(obj, attr))


# ── Zig HTTP Transport (replaces urllib3 entirely) ───────────────────────────

class _ZigRawResponse:
    """Minimal raw response object that AWSResponse expects."""
    __slots__ = ('_body', 'status')

    def __init__(self, body, status):
        self._body = body
        self.status = status

    def stream(self, amt=1024, decode_content=True):
        if self._body:
            yield self._body
            self._body = None

    def read(self, amt=None):
        data = self._body or b''
        self._body = None
        return data


def _patch_http_transport():
    try:
        import botocore.awsrequest
        import botocore.httpsession

        from faster_boto3 import _http_accel as zig_http
    except ImportError:
        return False

    _save_original(botocore.httpsession.URLLib3Session, 'send')

    def zig_send(self, request):
        """Replace urllib3 with Zig HTTP client.

        The request already has all headers set (including Authorization
        from SigV4 signing). We just need to do the HTTP call.
        """
        try:
            # Convert headers — filter out Content-Length and Transfer-Encoding
            # since Zig's HTTP client manages these from the body
            skip_headers = {'content-length', 'transfer-encoding'}
            headers_list = []
            if request.headers:
                for key, val in request.headers.items():
                    if isinstance(key, bytes):
                        key = key.decode('utf-8')
                    if key.lower() in skip_headers:
                        continue
                    if isinstance(val, bytes):
                        val = val.decode('utf-8')
                    headers_list.append((key, str(val)))

            # Body handling — pass buffer-protocol objects directly to Zig
            # for zero-copy. Only read() file-like objects that don't support
            # the buffer protocol (e.g. BytesIO).
            body = request.body
            status = None
            resp_headers_bytes = None
            resp_body = None

            # Fast path for real files: skip Python read() and let Zig pread().
            if body is not None and hasattr(body, 'fileno') and hasattr(body, 'tell'):
                try:
                    fd = body.fileno()
                    offset = body.tell()
                    length = _content_length_from_request(request, offset)
                except (OSError, io.UnsupportedOperation, ValueError, TypeError, AttributeError):
                    fd = None
                    length = None
                if (
                    fd is not None
                    and length is not None
                    and length > 0
                    and request.method in {'PUT', 'POST'}
                    and hasattr(zig_http, 'request_fd')
                ):
                    status, resp_headers_bytes, resp_body = zig_http.request_fd(
                        request.method,
                        request.url,
                        headers_list,
                        fd,
                        offset,
                        length,
                    )

            if status is None:
                if body is not None:
                    if isinstance(body, str):
                        body = body.encode('utf-8')
                    elif hasattr(body, 'read') and not isinstance(body, (bytes, bytearray, memoryview)):
                        pos = body.tell() if hasattr(body, 'tell') else 0
                        body = body.read()
                        if hasattr(request.body, 'seek'):
                            request.body.seek(pos)
                status, resp_headers_bytes, resp_body = zig_http.request(
                    request.method,
                    request.url,
                    headers_list,
                    body,
                )

            # Parse response headers from "Key: Value\r\n" format
            resp_headers = {}
            if resp_headers_bytes:
                for line in resp_headers_bytes.split(b'\r\n'):
                    if b': ' in line:
                        k, v = line.split(b': ', 1)
                        resp_headers[k.decode('utf-8')] = v.decode('utf-8')

            # Build AWSResponse
            raw = _ZigRawResponse(resp_body, status)
            http_response = botocore.awsrequest.AWSResponse(
                request.url,
                status,
                resp_headers,
                raw,
            )

            if not request.stream_output:
                _ = http_response.content

            return http_response

        except Exception as e:
            # Fall back to urllib3 for HTTPS or errors
            from botocore.exceptions import HTTPClientError
            raise HTTPClientError(error=e)

    botocore.httpsession.URLLib3Session.send = zig_send
    return True


def _content_length_from_request(request, offset):
    headers = request.headers or {}
    content_length = headers.get('Content-Length') or headers.get('content-length')
    if content_length is not None:
        return int(content_length)

    body = request.body
    if body is None or not hasattr(body, 'seek'):
        return None

    current = body.tell()
    body.seek(0, os.SEEK_END)
    end = body.tell()
    body.seek(current)
    return max(0, end - offset)


def _patch_sigv4():
    try:
        import botocore.auth

        from faster_boto3 import _sigv4_accel as sigv4_accel
    except ImportError:
        return False

    _save_original(botocore.auth.SigV4Auth, 'signature')

    def zig_signature(self, string_to_sign, request):
        return sigv4_accel.sign(
            self.credentials.secret_key,
            request.context["timestamp"][0:8],
            self._region_name,
            self._service_name,
            string_to_sign,
        )

    botocore.auth.SigV4Auth.signature = zig_signature
    return True


def _fast_parse_timestamp(parser_accel, value):
    if isinstance(value, datetime.datetime):
        return value
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        numeric_value = None
    if numeric_value is not None:
        return datetime.datetime.fromtimestamp(numeric_value, tz=datetime.UTC)

    year, month, day, hour, minute, second = parser_accel.parse_timestamp(str(value))
    return datetime.datetime(year, month, day, hour, minute, second, tzinfo=datetime.UTC)


def _patch_parsers():
    try:
        import botocore.parsers
        import botocore.utils

        from faster_boto3 import _parser_accel as parser_accel
    except ImportError:
        return False

    patched = False

    _save_original(botocore.utils, 'parse_timestamp')
    _save_original(botocore.parsers, 'DEFAULT_TIMESTAMP_PARSER')

    def zig_parse_timestamp(value):
        return _fast_parse_timestamp(parser_accel, value)

    botocore.utils.parse_timestamp = zig_parse_timestamp
    botocore.parsers.DEFAULT_TIMESTAMP_PARSER = zig_parse_timestamp
    patched = True

    _save_original(botocore.parsers.BaseJSONParser, '_parse_body_as_json')
    original_parse_body_as_json = botocore.parsers.BaseJSONParser._parse_body_as_json

    def zig_parse_body_as_json(self, body_contents):
        if not body_contents:
            return {}
        try:
            return parser_accel.parse_json(body_contents)
        except Exception:
            return original_parse_body_as_json(self, body_contents)

    botocore.parsers.BaseJSONParser._parse_body_as_json = zig_parse_body_as_json
    return patched


# ── User-Agent Caching (6% of boto3 time) ────────────────────────────────────

def _patch_useragent():
    try:
        import botocore.useragent
    except ImportError:
        return False

    _save_original(botocore.useragent.UserAgentString, 'to_string')
    original_to_string = botocore.useragent.UserAgentString.to_string

    def cached_to_string(self):
        cache_attr = '_faster_boto3_ua_cache'
        cached = getattr(self, cache_attr, None)
        if cached is not None:
            return cached
        result = original_to_string(self)
        try:
            object.__setattr__(self, cache_attr, result)
        except (AttributeError, TypeError):
            pass
        return result

    botocore.useragent.UserAgentString.to_string = cached_to_string
    return True
