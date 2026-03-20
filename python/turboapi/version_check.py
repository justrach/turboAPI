#!/usr/bin/env python3
"""
TurboAPI Version & Free-Threading Check
Ensures TurboAPI runs on Python 3.14+ free-threading builds only.
"""

import logging
import sys
import sysconfig

logger = logging.getLogger(__name__)

# ── Emoji / ASCII symbols ────────────────────────────────────────────────────

CHECK_MARK = "✅"
CROSS_MARK = "❌"
ROCKET = "🚀"
THREAD = "🧵"
BULB = "💡"
TARGET = "🎯"
BOOK = "📚"
MAG = "🔍"
PARTY = "🎉"

try:
    # Test if terminal can render emojis
    CHECK_MARK.encode(sys.stdout.encoding or "utf-8")
except (UnicodeEncodeError, LookupError, AttributeError):
    CHECK_MARK = "[OK]"
    CROSS_MARK = "[X]"
    ROCKET = ">>"
    THREAD = "--"
    BULB = "i "
    TARGET = "* "
    BOOK = "# "
    MAG = "? "
    PARTY = "!!"


# ── Detection ────────────────────────────────────────────────────────────────


def _detect_free_threading() -> bool:
    """Detect if Python is running in free-threading (no-GIL) mode."""
    # Method 1: sysconfig Py_GIL_DISABLED (canonical)
    try:
        val = sysconfig.get_config_var("Py_GIL_DISABLED")
        if val is not None:
            return bool(int(val))
    except (ValueError, TypeError):
        pass  # Py_GIL_DISABLED config var not parseable; try fallback methods

    # Method 2: sys._is_gil_enabled() (3.13t+)
    if hasattr(sys, "_is_gil_enabled"):
        try:
            return not sys._is_gil_enabled()
        except Exception:
            pass  # _is_gil_enabled() call failed; assume GIL is enabled

    return False


# ── Check ────────────────────────────────────────────────────────────────────


def check_python_version():
    """Raise ImportError if Python < 3.14."""
    if sys.version_info < (3, 14):  # noqa: UP036 — runtime guard, not dead code
        raise ImportError(
            f"{CROSS_MARK} TurboAPI requires Python 3.14+.\n"
            f"   Current: Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n"
            f"\n"
            f"   Install:\n"
            f"     uv python install 3.14t   # recommended (free-threaded)\n"
            f"     uv python install 3.14    # also works\n"
        )


def check_free_threading_support():
    """Raise ImportError if not running on a free-threading build."""
    check_python_version()

    if not _detect_free_threading():
        raise ImportError(
            f"{CROSS_MARK} TurboAPI requires a free-threading Python build (no-GIL).\n"
            f"   Current: Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} (GIL enabled)\n"
            f"\n"
            f"   {THREAD} Free-threading gives you:\n"
            f"     • 7x faster than FastAPI\n"
            f"     • True multi-threaded parallelism\n"
            f"     • Zig-native concurrency\n"
            f"\n"
            f"   Install:\n"
            f"     uv python install 3.14t\n"
            f"     python3.14t -m pip install turboapi\n"
        )

    v = sys.version_info
    logger.info("TurboAPI: Python %d.%d.%d free-threading active", v.major, v.minor, v.micro)


def get_python_threading_info() -> dict:
    """Return diagnostic info about the Python runtime."""
    ft = _detect_free_threading()
    return {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "free_threading": ft,
        "gil_enabled": not ft,
        "implementation": getattr(sys, "implementation", type("", (), {"name": "unknown"})).name,
    }


# ── Auto-check on import ────────────────────────────────────────────────────

if __name__ != "__main__":
    check_free_threading_support()

if __name__ == "__main__":
    print(f"{MAG} TurboAPI Python Compatibility Check")
    print("=" * 50)
    info = get_python_threading_info()
    print(f"Python:         {info['python_version']}")
    print(f"Free-threading: {'YES' if info['free_threading'] else 'NO'}")
    print(f"GIL:            {'disabled' if info['free_threading'] else 'enabled'}")
    print()
    try:
        check_free_threading_support()
        print(f"{PARTY} Compatible — ready for 7x FastAPI performance!")
    except ImportError as e:
        print(f"{CROSS_MARK} Not compatible")
        print(f"   {e}")
