"""Python Redis client. Zig handles the entire hot path."""

from faster_redis._redis_accel import (
    connect as _connect,
    execute as _execute,
    execute_pipeline as _execute_pipeline,
    close as _close,
)


class Redis:
    """Zig-native Redis client. Every command is one Zig call."""

    def __init__(self, host='127.0.0.1', port=6379, db=0, password=None,
                 decode_responses=True):
        self._decode = decode_responses
        _connect(host, port)
        if password:
            self._exec('AUTH', password)
        if db:
            self._exec('SELECT', str(db))

    def _exec(self, *args):
        result = _execute([str(a) for a in args])
        return self._dec(result)

    def _dec(self, result):
        if result is None:
            return None
        if isinstance(result, list):
            return [self._dec(x) for x in result]
        return result

    def close(self):
        _close()

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
    def zrange(self, key, start, stop, withscores=False):
        args = ['ZRANGE', key, start, stop]
        if withscores: args.append('WITHSCORES')
        return self._exec(*args)
    def zrank(self, key, member): return self._exec('ZRANK', key, member)
    def zcard(self, key): return self._exec('ZCARD', key)
    def zscore(self, key, member): return self._exec('ZSCORE', key, member)

    # -- Server ------------------------------------------------------------
    def ping(self): return self._exec('PING')
    def info(self, section=None): return self._exec('INFO', section) if section else self._exec('INFO')
    def dbsize(self): return self._exec('DBSIZE')
    def flushdb(self): return self._exec('FLUSHDB')
    def flushall(self): return self._exec('FLUSHALL')
    def select(self, db): return self._exec('SELECT', str(db))
    def echo(self, msg): return self._exec('ECHO', msg)
    def time(self): return self._exec('TIME')

    # -- Pipeline ----------------------------------------------------------
    def pipeline(self, transaction=False):
        return Pipeline(self, transaction)


class Pipeline:
    """Buffered pipeline. execute() sends all commands in one Zig call."""

    def __init__(self, client, transaction=False):
        self._client = client
        self._transaction = transaction
        self._commands = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def execute(self):
        if not self._commands:
            return []
        cmds = self._commands
        if self._transaction:
            cmds = [['MULTI']] + cmds + [['EXEC']]

        # One Zig call: pack all, send all, recv all
        cmd_lists = [[str(a) for a in cmd] for cmd in cmds]
        results = _execute_pipeline(cmd_lists)
        results = [self._client._dec(r) for r in results]

        if self._transaction and results:
            return results[-1] if isinstance(results[-1], list) else results[1:-1]

        self._commands = []
        return results

    def __getattr__(self, name):
        """Buffer any Redis command."""
        def method(*args, **kwargs):
            self._commands.append([name.upper()] + list(args))
            return self
        return method
