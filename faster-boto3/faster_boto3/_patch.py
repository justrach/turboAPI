"""
faster-boto3: Replace botocore's HTTP transport with Zig.

Instead of monkey-patching individual functions (signing, timestamps, etc.),
we replace URLLib3Session.send() entirely. This eliminates:
- urllib3 connection pooling overhead
- Python socket handling
- Header dict construction
- URL parsing per request

The Zig HTTP client does SigV4-signed request → response in native code
with persistent connection pooling (nanobrew pattern).
"""

import io
import logging

logger = logging.getLogger("faster_boto3")

_patched = False
_originals = {}


def patch_all():
    """Replace botocore's HTTP transport with Zig."""
    global _patched
    if _patched:
        return _patched

    patched = []

    if _patch_http_transport():
        patched.append("zig-http-transport")
    if _patch_useragent():
        patched.append("UA-cache")

    _patched = True
    if patched:
        logger.info(f"faster-boto3: patched {', '.join(patched)}")
    return patched


def unpatch_all():
    """Restore original botocore."""
    global _patched
    for key, (obj, attr, original) in _originals.items():
        setattr(obj, attr, original)
    _originals.clear()
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
        from faster_boto3 import _http_accel as zig_http
        import botocore.httpsession
        import botocore.awsrequest
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

            # Body handling — botocore sends bytes, str, BytesIO, or None
            body = request.body
            if body is not None:
                if hasattr(body, 'read'):
                    pos = body.tell() if hasattr(body, 'tell') else 0
                    body = body.read()
                    if hasattr(request.body, 'seek'):
                        request.body.seek(pos)
                elif isinstance(body, str):
                    body = body.encode('utf-8')
            # Single Zig call: HTTP request with connection pooling
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
                http_response.content  # exhaust body

            return http_response

        except Exception as e:
            # Fall back to urllib3 for HTTPS or errors
            from botocore.exceptions import HTTPClientError
            raise HTTPClientError(error=e)

    botocore.httpsession.URLLib3Session.send = zig_send
    return True


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
