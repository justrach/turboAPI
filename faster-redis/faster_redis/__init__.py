"""
faster-redis: Drop-in replacement for redis-py, powered by Zig.

Usage:
    import faster_redis as redis

    r = redis.Redis(host='localhost', port=6379)
    r.set('key', 'value')
    r.get('key')  # b'value'
"""

__version__ = "0.1.0"

# Re-export redis-py's API
import redis as _redis

Redis = _redis.Redis
StrictRedis = _redis.StrictRedis
ConnectionPool = _redis.ConnectionPool
Connection = _redis.Connection
exceptions = _redis.exceptions

# Apply Zig acceleration on import
from ._patch import patch_all as _patch
_patched = _patch()


def patch():
    """Re-apply Zig patches."""
    from ._patch import patch_all
    return patch_all()


def unpatch():
    """Restore vanilla redis-py."""
    from ._patch import unpatch_all
    unpatch_all()
