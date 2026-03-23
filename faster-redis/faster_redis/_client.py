"""Python Redis client. Zig handles the entire hot path."""

import threading
from contextlib import contextmanager

import redis as _redis_py

from faster_redis._redis_accel import (
    close as _close,
    close_pool as _close_pool,
    connect as _connect,
    connect_pool as _connect_pool,
    execute as _execute,
    execute_pooled as _execute_pooled,
    execute_pooled_slot as _execute_pooled_slot,
    execute_pipeline as _execute_pipeline,
    execute_pipeline_pooled as _execute_pipeline_pooled,
    execute_pipeline_pooled_slot as _execute_pipeline_pooled_slot,
)


def _normalize_command_name(name):
    return name.upper().replace('_', ' ').split()


def _reject_unsupported_kwargs(name, kwargs):
    if kwargs:
        keys = ", ".join(sorted(kwargs))
        raise TypeError(
            f"{name}() does not support keyword arguments in the raw-command fallback; "
            f"use execute_command(...) or an explicit method instead (got: {keys})"
        )


def _coerce_command_arg(arg):
    if isinstance(arg, (str, bytes)):
        return arg
    if isinstance(arg, bytearray):
        return bytes(arg)
    if isinstance(arg, memoryview):
        return arg.tobytes()
    return str(arg)


def _response_key(args):
    parts = [str(part).upper() for part in args[:2]]
    if len(parts) >= 2 and parts[0] in {"ACL", "CLIENT", "CONFIG", "OBJECT", "XGROUP"}:
        return f"{parts[0]} {parts[1]}"
    return parts[0] if parts else ""


def _parse_client_list(result):
    if not isinstance(result, str):
        return result
    rows = []
    for line in result.splitlines():
        if not line.strip():
            continue
        entry = {}
        for field in line.split():
            if "=" not in field:
                continue
            key, value = field.split("=", 1)
            entry[key] = value
        rows.append(entry)
    return rows


def _pairs_to_dict(result):
    if not isinstance(result, list):
        return result
    return dict(zip(result[::2], result[1::2]))


def _parse_stream_entries(result):
    if not isinstance(result, list):
        return result
    entries = []
    for item in result:
        if not isinstance(item, list) or len(item) != 2:
            entries.append(item)
            continue
        entry_id, fields = item
        entries.append((entry_id, _pairs_to_dict(fields)))
    return entries


def _parse_xreadgroup(result):
    if not isinstance(result, list):
        return result
    streams = []
    for item in result:
        if not isinstance(item, list) or len(item) != 2:
            streams.append(item)
            continue
        stream_name, entries = item
        streams.append([stream_name, _parse_stream_entries(entries)])
    return streams


def _parse_acl_getuser(result):
    if not isinstance(result, list):
        return result
    raw = _pairs_to_dict(result)
    flags = raw.get("flags", [])
    if not isinstance(flags, list):
        flags = [flags]
    command_tokens = str(raw.get("commands", "")).split()
    categories = [token for token in command_tokens if token.startswith(("+@", "-@"))]
    commands = [token for token in command_tokens if not token.startswith(("+@", "-@"))]

    def _listify(value):
        if value in ("", None):
            return []
        if isinstance(value, list):
            return value
        return str(value).split()

    return {
        "flags": flags,
        "passwords": raw.get("passwords", []) if isinstance(raw.get("passwords", []), list) else _listify(raw.get("passwords")),
        "commands": commands,
        "keys": _listify(raw.get("keys")),
        "channels": _listify(raw.get("channels")),
        "selectors": raw.get("selectors", []) if isinstance(raw.get("selectors", []), list) else _listify(raw.get("selectors")),
        "categories": categories,
        "enabled": "on" in flags,
    }


_ERROR_PREFIXES = (
    "ERR ",
    "WRONGTYPE ",
    "EXECABORT ",
    "NOGROUP ",
    "BUSY ",
    "NOSCRIPT ",
    "NOAUTH ",
    "NOPERM ",
    "READONLY ",
    "MISCONF ",
    "LOADING ",
    "MASTERDOWN ",
    "OOM ",
    "TRYAGAIN ",
    "CLUSTERDOWN ",
    "CROSSSLOT ",
    "MOVED ",
    "ASK ",
)

_OK_TRUE_COMMANDS = {
    "AUTH",
    "FLUSHALL",
    "FLUSHDB",
    "MSET",
    "PING",
    "SELECT",
    "SET",
    "UNWATCH",
    "WATCH",
}

_BOOL_INT_COMMANDS = {"EXPIRE", "HEXISTS", "SISMEMBER", "SETNX"}


