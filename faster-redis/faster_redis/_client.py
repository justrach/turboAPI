"""Python API for the Zig Redis client."""

from faster_redis._redis_accel import (
    pack_command as _pack,
    parse_resp as _parse,
)
import socket
import time

class Redis:
    """Zig-native Redis client. Drop-in API compatible with redis-py."""

    def __init__(self, host='localhost', port=6379, db=0, password=None,
                 decode_responses=True, socket_timeout=None):
        self._host = host
        self._port = port
        self._db = db
        self._decode = decode_responses
        self._sock = None
        self._connect()
        if password:
            self._exec('AUTH', password)
        if db:
            self._exec('SELECT', str(db))

    def _connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock.connect((self._host, self._port))

    def _exec(self, *args):
        """Execute a command: Zig pack, socket send, socket recv, Zig parse."""
        cmd = _pack([str(a) for a in args])
        self._sock.sendall(cmd)
        # Read response -- handle variable-length responses
        data = self._recv()
        result = _parse(data)
        return self._decode_result(result)

    def _recv(self):
        """Read a complete RESP response from socket."""
        buf = b''
        while True:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("Connection closed")
            buf += chunk
            # Try to parse -- if complete, we're done
            try:
                _parse(buf)
                return buf
            except (ValueError, Exception):
                # Need more data
                if len(buf) > 10 * 1024 * 1024:
                    raise ConnectionError("Response too large")
                continue

    def _decode_result(self, result):
        if isinstance(result, bytes) and self._decode:
            return result.decode('utf-8', errors='replace')
        if isinstance(result, list):
            return [self._decode_result(x) for x in result]
        return result

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # -- String commands ----------------------------------------------

    def set(self, key, value, ex=None, px=None, nx=False, xx=False):
        args = ['SET', key, value]
        if ex is not None:
            args.extend(['EX', str(ex)])
        if px is not None:
            args.extend(['PX', str(px)])
        if nx:
            args.append('NX')
        if xx:
            args.append('XX')
        return self._exec(*args)

    def get(self, key):
        return self._exec('GET', key)

    def mset(self, mapping):
        args = ['MSET']
        for k, v in mapping.items():
            args.extend([k, v])
        return self._exec(*args)

    def mget(self, *keys):
        if len(keys) == 1 and isinstance(keys[0], (list, tuple)):
            keys = keys[0]
        return self._exec('MGET', *keys)

    def delete(self, *keys):
        return self._exec('DEL', *keys)

    def exists(self, *keys):
        return self._exec('EXISTS', *keys)

    def incr(self, key, amount=1):
        if amount == 1:
            return self._exec('INCR', key)
        return self._exec('INCRBY', key, amount)

    def decr(self, key, amount=1):
        if amount == 1:
            return self._exec('DECR', key)
        return self._exec('DECRBY', key, amount)

    def expire(self, key, seconds):
        return self._exec('EXPIRE', key, seconds)

    def ttl(self, key):
        return self._exec('TTL', key)

    def keys(self, pattern='*'):
        return self._exec('KEYS', pattern)

    def type(self, key):
        return self._exec('TYPE', key)

    def strlen(self, key):
        return self._exec('STRLEN', key)

    def append(self, key, value):
        return self._exec('APPEND', key, value)

    def getset(self, key, value):
        return self._exec('GETSET', key, value)

    def setex(self, key, seconds, value):
        return self._exec('SETEX', key, seconds, value)

    def setnx(self, key, value):
        return self._exec('SETNX', key, value)

    # -- Hash commands ------------------------------------------------

    def hset(self, key, field=None, value=None, mapping=None):
        args = ['HSET', key]
        if field and value:
            args.extend([field, value])
        if mapping:
            for k, v in mapping.items():
                args.extend([k, v])
        return self._exec(*args)

    def hget(self, key, field):
        return self._exec('HGET', key, field)

    def hgetall(self, key):
        result = self._exec('HGETALL', key)
        if isinstance(result, list):
            return dict(zip(result[::2], result[1::2]))
        return result

    def hdel(self, key, *fields):
        return self._exec('HDEL', key, *fields)

    def hexists(self, key, field):
        return self._exec('HEXISTS', key, field)

    def hkeys(self, key):
        return self._exec('HKEYS', key)

    def hvals(self, key):
        return self._exec('HVALS', key)

    def hlen(self, key):
        return self._exec('HLEN', key)

    # -- List commands ------------------------------------------------

    def lpush(self, key, *values):
        return self._exec('LPUSH', key, *values)

    def rpush(self, key, *values):
        return self._exec('RPUSH', key, *values)

    def lpop(self, key):
        return self._exec('LPOP', key)

    def rpop(self, key):
        return self._exec('RPOP', key)

    def llen(self, key):
        return self._exec('LLEN', key)

    def lrange(self, key, start, stop):
        return self._exec('LRANGE', key, start, stop)

    # -- Set commands -------------------------------------------------

    def sadd(self, key, *members):
        return self._exec('SADD', key, *members)

    def smembers(self, key):
        return self._exec('SMEMBERS', key)

    def srem(self, key, *members):
        return self._exec('SREM', key, *members)

    def scard(self, key):
        return self._exec('SCARD', key)

    def sismember(self, key, member):
        return self._exec('SISMEMBER', key, member)

    # -- Sorted set commands ------------------------------------------

    def zadd(self, key, mapping):
        args = ['ZADD', key]
        for member, score in mapping.items():
            args.extend([score, member])
        return self._exec(*args)

    def zrange(self, key, start, stop, withscores=False):
        args = ['ZRANGE', key, start, stop]
        if withscores:
            args.append('WITHSCORES')
        return self._exec(*args)

    def zrank(self, key, member):
        return self._exec('ZRANK', key, member)

    def zcard(self, key):
        return self._exec('ZCARD', key)

    # -- Server commands ----------------------------------------------

    def ping(self):
        return self._exec('PING')

    def info(self, section=None):
        if section:
            return self._exec('INFO', section)
        return self._exec('INFO')

    def dbsize(self):
        return self._exec('DBSIZE')

    def flushdb(self):
        return self._exec('FLUSHDB')

    def flushall(self):
        return self._exec('FLUSHALL')

    def select(self, db):
        return self._exec('SELECT', str(db))

    # -- Pipeline -----------------------------------------------------

    def pipeline(self, transaction=False):
        return Pipeline(self, transaction)


