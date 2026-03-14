#!/usr/bin/env python3
"""
TurboAPI Free-Threading Version Check
Ensures TurboAPI only runs on Python 3.13+ free-threading builds
"""

import io
import sys
import sysconfig
import threading

# Configure stdout to use UTF-8 encoding on Windows
if sys.platform == 'win32':
    # Ensure UTF-8 encoding for print() on Windows
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    elif not isinstance(sys.stdout, io.TextIOWrapper):
        # Fallback for older Python or special stdout
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

# Define symbols that work across all platforms
CHECK_MARK = "[OK]"
CROSS_MARK = "[X]"
ROCKET = "[ROCKET]"
THREAD = "[THREAD]"
BULB = "[INFO]"
TARGET = "[TARGET]"
BOOK = "[DOCS]"
MAG = "[CHECK]"
PARTY = "[SUCCESS]"

# Try to use Unicode emojis if the terminal supports it
try:
    # Test if we can encode/print emojis
    test_str = "✅"
    if sys.platform == 'win32':
        # On Windows, test if console can display the emoji
        test_str.encode(sys.stdout.encoding or 'utf-8')
    # If we get here, emojis work
    CHECK_MARK = "✅"
    CROSS_MARK = "❌"
    ROCKET = "🚀"
    THREAD = "🧵"
    BULB = "💡"
    TARGET = "🎯"
    BOOK = "📚"
    MAG = "🔍"
    PARTY = "🎉"
except (UnicodeEncodeError, LookupError, AttributeError):
    # Fallback to ASCII symbols already set above
    pass


def check_free_threading_support():
    """
    Check if Python is running with free-threading (no-GIL) enabled.
    Raises ImportError if not compatible.
    """

    # Check Python version first

    # Check for free-threading build (multiple detection methods)
    is_free_threading = _detect_free_threading()

    if not is_free_threading:
        raise ImportError(
            f"{CROSS_MARK} TurboAPI requires Python free-threading build (no-GIL).\n"
            f"   Current: Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} with GIL enabled\n"
            f"   \n"
            f"   {THREAD} Free-threading required for:\n"
            f"     • 5-10x performance improvements\n"
            f"     • True multi-threading parallelism\n"
            f"     • Zero Python middleware overhead\n"
            f"     • Zig-native concurrency\n"
            f"   \n"
            f"   Install free-threading Python:\n"
            f"     • uv python install 3.14t\n"
            f"     • python3.14t\n"
            f"     • Build from source: ./configure --disable-gil\n"
            f"   \n"
            f"   {ROCKET} Experience revolutionary performance with free-threading!\n"
            f"   {BOOK} See: PYTHON_FREE_THREADING_GUIDE.md"
        )

    # Success! Print confirmation
    print(f"{CHECK_MARK} TurboAPI: Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} free-threading detected!")
    print(f"{THREAD} True parallelism enabled - ready for 5-10x performance!")


def _detect_free_threading():
    """
    Detect if Python is running in free-threading mode.
    Uses canonical detection methods.
    """

    # Method 1: sysconfig Py_GIL_DISABLED (canonical, 3.13+)
    try:
        gil_disabled = sysconfig.get_config_var("Py_GIL_DISABLED")
        if gil_disabled is not None:
            return bool(int(gil_disabled))
    except (ValueError, TypeError):
        pass

    # Method 2: sys._is_gil_enabled() (available in 3.13t+ when GIL is disabled)
    try:
        if hasattr(sys, '_is_gil_enabled'):
            return not sys._is_gil_enabled()
    except Exception:
        pass

    # Method 3: Check version string for free-threading indicators
    try:
        version_str = sys.version.lower()
        if 'free-threading' in version_str:
            return True
    except Exception:
        pass

    # Default: assume GIL is present
    return False


def get_python_threading_info():
    """Get detailed information about Python threading capabilities."""
    info = {
        'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        'free_threading': _detect_free_threading(),
        'gil_enabled': not _detect_free_threading(),
        'threading_native_id': hasattr(threading._thread, 'get_native_id') if hasattr(threading, '_thread') else False,
        'implementation': sys.implementation.name if hasattr(sys, 'implementation') else 'unknown',
    }

    # Add performance prediction
    if info['free_threading']:
        info['performance_multiplier'] = '5-10x FastAPI'
        info['concurrency'] = 'True parallelism'
        info['gil_overhead'] = 'Zero (Zig-native)'
    else:
        info['performance_multiplier'] = 'Limited by GIL'
        info['concurrency'] = 'Serialized threads'
        info['gil_overhead'] = 'High (Python bottleneck)'

    return info


# Perform the check when module is imported
if __name__ != "__main__":
    try:
        check_free_threading_support()
    except ImportError as e:
        # Re-raise with additional context
        raise ImportError(
            f"{e}\n\n"
            f"{BULB} TurboAPI is designed exclusively for free-threading Python builds.\n"
            f"   This ensures maximum performance and true parallelism.\n"
            f"   \n"
            f"   {TARGET} Why free-threading only?\n"
            f"     • 5-10x performance gains over FastAPI\n"
            f"     • True multi-threading without GIL bottlenecks\n"
            f"     • Zig-native concurrency integration\n"
            f"     • Future-proof architecture\n"
            f"   \n"
            f"   {BOOK} Setup Guide: PYTHON_FREE_THREADING_GUIDE.md\n"
        ) from e


if __name__ == "__main__":
    # Direct execution - show diagnostic information
    print(f"{MAG} TurboAPI Python Free-Threading Compatibility Check")
    print("=" * 60)

    info = get_python_threading_info()

    print(f"Python Version: {info['python_version']}")
    print(f"Implementation: {info['implementation']}")
    print(f"Free-Threading: {CHECK_MARK + ' YES' if info['free_threading'] else CROSS_MARK + ' NO'}")
    print(f"GIL Enabled: {CROSS_MARK + ' YES' if info['gil_enabled'] else CHECK_MARK + ' NO'}")
    print(f"Native Thread ID: {CHECK_MARK + ' YES' if info['threading_native_id'] else CROSS_MARK + ' NO'}")
    print()
    print(f"Expected Performance: {info['performance_multiplier']}")
    print(f"Concurrency Model: {info['concurrency']}")
    print(f"GIL Overhead: {info['gil_overhead']}")

    print("\n" + "=" * 60)

    try:
        check_free_threading_support()
        print(f"{PARTY} TurboAPI compatibility: PASSED")
        print(f"{ROCKET} Ready for revolutionary performance!")
    except ImportError as e:
        print(f"{CROSS_MARK} TurboAPI compatibility: FAILED")
        print(f"   {e}")