def _raise_pipeline_error(value):
    if isinstance(value, list):
        for item in value:
            _raise_pipeline_error(item)
        return
    if isinstance(value, str) and value.startswith(_ERROR_PREFIXES):
        raise _redis_py.exceptions.ResponseError(value)


def _command_name(part):
    if isinstance(part, bytes):
        return part.decode("utf-8", "ignore").upper()
    return str(part).upper()


def _apply_response_fast(args, result):
    if not args:
        return result, True

    cmd0 = _command_name(args[0])
    if cmd0 == "GET":
        return result, True

    if cmd0 in _OK_TRUE_COMMANDS:
        if result == "OK" or result == "PONG":
            return True, True
        return result, True

    if cmd0 in _BOOL_INT_COMMANDS:
        return (bool(result) if result is not None else None), True

    if cmd0 == "ZRANGE":
        if len(args) > 4 and any(_command_name(part) == "WITHSCORES" for part in args[1:]):
            if not isinstance(result, list):
                return result, True
            pairs = []
            for i in range(0, len(result), 2):
                pairs.append((result[i], float(result[i + 1])))
            return pairs, True
        return result, True

    return result, False


class Redis:
    """Zig-native Redis client. Every command is one Zig call."""

    def __init__(self, host='127.0.0.1', port=6379, db=0, password=None,
                 decode_responses=True):
        self._host = host
        self._port = port
        self._db = db
        self._password = password
        self._decode = decode_responses
        self._conn = _connect(host, port)
        if password:
            self._exec('AUTH', password)
        if db:
            self._exec('SELECT', str(db))

    def _exec(self, *args):
        result = self._dec(self._execute_raw([_coerce_command_arg(a) for a in args]))
        fast_result, handled = _apply_response_fast(args, result)
        if handled:
            return fast_result
        return self._apply_response_callback(args, result)

    def _execute_raw(self, args):
        return _execute(self._conn, args)

    def _execute_pipeline_raw(self, cmd_lists):
        return _execute_pipeline(self._conn, cmd_lists)

    def _dec(self, result):
        return result

    def _apply_response_callback(self, args, result):
        key = _response_key(args)
        if key in {"CONFIG RESETSTAT", "CONFIG SET", "XGROUP CREATE"}:
            return True if result == "OK" else result
        if key == "ACL GETUSER":
            return _parse_acl_getuser(result)
        if key == "CONFIG GET":
            return _pairs_to_dict(result)
        if key == "CLIENT LIST":
            return _parse_client_list(result)
        if key == "XGROUP DESTROY":
            return bool(result) if result is not None else None
        return result

    def close(self):
        if self._conn is not None:
            _close(self._conn)
            self._conn = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # -- Strings -----------------------------------------------------------
    def set(self, key, value, ex=None, px=None, nx=False, xx=False):
        args = ['SET', key, value]
        if ex is not None: args.extend(['EX', str(ex)])
        if px is not None: args.extend(['PX', str(px)])
        if nx: args.append('NX')
        if xx: args.append('XX')
        return self._exec(*args)

    def get(self, key): return self._exec('GET', key)
    def mset(self, mapping):
        args = ['MSET']
        for k, v in mapping.items(): args.extend([k, v])
        return self._exec(*args)
    def mget(self, *keys):
        if len(keys) == 1 and isinstance(keys[0], (list, tuple)): keys = keys[0]
        return self._exec('MGET', *keys)
    def delete(self, *keys): return self._exec('DEL', *keys)
    def exists(self, *keys): return self._exec('EXISTS', *keys)
    def incr(self, key, amount=1):
        return self._exec('INCR', key) if amount == 1 else self._exec('INCRBY', key, amount)
    def decr(self, key, amount=1):
        return self._exec('DECR', key) if amount == 1 else self._exec('DECRBY', key, amount)
    def expire(self, key, seconds): return self._exec('EXPIRE', key, seconds)
    def ttl(self, key): return self._exec('TTL', key)
    def keys(self, pattern='*'): return self._exec('KEYS', pattern)
    def type(self, key): return self._exec('TYPE', key)
    def strlen(self, key): return self._exec('STRLEN', key)
    def append(self, key, value): return self._exec('APPEND', key, value)
    def setex(self, key, seconds, value): return self._exec('SETEX', key, seconds, value)
    def setnx(self, key, value): return self._exec('SETNX', key, value)
    def getrange(self, key, start, end): return self._exec('GETRANGE', key, start, end)

    # -- Hashes ------------------------------------------------------------
    def hset(self, key, field=None, value=None, mapping=None):
        args = ['HSET', key]
        if field and value: args.extend([field, value])
        if mapping:
            for k, v in mapping.items(): args.extend([k, v])
        return self._exec(*args)
    def hget(self, key, field): return self._exec('HGET', key, field)
    def hgetall(self, key):
        r = self._exec('HGETALL', key)
        return dict(zip(r[::2], r[1::2])) if isinstance(r, list) else r
    def hdel(self, key, *fields): return self._exec('HDEL', key, *fields)
    def hexists(self, key, field): return self._exec('HEXISTS', key, field)
    def hkeys(self, key): return self._exec('HKEYS', key)
    def hvals(self, key): return self._exec('HVALS', key)
    def hlen(self, key): return self._exec('HLEN', key)
    def hincrby(self, key, field, amount=1): return self._exec('HINCRBY', key, field, amount)

    # -- Lists -------------------------------------------------------------
    def lpush(self, key, *values): return self._exec('LPUSH', key, *values)
    def rpush(self, key, *values): return self._exec('RPUSH', key, *values)
    def lpop(self, key): return self._exec('LPOP', key)
    def rpop(self, key): return self._exec('RPOP', key)
    def llen(self, key): return self._exec('LLEN', key)
    def lrange(self, key, start, stop): return self._exec('LRANGE', key, start, stop)
    def lindex(self, key, index): return self._exec('LINDEX', key, index)

    # -- Sets --------------------------------------------------------------
    def sadd(self, key, *members): return self._exec('SADD', key, *members)
    def smembers(self, key): return self._exec('SMEMBERS', key)
    def srem(self, key, *members): return self._exec('SREM', key, *members)
    def scard(self, key): return self._exec('SCARD', key)
    def sismember(self, key, member): return self._exec('SISMEMBER', key, member)
    def sunion(self, *keys): return self._exec('SUNION', *keys)
    def sinter(self, *keys): return self._exec('SINTER', *keys)

    # -- Sorted sets -------------------------------------------------------
    def zadd(self, key, mapping):
        args = ['ZADD', key]
        for m, s in mapping.items(): args.extend([s, m])
        return self._exec(*args)
    def zrange(self, key, start, stop, withscores=False, desc=False, byscore=False):
        args = ['ZRANGE', key, start, stop]
        if byscore: args.append('BYSCORE')
        if desc: args.append('REV')
        if withscores: args.append('WITHSCORES')
        return self._exec(*args)
    def zrank(self, key, member): return self._exec('ZRANK', key, member)
    def zcard(self, key): return self._exec('ZCARD', key)
    def zscore(self, key, member): return self._exec('ZSCORE', key, member)
    def geoadd(self, key, values, nx=False, xx=False, ch=False):
        args = ['GEOADD', key]
        if nx: args.append('NX')
        if xx: args.append('XX')
        if ch: args.append('CH')
        if isinstance(values, (list, tuple)) and values and not isinstance(values[0], (list, tuple)):
            values = [values]
        for item in values:
            lon, lat, member = item
            args.extend([lon, lat, member])
        return self._exec(*args)
    def geopos(self, key, *members):
        result = self._exec('GEOPOS', key, *members)
        if not isinstance(result, list):
            return result
        parsed = []
        for item in result:
            if item is None:
                parsed.append(None)
                continue
            if isinstance(item, list) and len(item) == 2:
                parsed.append((float(item[0]), float(item[1])))
            else:
                parsed.append(item)
        return parsed

    # -- Streams -----------------------------------------------------------
    def xadd(self, name, fields, id='*', maxlen=None, approximate=True, nomkstream=False):
        args = ['XADD', name]
        if nomkstream:
            args.append('NOMKSTREAM')
        if maxlen is not None:
            args.extend(['MAXLEN'])
            if approximate:
                args.append('~')
            args.append(maxlen)
        args.append(id)
        for key, value in fields.items():
            args.extend([key, value])
        return self._exec(*args)

    def xrange(self, name, min='-', max='+', count=None):
        args = ['XRANGE', name, min, max]
        if count is not None:
            args.extend(['COUNT', count])
        return _parse_stream_entries(self._exec(*args))

    def xgroup_create(self, name, groupname, id='$', mkstream=False, entriesread=None):
        args = ['XGROUP', 'CREATE', name, groupname, id]
        if mkstream:
            args.append('MKSTREAM')
        if entriesread is not None:
            args.extend(['ENTRIESREAD', entriesread])
        return self._exec(*args)
    def xgroup_destroy(self, name, groupname): return self._exec('XGROUP', 'DESTROY', name, groupname)
    def xgroup_createconsumer(self, name, groupname, consumername):
        return self._exec('XGROUP', 'CREATECONSUMER', name, groupname, consumername)
    def xgroup_delconsumer(self, name, groupname, consumername):
        return self._exec('XGROUP', 'DELCONSUMER', name, groupname, consumername)

    def xreadgroup(self, groupname, consumername, streams, count=None, block=None, noack=False):
        args = ['XREADGROUP', 'GROUP', groupname, consumername]
        if count is not None:
            args.extend(['COUNT', count])
        if block is not None:
            args.extend(['BLOCK', block])
        if noack:
            args.append('NOACK')
        args.append('STREAMS')
        keys = list(streams.keys())
        args.extend(keys)
        args.extend(streams[key] for key in keys)
        return _parse_xreadgroup(self._exec(*args))

    # -- Server ------------------------------------------------------------
    def ping(self): return self._exec('PING')
    def acl_list(self): return self._exec('ACL', 'LIST')
    def acl_whoami(self): return self._exec('ACL', 'WHOAMI')
    def acl_getuser(self, username): return self._exec('ACL', 'GETUSER', username)
    def info(self, section=None): return self._exec('INFO', section) if section else self._exec('INFO')
    def client_list(self, _type=None):
        args = ['CLIENT', 'LIST']
        if _type is not None:
            args.extend(['TYPE', _type])
        return self._exec(*args)
    def client_id(self): return self._exec('CLIENT', 'ID')
    def dbsize(self): return self._exec('DBSIZE')
    def flushdb(self): return self._exec('FLUSHDB')
    def flushall(self): return self._exec('FLUSHALL')
    def select(self, db): return self._exec('SELECT', str(db))
    def echo(self, msg): return self._exec('ECHO', msg)
    def time(self): return self._exec('TIME')
    def script_load(self, script): return self._exec('SCRIPT', 'LOAD', script)
    def eval(self, script, numkeys, *keys_and_args): return self._exec('EVAL', script, numkeys, *keys_and_args)
    def evalsha(self, sha1, numkeys, *keys_and_args): return self._exec('EVALSHA', sha1, numkeys, *keys_and_args)
    def config_get(self, pattern="*"): return self._exec('CONFIG', 'GET', pattern)
    def config_set(self, name, value): return self._exec('CONFIG', 'SET', name, value)
    def config_resetstat(self): return self._exec('CONFIG', 'RESETSTAT')
    def object(self, infotype, key):
        return self._exec('OBJECT', infotype, key)
    def object_encoding(self, key): return self.object('ENCODING', key)
    def object_refcount(self, key): return self.object('REFCOUNT', key)
    def object_idletime(self, key): return self.object('IDLETIME', key)

    # -- Pipeline ----------------------------------------------------------
    def pipeline(self, transaction=False):
        return Pipeline(self, transaction)

    # -- Catch-all for any Redis command not explicitly defined -----
    def execute_command(self, *args):
        """Execute any Redis command. Same as redis-py's interface."""
        return self._exec(*args)

    def __getattr__(self, name):
        """Fallback for raw Redis commands without redis-py response callbacks."""
        if name.startswith('_'):
            raise AttributeError(name)
        def method(*args, **kwargs):
            _reject_unsupported_kwargs(name, kwargs)
            cmd = _normalize_command_name(name)
            return self._exec(*cmd, *args)
        return method


