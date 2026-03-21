"""Auto-patch boto3 on import.

Usage:
    import faster_boto3.auto

That's it. All boto3 calls now use the Zig HTTP transport.
"""
from . import patch as _patch
_patch()