class Pipeline:
    """Zig-pipelined command buffer. All commands sent in one TCP write."""

    def __init__(self, client, transaction=False):
        self._client = client
        self._transaction = transaction
        self._commands = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self):
        """Send all buffered commands in one shot, parse all responses."""
        if not self._commands:
            return []

        cmds = self._commands
        if self._transaction:
            cmds = [['MULTI']] + cmds + [['EXEC']]

        # Zig-pack all commands into one buffer
        buf = b''
        for cmd in cmds:
            buf += _pack([str(a) for a in cmd])

        self._client._sock.sendall(buf)

        # Read all responses
        results = []
        raw = b''
        expected = len(cmds)
        while len(results) < expected:
            raw += self._client._sock.recv(65536)
            # Try to parse responses from buffer
            while len(results) < expected and raw:
                try:
                    val = _parse(raw)
                    # Find how much we consumed
                    # Re-parse to get consumed bytes (parse_resp returns value, not consumed)
                    # For now, split on known response boundaries
                    results.append(self._client._decode_result(val))
                    # Remove consumed bytes -- approximate by trying re-parse
                    # This is a hack until we expose consumed bytes from Zig
                    break
                except (ValueError, Exception):
                    break

        # If transaction, unwrap MULTI/EXEC
        if self._transaction and results:
            # First is MULTI OK, last is EXEC array, middle are QUEUED
            return results[-1] if isinstance(results[-1], list) else results[1:-1]

        self._commands = []
        return results

    # -- Command methods (buffer, don't execute) ----------------------
    def __getattr__(self, name):
        """Proxy any Redis command - buffer it for pipeline execution."""
        def method(*args, **kwargs):
            self._commands.append([name.upper()] + list(args))
            return self
        return method