class Pipeline:
    """Buffered pipeline. execute() sends all commands in one Zig call."""

    def __init__(self, client, transaction=False):
        self._client = client
        self._transaction = transaction
        self._watching = False
        self._in_multi = not transaction
        self._commands = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def execute(self):
        if not self._commands:
            if self._watching:
                self._watching = False
            return []
        cmds = self._commands
        if self._transaction:
            cmds = [['MULTI']] + cmds + [['EXEC']]

        # One Zig call: pack all, send all, recv all
        cmd_lists = [[_coerce_command_arg(a) for a in cmd] for cmd in cmds]
        raw_results = self._client._execute_pipeline_raw(cmd_lists)
        results = []
        for cmd, raw in zip(cmds, raw_results):
            decoded = self._client._dec(raw)
            fast_result, handled = _apply_response_fast(cmd, decoded)
            if handled:
                results.append(fast_result)
            else:
                results.append(self._client._apply_response_callback(cmd, decoded))

        if self._transaction and results:
            if isinstance(results[-1], list):
                exec_results = []
                for cmd, result in zip(self._commands, results[-1]):
                    decoded = self._client._dec(result)
                    fast_result, handled = _apply_response_fast(cmd, decoded)
                    if handled:
                        exec_results.append(fast_result)
                    else:
                        exec_results.append(self._client._apply_response_callback(cmd, decoded))
                _raise_pipeline_error(exec_results)
                self._commands = []
                self._watching = False
                self._in_multi = False
                return exec_results
            self._commands = []
            self._watching = False
            self._in_multi = False
            raise _redis_py.exceptions.WatchError("Watched variable changed.")

        _raise_pipeline_error(results)
        self._commands = []
        self._watching = False
        return results

    def watch(self, *keys):
        self._watching = True
        self._in_multi = False
        return self._client._exec('WATCH', *keys)

    def unwatch(self):
        self._watching = False
        self._in_multi = False
        self._commands = []
        return self._client._exec('UNWATCH')

    def multi(self):
        self._transaction = True
        self._in_multi = True
        return self

    def __getattr__(self, name):
        """Buffer any Redis command."""
        if name.startswith('_'):
            raise AttributeError(name)
        def method(*args, **kwargs):
            _reject_unsupported_kwargs(name, kwargs)
            if self._watching and not self._in_multi:
                return getattr(self._client, name)(*args, **kwargs)
            self._commands.append(_normalize_command_name(name) + list(args))
            return self
        return method


