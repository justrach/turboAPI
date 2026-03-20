"""
Per-thread asyncio event loop management for Python 3.13+ free-threading.

This module provides thread-local event loop management to enable true
parallel execution of async handlers across multiple threads.
"""

import asyncio
import sys
import threading


class EventLoopPool:
    """
    Manages per-thread asyncio event loops for parallel async execution.

    In Python 3.13+ with free-threading, we can run multiple event loops
    in parallel across different threads without GIL contention.
    """

    _loops: dict[int, asyncio.AbstractEventLoop] = {}
    _lock = threading.Lock()
    _initialized = False

    @classmethod
    def initialize(cls, num_threads: int | None = None) -> None:
        """
        Initialize the event loop pool with the specified number of threads.

        Args:
            num_threads: Number of threads to create event loops for.
                        If None, uses number of CPU cores.
        """
        if cls._initialized:
            return

        with cls._lock:
            if cls._initialized:
                return

            if num_threads is None:
                import os

                num_threads = os.cpu_count() or 4

            print(f"🔄 Initializing EventLoopPool with {num_threads} threads")
            cls._initialized = True

    @classmethod
    def get_running_loop(cls) -> asyncio.AbstractEventLoop | None:
        """
        Get the running event loop for the current thread, if any.

        Returns:
            The running event loop, or None if no loop is running.
        """
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None


# Python 3.13+ free-threading detection
def is_free_threading_enabled() -> bool:
    """Check if Python 3.13+ free-threading is enabled."""
    return hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()


# Initialize on import
if is_free_threading_enabled():
    print("🚀 Python 3.13+ free-threading detected - enabling parallel event loops!")
    EventLoopPool.initialize()
else:
    print("⚠️  Free-threading not enabled - async performance may be limited")
