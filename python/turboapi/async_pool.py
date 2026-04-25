"""
Per-thread asyncio event loop management for Python 3.13+ free-threading.

This module provides thread-local event loop management to enable true
parallel execution of async handlers across multiple threads.
"""

import asyncio
import json
import sys
import threading
from asyncio import events as _asyncio_events

from .exceptions import HTTPException
from .responses import Response

_dumps = json.dumps
_set_running_loop = getattr(_asyncio_events, "_set_running_loop", None)
_thread_local = threading.local()


def _set_thread_loop(loop: asyncio.AbstractEventLoop) -> asyncio.AbstractEventLoop:
    _thread_local.loop = loop
    _thread_local.run_until_complete = loop.run_until_complete
    return loop


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

            cls._initialized = True

    @classmethod
    def get_loop_for_thread(cls) -> asyncio.AbstractEventLoop:
        """
        Get or create an event loop for the current thread.

        Returns:
            The event loop for the current thread.
        """
        thread_id = threading.get_ident()

        # Fast path: loop already exists
        if thread_id in cls._loops:
            loop = cls._loops[thread_id]
            return _set_thread_loop(loop)

        # Slow path: create new loop
        with cls._lock:
            # Double-check after acquiring lock
            if thread_id in cls._loops:
                loop = cls._loops[thread_id]
                return _set_thread_loop(loop)

            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            cls._loops[thread_id] = loop
            return _set_thread_loop(loop)

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

    @classmethod
    def cleanup(cls) -> None:
        """Clean up all event loops (call on shutdown)."""
        with cls._lock:
            for thread_id, loop in cls._loops.items():
                if loop.is_running():
                    loop.stop()
                loop.close()
            cls._loops.clear()
            cls._initialized = False

    @classmethod
    def stats(cls) -> dict[str, int]:
        """Get statistics about the event loop pool."""
        with cls._lock:
            return {
                "total_loops": len(cls._loops),
                "active_threads": len([loop for loop in cls._loops.values() if loop.is_running()]),
            }


def ensure_event_loop() -> asyncio.AbstractEventLoop:
    """
    Ensure an event loop exists for the current thread.

    This is the primary function to call from Zig to get an event loop.

    Returns:
        The event loop for the current thread.
    """
    loop = getattr(_thread_local, "loop", None)
    if loop is not None and not loop.is_closed():
        return loop

    # Get or create thread-local loop
    return EventLoopPool.get_loop_for_thread()


def run_coroutine(coro):
    """Run a coroutine on the current worker thread's reusable event loop."""
    loop = ensure_event_loop()
    runner = getattr(_thread_local, "run_until_complete", None)
    if runner is None:
        runner = loop.run_until_complete
        _thread_local.run_until_complete = runner
    return runner(coro)


def _normalize_response_tuple(result):
    if isinstance(result, Response):
        body = result.body if isinstance(result.body, bytes) else result.body.encode("utf-8")
        return (result.status_code, result.media_type or "application/json", body)
    if hasattr(result, "model_dump"):
        result = result.model_dump()
    if isinstance(result, tuple) and len(result) == 2:
        return (result[1], "application/json", _dumps(result[0]))
    return (200, "application/json", _dumps(result))


def _exception_response_tuple(exc):
    if isinstance(exc, HTTPException):
        return (exc.status_code, "application/json", _dumps({"detail": exc.detail}))
    return (500, "application/json", _dumps({"error": str(exc)}))


def run_coroutine_response(coro):
    """Run a coroutine and normalize its result to TurboAPI's tuple response ABI."""
    loop = ensure_event_loop()
    runner = getattr(_thread_local, "run_until_complete", None)
    if runner is None:
        runner = loop.run_until_complete
        _thread_local.run_until_complete = runner
    try:
        return _normalize_response_tuple(runner(coro))
    except Exception as exc:
        return _exception_response_tuple(exc)


def run_coroutine_response_eager(coro):
    """Run a no-await coroutine without paying the event-loop scheduler cost."""
    loop = ensure_event_loop()
    try:
        if _set_running_loop is not None:
            _set_running_loop(loop)
        try:
            coro.send(None)
        except StopIteration as done:
            return _normalize_response_tuple(done.value)

        coro.close()
        return _exception_response_tuple(RuntimeError("eager async handler yielded unexpectedly"))
    except Exception as exc:
        return _exception_response_tuple(exc)
    finally:
        if _set_running_loop is not None:
            _set_running_loop(None)


# Python 3.13+ free-threading detection
def is_free_threading_enabled() -> bool:
    """Check if Python 3.13+ free-threading is enabled."""
    return hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()


# Initialize on import
if is_free_threading_enabled():
    EventLoopPool.initialize()