class ThreadLocalRedis:
    """One Redis connection per Python thread."""

    def __init__(self, host='127.0.0.1', port=6379, db=0, password=None,
                 decode_responses=True):
        self._kwargs = {
            'host': host,
            'port': port,
            'db': db,
            'password': password,
            'decode_responses': decode_responses,
        }
        self._local = threading.local()
        self._registry_lock = threading.Lock()
        self._clients = {}

    def client(self):
        client = getattr(self._local, 'client', None)
        if client is None:
            client = Redis(**self._kwargs)
            self._local.client = client
            with self._registry_lock:
                self._clients[threading.get_ident()] = client
        return client

    def close_thread(self):
        client = getattr(self._local, 'client', None)
        if client is None:
            return
        client.close()
        self._local.client = None
        with self._registry_lock:
            self._clients.pop(threading.get_ident(), None)

    def close(self):
        with self._registry_lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            client.close()
        self._local.client = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self.client(), name)


class _PooledSlotRedis(Redis):
    """Thread-bound view over a native pool slot."""

    def __init__(self, pool, slot):
        self._pool_owner = pool
        self._pool = pool._pool
        self._slot = slot
        self._host = pool._host
        self._port = pool._port
        self._db = pool._db
        self._password = pool._password
        self._decode = pool._decode
        self._conn = None

    def _execute_raw(self, args):
        return _execute_pooled_slot(self._pool, self._slot, args)

    def _execute_pipeline_raw(self, cmd_lists):
        return _execute_pipeline_pooled_slot(self._pool, self._slot, cmd_lists)

    def close(self):
        return None


