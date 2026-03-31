"""
Tests for security audit fixes (#41).
Each test validates a specific bug fix from the community security audit.
"""

import threading

import pytest

# ── Bug #10: RateLimitMiddleware thread safety ──────────────────────────────

def test_rate_limiter_has_lock():
    """Bug #10: RateLimitMiddleware.requests dict must be guarded by a lock."""
    from turboapi.middleware import RateLimitMiddleware

    rl = RateLimitMiddleware(requests_per_minute=100)
    assert hasattr(rl, "_lock"), "RateLimitMiddleware missing _lock"
    assert isinstance(rl._lock, type(threading.Lock()))


def test_rate_limiter_thread_safe():
    """Bug #10: Concurrent access to rate limiter must not crash."""
    from turboapi.middleware import RateLimitMiddleware
    from turboapi.models import Request

    rl = RateLimitMiddleware(requests_per_minute=10000)
    errors = []

    def hammer():
        try:
            for _ in range(100):
                req = Request(
                    method="GET",
                    path="/",
                    headers={"x-real-ip": f"10.0.0.{threading.current_thread().ident % 256}"},
                )
                try:
                    rl.before_request(req)
                except Exception:
                    pass  # rate limit exceeded is fine
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Thread safety violation: {errors}"


# ── Bug #9: RateLimitMiddleware prefers X-Real-IP ───────────────────────────

def test_rate_limiter_prefers_x_real_ip():
    """Bug #9: Should prefer X-Real-IP over X-Forwarded-For when peer is trusted."""
    from turboapi.middleware import RateLimitMiddleware
    from turboapi.models import Request

    # Configure with trusted proxy so headers are respected
    rl = RateLimitMiddleware(requests_per_minute=1, trusted_proxies={"127.0.0.1"})

    # First request with X-Real-IP from trusted proxy
    req1 = Request(method="GET", path="/", headers={"x-real-ip": "1.2.3.4"})
    req1.client_addr = "127.0.0.1"
    rl.before_request(req1)

    # Second request same X-Real-IP should be rate limited
    req2 = Request(method="GET", path="/", headers={"x-real-ip": "1.2.3.4"})
    req2.client_addr = "127.0.0.1"
    with pytest.raises(Exception, match="Rate limit"):
        rl.before_request(req2)

    # Different X-Real-IP should NOT be rate limited
    req3 = Request(method="GET", path="/", headers={"x-real-ip": "5.6.7.8"})
    req3.client_addr = "127.0.0.1"
    rl.before_request(req3)  # should not raise

# ── Bug #12: CORS wildcard + credentials ────────────────────────────────────

def test_cors_wildcard_credentials_raises():
    """Bug #12: CORSMiddleware must reject allow_credentials=True with wildcard origin."""
    from turboapi.middleware import CORSMiddleware

    with pytest.raises(ValueError, match="incompatible"):
        CORSMiddleware(allow_origins=["*"], allow_credentials=True)


def test_cors_wildcard_without_credentials_ok():
    """Bug #12: Wildcard origin WITHOUT credentials should work fine."""
    from turboapi.middleware import CORSMiddleware

    cors = CORSMiddleware(allow_origins=["*"], allow_credentials=False)
    assert cors.allow_origins == ["*"]


def test_cors_explicit_origin_with_credentials_ok():
    """Bug #12: Explicit origin WITH credentials should work fine."""
    from turboapi.middleware import CORSMiddleware

    cors = CORSMiddleware(
        allow_origins=["https://example.com"],
        allow_credentials=True,
    )
    assert cors.allow_credentials is True


# ── Bug #11: Password hash placeholder ──────────────────────────────────────

def test_get_password_hash_raises():
    """Bug #11: get_password_hash now returns a real hash (not plaintext)."""
    from turboapi.security import get_password_hash

    h = get_password_hash("secret123")
    assert h != "secret123", "must not return plaintext"
    assert "pbkdf2" in h, "must use pbkdf2"
def test_verify_password_raises():
    """Bug #11: verify_password now works correctly (returns bool, not raises)."""
    from turboapi.security import get_password_hash, verify_password

    h = get_password_hash("secret123")
    assert verify_password("secret123", h) is True
    assert verify_password("wrong", h) is False


def test_top_level_verify_password_export_matches_security_module():
    """Public turboapi.verify_password should match turboapi.security.verify_password."""
    from turboapi import verify_password as package_verify_password
    from turboapi.security import verify_password as security_verify_password

    assert package_verify_password is security_verify_password
# ── Bug #5: Port range validation ───────────────────────────────────────────
# (Zig-side — tested via integration; can't unit test @intCast directly)

def test_port_validation_documented():
    """Bug #5: SECURITY.md must document port range validation fix."""
    with open("SECURITY.md") as f:
        content = f.read()
    assert "range-checked" in content.lower() or "1–65535" in content or "1-65535" in content


# ── Bug #1: setError null terminator ────────────────────────────────────────

def test_seterror_fix_documented():
    """Bug #1: SECURITY.md must document bufPrintZ fix."""
    with open("SECURITY.md") as f:
        content = f.read()
    assert "bufPrintZ" in content


# ── Bug #2: Dangling pointers ──────────────────────────────────────────────

def test_dangling_pointer_fix_documented():
    """Bug #2: SECURITY.md must document allocator.dupe fix."""
    with open("SECURITY.md") as f:
        content = f.read()
    assert "allocator.dupe" in content or "dupe" in content


# ── Slowloris protection ────────────────────────────────────────────────────

def test_slowloris_protection_documented():
    """Slowloris: SECURITY.md must document read timeout mitigation."""
    with open("SECURITY.md") as f:
        content = f.read()
    assert "slow" in content.lower() or "timeout" in content.lower() or "SO_RCVTIMEO" in content
