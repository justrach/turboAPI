"""
Per-thread asyncio event loop management for Python 3.13+ free-threading.

This module provides thread-local event loop management to enable true
parallel execution of async handlers across multiple threads.
"""

import asyncio
import threading
from typing import Dict, Optional
import sys


class EventLoopPool:
    """
    Manages per-thread asyncio event loops for parallel async execution.
    
    In Python 3.13+ with free-threading, we can run multiple event loops
    in parallel across different threads without GIL contention.
    """
    
    _loops: Dict[int, asyncio.AbstractEventLoop] = {}
    _lock = threading.Lock()
    _initialized = False
    
    @classmethod
    def initialize(cls, num_threads: Optional[int] = None) -> None:
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
    def get_loop_for_thread(cls) -> asyncio.AbstractEventLoop:
        """
        Get or create an event loop for the current thread.
        
        Returns:
            The event loop for the current thread.
        """
        thread_id = threading.get_ident()
        
        # Fast path: loop already exists
        if thread_id in cls._loops:
            return cls._loops[thread_id]
        
        # Slow path: create new loop
        with cls._lock:
            # Double-check after acquiring lock
            if thread_id in cls._loops:
                return cls._loops[thread_id]
            
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            cls._loops[thread_id] = loop
            
            print(f"✅ Created event loop for thread {thread_id}")
            return loop
    
    @classmethod
    def get_running_loop(cls) -> Optional[asyncio.AbstractEventLoop]:
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
    def stats(cls) -> Dict[str, int]:
        """Get statistics about the event loop pool."""
        with cls._lock:
            return {
                "total_loops": len(cls._loops),
                "active_threads": len([l for l in cls._loops.values() if l.is_running()]),
            }


def ensure_event_loop() -> asyncio.AbstractEventLoop:
    """
    Ensure an event loop exists for the current thread.
    
    This is the primary function to call from Rust to get an event loop.
    
    Returns:
        The event loop for the current thread.
    """
    # Try to get running loop first (fast path)
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        pass
    
    # Get or create thread-local loop
    return EventLoopPool.get_loop_for_thread()


# Python 3.13+ free-threading detection
def is_free_threading_enabled() -> bool:
    """Check if Python 3.13+ free-threading is enabled."""
    return hasattr(sys, '_is_gil_enabled') and not sys._is_gil_enabled()


# Initialize on import
if is_free_threading_enabled():
    print("🚀 Python 3.13+ free-threading detected - enabling parallel event loops!")
    EventLoopPool.initialize()
else:
    print("⚠️  Free-threading not enabled - async performance may be limited")
