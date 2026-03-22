"""
faster-redis: Python Redis client powered by Zig.

Not a wrapper around redis-py. Not hiredis. The entire client —
TCP socket, RESP parsing, command packing, connection pooling —
runs in Zig. Python just provides the API.

Usage:
    from faster_redis import Redis

    r = Redis()
    r.set('key', 'value')
    r.get('key')  # 'value'
    r.mget('k1', 'k2', 'k3')  # ['v1', 'v2', 'v3']

    with r.pipeline() as pipe:
        pipe.set('a', '1')
        pipe.set('b', '2')
        results = pipe.execute()
"""

__version__ = "0.1.0"

from ._parity import ParityScenario, compare_scenario, core_parity_scenarios, run_parity_matrix
from ._client import Redis, Pipeline
from ._shadow import NativeShadowMismatch, ShadowRedis, native_compare, native_shadow
