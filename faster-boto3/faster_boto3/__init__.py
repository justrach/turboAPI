"""
faster-boto3: Drop-in boto3 acceleration layer powered by Zig.

Usage:
    # Monkey-patch boto3 with Zig accelerators
    import faster_boto3
    faster_boto3.patch()

    # Or use directly
    from faster_boto3 import Session
"""

__version__ = "0.1.0"

_patched = False


def patch():
    """Monkey-patch boto3 to use Zig-accelerated internals."""
    global _patched
    if _patched:
        return

    try:
        from . import _sigv4_accel
        _patch_sigv4(_sigv4_accel)
    except ImportError:
        pass  # Zig module not built, fall back to pure Python

    _patched = True


def _patch_sigv4(accel):
    """Replace botocore's SigV4 signing with Zig implementation."""
    try:
        import botocore.auth
        # Store originals
        botocore.auth._original_HmacV1 = botocore.auth.HmacV1Auth
        # Replace with Zig-accelerated versions
        # TODO: implement ZigSigV4Auth
    except ImportError:
        pass


# Re-export boto3's Session for drop-in usage
try:
    from boto3.session import Session
except ImportError:
    Session = None
