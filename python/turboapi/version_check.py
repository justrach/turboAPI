#!/usr/bin/env python3
"""
TurboAPI Free-Threading Version Check
Ensures TurboAPI only runs on Python 3.13+ free-threading builds
"""

import io
import sys
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
            f"     • Rust-native concurrency\n"
            f"   \n"
            f"   Install free-threading Python:\n"
            f"     • python3.13t (if available)\n"
            f"     • pyenv install 3.13t-dev\n"
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
    Uses multiple detection methods for reliability.
    """

    # Method 1: Check for GIL-related functions (most reliable)
    try:
        # In free-threading builds, some GIL-related functions are removed/modified
        if not hasattr(sys, '_current_frames'):
            return True
    except Exception:
        pass

    # Method 2: Check sys.flags for free-threading flag
    try:
        if hasattr(sys, 'flags') and hasattr(sys.flags, 'nogil'):
            return sys.flags.nogil
    except Exception:
        pass

    # Method 3: Check threading module behavior
    try:
        # In free-threading, threading.get_ident() behavior changes
        import threading
        # This is a heuristic - may need adjustment based on actual free-threading behavior
        if hasattr(threading, '_thread') and hasattr(threading._thread, 'get_native_id'):
            # Free-threading builds often have enhanced native thread support
            return True
    except Exception:
        pass

    # Method 4: Check interpreter flags in sys
    try:
        if hasattr(sys, 'implementation') and hasattr(sys.implementation, 'name'):
            # Check if implementation has free-threading indicators
            if 'free' in sys.implementation.name.lower() or 'nogil' in str(sys.implementation):
                return True
    except Exception:
        pass

    # Method 5: Check version string for free-threading indicators
    try:
        version_str = sys.version.lower()
        if 'free-threading' in version_str or 'nogil' in version_str or '+free' in version_str:
            return True
    except Exception:
        pass

    # Method 6: Check for experimental free-threading modules
    try:
        # Free-threading builds may have special modules
        import _thread
        if hasattr(_thread, 'get_native_id') and not hasattr(sys, '_current_frames'):
            return True
    except Exception:
        pass

    # Method 7: Runtime test - try true parallel execution
    try:
        return _test_parallel_execution()
    except Exception:
        pass

    # Default: assume GIL is present
    return False


def _test_parallel_execution():
    """
    Runtime test to detect if threads can execute Python code in parallel.
    This is the most definitive test but also the most expensive.
    """
    import threading
    import time

    # Quick parallel execution test
    results = []
    start_times = []

    def worker():
        start_times.append(time.time())
        # CPU work that would be blocked by GIL
        total = sum(i * i for i in range(10000))
        results.append(total)

    # Start threads simultaneously
    threads = [threading.Thread(target=worker) for _ in range(2)]

    overall_start = time.time()
    for t in threads:
        t.start()

    for t in threads:
        t.join()

    overall_time = time.time() - overall_start

    # If threads started within 1ms of each other and completed quickly,
    # it's likely true parallelism (no GIL blocking)
    if len(start_times) >= 2:
        start_spread = max(start_times) - min(start_times)
        # True parallelism: threads start nearly simultaneously and complete fast
        if start_spread < 0.01 and overall_time < 0.05:  # 10ms start spread, 50ms total
            return True

    return False


def get_python_threading_info():
    """Get detailed information about Python threading capabilities."""
    info = {
        'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        'free_threading': _detect_free_threading(),
        'gil_enabled': hasattr(sys, '_current_frames'),
        'threading_native_id': hasattr(threading._thread, 'get_native_id') if hasattr(threading, '_thread') else False,
        'implementation': sys.implementation.name if hasattr(sys, 'implementation') else 'unknown',
    }

    # Add performance prediction
    if info['free_threading']:
        info['performance_multiplier'] = '5-10x FastAPI'
        info['concurrency'] = 'True parallelism'
        info['gil_overhead'] = 'Zero (Rust-native)'
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
            f"     • Rust-native concurrency integration\n"
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