class PooledRedis(Redis):
    """Small fixed-size native pool of Redis connections."""

    def __init__(self, size=4, host='127.0.0.1', port=6379, db=0, password=None,
                 decode_responses=True):
        self._host = host
        self._port = port
        self._db = db
        self._password = password
        self._decode = decode_responses
        self._size = size
        self._pool = _connect_pool(host, port, size)
        self._local = threading.local()
        self._slot_lock = threading.Lock()
        self._next_slot = 0
        if password:
            for _ in range(size):
                self._exec('AUTH', password)
        if db:
            for _ in range(size):
                self._exec('SELECT', str(db))

    @contextmanager
    def connection(self, timeout=None):
        del timeout
        yield self.client()

    def _slot(self):
        slot = getattr(self._local, 'slot', None)
        if slot is None:
            with self._slot_lock:
                slot = self._next_slot % self._size
                self._next_slot += 1
            self._local.slot = slot
        return slot

    def client(self):
        client = getattr(self._local, 'client', None)
        if client is None:
            client = _PooledSlotRedis(self, self._slot())
            self._local.client = client
        return client

    def _execute_raw(self, args):
        return self.client()._execute_raw(args)

    def _execute_pipeline_raw(self, cmd_lists):
        return self.client()._execute_pipeline_raw(cmd_lists)

    def _exec(self, *args):
        return self.client()._exec(*args)

    def close(self):
        if getattr(self, '_pool', None) is not None:
            _close_pool(self._pool)
            self._pool = None
        self._local = threading.local()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def pipeline(self, transaction=False):
        return self.client().pipeline(transaction=transaction)

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self.client(), name)
