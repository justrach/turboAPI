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

# ── Apply Zig patches before re-exporting boto3 ─────────────────────────────

from ._patch import patch_all as _patch_all, unpatch_all as _unpatch_all

_patch_all()


def patch():
    """Re-apply patches (if you called unpatch())."""
    return _patch_all()


def unpatch():
    """Restore vanilla boto3 behavior."""
    _unpatch_all()


# ── Re-export everything from boto3 (drop-in replacement) ───────────────────

import boto3 as _boto3

Session = _boto3.Session
client = _boto3.client
resource = _boto3.resource
session = _boto3.session

set_stream_logger = _boto3.set_stream_logger
setup_default_session = _boto3.setup_default_session

DEFAULT_SESSION = _boto3.DEFAULT_SESSION
exceptions = _boto3.exceptions
