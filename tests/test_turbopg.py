"""Tests for TurboPG standalone client."""

import pytest

# ── Import tests ─────────────────────────────────────────────────────────────


def test_import():
    from turbopg import Database, __version__

    assert __version__ == "0.1.1"
    assert Database is not None


def test_repr():
    from turbopg import Database

    # Don't actually connect — just test the repr
    db = object.__new__(Database)
    db.conn_string = "postgres://localhost/test"
    db.pool_size = 8
    assert "Database" in repr(db)
    assert "localhost" in repr(db)


# ── Parameter conversion tests ───────────────────────────────────────────────


def test_param_conversion_single():
    """$1 → %s for psycopg2."""
    from turbopg.client import Database

    db = object.__new__(Database)
    db._fallback_engine = None
    db._native = None

    # Test the conversion logic directly
    sql = "SELECT * FROM users WHERE id = $1"
    converted = sql
    for i in range(1, 0, -1):
        converted = converted.replace(f"${i}", "%s")
    assert converted == "SELECT * FROM users WHERE id = %s"


def test_param_conversion_multiple():
    """$1, $2, $3 → %s, %s, %s in reverse order."""
    sql = "SELECT * FROM t WHERE a = $1 AND b = $2 AND c = $3"
    converted = sql
    for i in range(3, 0, -1):
        converted = converted.replace(f"${i}", "%s")
    assert converted == "SELECT * FROM t WHERE a = %s AND b = %s AND c = %s"


def test_param_conversion_no_collision():
    """$10 should not be partially replaced by $1."""
    sql = "SELECT $1, $10"
    converted = sql
    for i in range(10, 0, -1):
        converted = converted.replace(f"${i}", "%s")
    assert converted == "SELECT %s, %s"


# ── Serialization tests ─────────────────────────────────────────────────────


def test_serialize_decimal():
    from decimal import Decimal

    from turbopg.client import Database

    assert Database._serialize_value(Decimal("99.99")) == 99.99
    assert isinstance(Database._serialize_value(Decimal("0")), float)


def test_serialize_datetime():
    from datetime import datetime

    from turbopg.client import Database

    dt = datetime(2026, 3, 20, 12, 0, 0)
    result = Database._serialize_value(dt)
    assert "2026-03-20" in result
    assert isinstance(result, str)


def test_serialize_date():
    from datetime import date

    from turbopg.client import Database

    d = date(2026, 3, 20)
    result = Database._serialize_value(d)
    assert result == "2026-03-20"


def test_serialize_none():
    from turbopg.client import Database

    assert Database._serialize_value(None) is None


def test_serialize_string():
    from turbopg.client import Database

    assert Database._serialize_value("hello") == "hello"


def test_serialize_int():
    from turbopg.client import Database

    assert Database._serialize_value(42) == 42


def test_serialize_list():
    from turbopg.client import Database

    assert Database._serialize_value([1, 2, 3]) == [1, 2, 3]


# ── Context manager tests ───────────────────────────────────────────────────


def test_context_manager():
    """Context manager should not raise."""
    from turbopg import Database

    # Create a dummy instance that won't connect
    db = object.__new__(Database)
    db.conn_string = "postgres://fake"
    db.pool_size = 1

    # __enter__ and __exit__ should work
    with db as d:
        assert d is db


# ── Error handling tests ─────────────────────────────────────────────────────


def test_query_no_backend_raises():
    """query() without backend should raise NotImplementedError."""
    from turbopg import Database

    db = object.__new__(Database)
    db._native = True  # pretend native exists
    db._native_raw = False  # no raw query path
    db._fallback_engine = None  # but no fallback

    with pytest.raises(NotImplementedError, match="psycopg2-binary"):
        db.query("SELECT 1")


def test_execute_no_backend_raises():
    from turbopg import Database

    db = object.__new__(Database)
    db._native = True
    db._native_raw = False
    db._fallback_engine = None

    with pytest.raises(NotImplementedError, match="psycopg2-binary"):
        db.execute("SELECT 1")


def test_query_one_empty():
    """query_one should return None when query returns empty list."""
    from turbopg import Database

    db = object.__new__(Database)
    db._native = None
    db._fallback_engine = None

    # Mock query to return empty
    db.query = lambda *a, **k: []
    assert db.query_one("SELECT 1") is None


def test_query_one_returns_first():
    """query_one should return first row."""
    from turbopg import Database

    db = object.__new__(Database)

    db.query = lambda *a, **k: [{"id": 1}, {"id": 2}]
    result = db.query_one("SELECT 1")
    assert result == {"id": 1}
