"""
faster-boto3: Drop-in replacement for boto3, powered by Zig.

Usage:
    # Just swap the import:
    import faster_boto3 as boto3

    s3 = boto3.client('s3')
    s3.put_object(Bucket='my-bucket', Key='file.txt', Body=data)

    # Or keep both:
    import faster_boto3
    s3 = faster_boto3.client('s3')
"""

__version__ = "0.1.0"

import boto3 as _boto3

from ._patch import patch_all as _patch_all
from ._patch import unpatch_all as _unpatch_all
from .session import Session

# ── Apply Zig patches before re-exporting boto3 ─────────────────────────────

_patch_all()


def patch():
    """Re-apply patches (if you called unpatch())."""
    return _patch_all()


def unpatch():
    """Restore vanilla boto3 behavior."""
    _unpatch_all()


# ── Re-export everything from boto3 (drop-in replacement) ───────────────────

session = _boto3.session

_DEFAULT_SESSION = None
DEFAULT_SESSION = None


def _get_default_session():
    global _DEFAULT_SESSION, DEFAULT_SESSION
    if _DEFAULT_SESSION is None:
        _DEFAULT_SESSION = Session()
        DEFAULT_SESSION = _DEFAULT_SESSION
    return _DEFAULT_SESSION


def client(*args, **kwargs):
    return _get_default_session().client(*args, **kwargs)


def resource(*args, **kwargs):
    return _get_default_session().resource(*args, **kwargs)

set_stream_logger = _boto3.set_stream_logger


def setup_default_session(*args, **kwargs):
    global _DEFAULT_SESSION, DEFAULT_SESSION
    _DEFAULT_SESSION = Session(*args, **kwargs)
    DEFAULT_SESSION = _DEFAULT_SESSION
exceptions = _boto3.exceptions
