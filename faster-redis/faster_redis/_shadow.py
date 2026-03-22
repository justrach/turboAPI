"""Shadow-mode adapter: redis-py is primary, Zig-native client is mirrored."""

from redis import Redis as RedisPy

from ._client import Redis as NativeRedis


_MISSING = object()


def _normalize(value):
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize(item) for item in value)
    if isinstance(value, dict):
        return {key: _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, set):
        return sorted(_normalize(item) for item in value)
    return value


def _capture(outcome):
    try:
        return {"result": outcome(), "error": None}
    except Exception as exc:  # pragma: no cover - behavior is asserted by caller
        return {"result": _MISSING, "error": exc}


class NativeShadowMismatch(AssertionError):
    """Raised when strict shadow mode detects a mismatch."""


def _build_clients(
    host,
    port,
    db,
    password,
    decode_responses,
    shadow_host,
    shadow_port,
    shadow_db,
    shadow_password,
    allow_same_target,
):
    shadow_host = host if shadow_host is None else shadow_host
    shadow_port = port if shadow_port is None else shadow_port
    shadow_db = db if shadow_db is None else shadow_db
    shadow_password = password if shadow_password is None else shadow_password

    same_target = (
        host == shadow_host
        and port == shadow_port
        and db == shadow_db
        and password == shadow_password
    )
    if same_target and not allow_same_target:
        raise ValueError(
            "native shadowing requires a distinct shadow target by default; "
            "set shadow_db/shadow_host/shadow_port or allow_same_target=True"
        )

    primary = RedisPy(
        host=host,
        port=port,
        db=db,
        password=password,
        decode_responses=decode_responses,
    )
    shadow = NativeRedis(
        host=shadow_host,
        port=shadow_port,
        db=shadow_db,
        password=shadow_password,
        decode_responses=decode_responses,
    )
    return primary, shadow


class ShadowRedis:
    """Return redis-py results while replaying the same calls to the native client."""

    def __init__(
        self,
        host="127.0.0.1",
        port=6379,
        db=0,
        password=None,
        decode_responses=True,
        *,
        shadow_host=None,
        shadow_port=None,
        shadow_db=None,
        shadow_password=None,
        allow_same_target=False,
        on_mismatch=None,
        strict=False,
    ):
        self._primary, self._shadow = _build_clients(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=decode_responses,
            shadow_host=shadow_host,
            shadow_port=shadow_port,
            shadow_db=shadow_db,
            shadow_password=shadow_password,
            allow_same_target=allow_same_target,
        )
        self._on_mismatch = on_mismatch
        self._strict = strict

    def close(self):
        self._primary.close()
        self._shadow.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def pipeline(self, transaction=False):
        return ShadowPipeline(self, transaction=transaction)

    def execute_command(self, *args, **kwargs):
        return self._invoke("execute_command", *args, **kwargs)

    def _invoke(self, name, *args, **kwargs):
        primary_call = lambda: getattr(self._primary, name)(*args, **kwargs)
        shadow_call = lambda: getattr(self._shadow, name)(*args, **kwargs)

        primary = _capture(primary_call)
        shadow = _capture(shadow_call)
        self._maybe_report(name, args, kwargs, primary, shadow)

        if primary["error"] is not None:
            raise primary["error"]
        return primary["result"]

    def _maybe_report(self, name, args, kwargs, primary, shadow):
        mismatch = None
        if type(primary["error"]) is not type(shadow["error"]):
            mismatch = "error_type"
        elif primary["error"] is not None and str(primary["error"]) != str(shadow["error"]):
            mismatch = "error_message"
        elif primary["error"] is None and _normalize(primary["result"]) != _normalize(shadow["result"]):
            mismatch = "result"

        if mismatch is None:
            return

        payload = {
            "kind": mismatch,
            "operation": name,
            "args": args,
            "kwargs": kwargs,
            "primary_result": None if primary["result"] is _MISSING else primary["result"],
            "shadow_result": None if shadow["result"] is _MISSING else shadow["result"],
            "primary_error": None if primary["error"] is None else repr(primary["error"]),
            "shadow_error": None if shadow["error"] is None else repr(shadow["error"]),
        }

        if self._on_mismatch is not None:
            self._on_mismatch(payload)
        if self._strict:
            raise NativeShadowMismatch(payload)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def method(*args, **kwargs):
            return self._invoke(name, *args, **kwargs)

        return method


class ShadowPipeline:
    """Queue commands and compare primary vs native pipeline results on execute()."""

    def __init__(self, client, transaction=False):
        self._client = client
        self._transaction = transaction
        self._commands = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self):
        primary_pipe = self._client._primary.pipeline(transaction=self._transaction)
        shadow_pipe = self._client._shadow.pipeline(transaction=self._transaction)

        for name, args, kwargs in self._commands:
            getattr(primary_pipe, name)(*args, **kwargs)
            getattr(shadow_pipe, name)(*args, **kwargs)

        primary = _capture(primary_pipe.execute)
        shadow = _capture(shadow_pipe.execute)
        self._client._maybe_report("pipeline.execute", tuple(self._commands), {}, primary, shadow)
        self._commands = []

        if primary["error"] is not None:
            raise primary["error"]
        return primary["result"]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def method(*args, **kwargs):
            self._commands.append((name, args, kwargs))
            return self

        return method


def native_shadow(*args, **kwargs):
    """Create a shadow-mode client with redis-py as primary and Zig as the mirror."""

    return ShadowRedis(*args, **kwargs)


def native_compare(
    fn,
    host="127.0.0.1",
    port=6379,
    db=0,
    password=None,
    decode_responses=True,
    *,
    shadow_host=None,
    shadow_port=None,
    shadow_db=None,
    shadow_password=None,
    allow_same_target=False,
):
    """
    Run the same scenario separately against redis-py and the native client.

    This is intended for parity testing without per-call shadow overhead in the
    application path. Callers should point `shadow_*` at an isolated target.
    """

    primary, shadow = _build_clients(
        host=host,
        port=port,
        db=db,
        password=password,
        decode_responses=decode_responses,
        shadow_host=shadow_host,
        shadow_port=shadow_port,
        shadow_db=shadow_db,
        shadow_password=shadow_password,
        allow_same_target=allow_same_target,
    )
    try:
        primary_outcome = _capture(lambda: fn(primary))
        shadow_outcome = _capture(lambda: fn(shadow))
    finally:
        primary.close()
        shadow.close()

    report = {
        "primary_result": None if primary_outcome["result"] is _MISSING else primary_outcome["result"],
        "native_result": None if shadow_outcome["result"] is _MISSING else shadow_outcome["result"],
        "primary_error": None if primary_outcome["error"] is None else repr(primary_outcome["error"]),
        "native_error": None if shadow_outcome["error"] is None else repr(shadow_outcome["error"]),
        "match": False,
    }

    if type(primary_outcome["error"]) is not type(shadow_outcome["error"]):
        report["kind"] = "error_type"
    elif primary_outcome["error"] is not None and str(primary_outcome["error"]) != str(shadow_outcome["error"]):
        report["kind"] = "error_message"
    elif primary_outcome["error"] is None and _normalize(primary_outcome["result"]) != _normalize(shadow_outcome["result"]):
        report["kind"] = "result"
    else:
        report["kind"] = None
        report["match"] = True

    return report
