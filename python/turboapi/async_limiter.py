"""
Async Limiter - Semaphore-based rate limiting for async tasks

Prevents event loop overload by limiting concurrent async tasks.
"""

import asyncio
from typing import Any, Coroutine


class AsyncLimiter:
    """Semaphore-based limiter for async tasks
    
    Limits the number of concurrent async tasks to prevent event loop overload.
    This is critical for maintaining stable performance under high load.
    
    Args:
        max_concurrent: Maximum number of concurrent tasks (default: 512)
    
    Example:
        limiter = AsyncLimiter(max_concurrent=512)
        result = await limiter(some_coroutine())
    """
    
    def __init__(self, max_concurrent: int = 512):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.max_concurrent = max_concurrent
        self._active_tasks = 0
    
    async def __call__(self, coro: Coroutine) -> Any:
        """Execute coroutine with semaphore gating
        
        Args:
            coro: Coroutine to execute
            
        Returns:
            Result of the coroutine
        """
        async with self.semaphore:
            self._active_tasks += 1
            try:
                return await coro
            finally:
                self._active_tasks -= 1
    
    @property
    def active_tasks(self) -> int:
        """Get current number of active tasks"""
        return self._active_tasks
    
    @property
    def available_slots(self) -> int:
        """Get number of available slots"""
        return self.max_concurrent - self._active_tasks


# Global limiter instance per event loop
_limiters = {}


def get_limiter(max_concurrent: int = 512) -> AsyncLimiter:
    """Get or create limiter for current event loop
    
    Args:
        max_concurrent: Maximum concurrent tasks
        
    Returns:
        AsyncLimiter instance for current event loop
    """
    try:
        loop = asyncio.get_running_loop()
        loop_id = id(loop)
        
        if loop_id not in _limiters:
            _limiters[loop_id] = AsyncLimiter(max_concurrent)
        
        return _limiters[loop_id]
    except RuntimeError:
        # No running loop, create standalone limiter
        return AsyncLimiter(max_concurrent)


def reset_limiters():
    """Reset all limiters (useful for testing)"""
    global _limiters
    _limiters = {}
