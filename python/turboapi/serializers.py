"""Pluggable JSON serializer backends.

Auto-detects orjson > msgspec > stdlib json.
Override with TURBO_JSON_BACKEND=orjson|msgspec|json env var.
"""

import os

_backend = os.environ.get("TURBO_JSON_BACKEND", "auto")


def _detect_backend():
    if _backend != "auto":
        if _backend == "orjson":
            import orjson
            return orjson.dumps, orjson.loads, "orjson"
        elif _backend == "msgspec":
            import msgspec.json
            return msgspec.json.encode, msgspec.json.decode, "msgspec"
        else:
            import json
            return lambda obj: json.dumps(obj).encode(), json.loads, "json"

    try:
        import orjson
        return orjson.dumps, orjson.loads, "orjson"
    except ImportError:
        pass

    try:
        import msgspec.json
        return msgspec.json.encode, msgspec.json.decode, "msgspec"
    except ImportError:
        pass

    import json
    return lambda obj: json.dumps(obj).encode(), json.loads, "json"


json_dumps, json_loads, JSON_BACKEND = _detect_backend()
