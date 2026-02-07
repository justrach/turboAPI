"""Thread-safe in-memory queue for TurboAPI.

Drop-in replacement for asyncio.Queue that works from Tokio worker threads.
Uses threading.Condition + collections.deque for true thread safety,
including Python 3.13+ free-threading (no GIL dependency).

Usage:
    from turboapi import Queue, QueueEmpty, QueueFull

    task_queue = Queue(maxsize=100)

    @app.post("/enqueue")
    def enqueue(data: dict):
        task_queue.put(data)
        return {"queued": task_queue.qsize()}

    @app.get("/dequeue")
    def dequeue():
        try:
            item = task_queue.get(timeout=5.0)
            return {"item": item}
        except QueueEmpty:
            return {"error": "timeout"}, 408
"""

import threading
import time
from collections import deque
from typing import Any, Optional


class QueueEmpty(Exception):
    """Raised when get_nowait() is called on an empty queue."""
    pass


class QueueFull(Exception):
    """Raised when put_nowait() is called on a full queue."""
    pass


class Queue:
    """Thread-safe FIFO queue for TurboAPI handlers.

    Works from both sync and async TurboAPI handlers without requiring
    an asyncio event loop. Safe for Python 3.13+ free-threading.

    Args:
        maxsize: Maximum number of items. 0 means unlimited (default).
    """

    def __init__(self, maxsize: int = 0):
        self.maxsize: int = maxsize
        self._queue: deque = deque()
        self._mutex: threading.Lock = threading.Lock()
        self._not_empty: threading.Condition = threading.Condition(self._mutex)
        self._not_full: threading.Condition = threading.Condition(self._mutex)
        self._unfinished_tasks: int = 0
        self._all_done: threading.Condition = threading.Condition(self._mutex)

    def put(self, item: Any, block: bool = True, timeout: Optional[float] = None) -> None:
        """Put an item into the queue.

        Args:
            item: The item to enqueue.
            block: Whether to block if the queue is full.
            timeout: Maximum seconds to wait (None = wait forever).

        Raises:
            QueueFull: If the queue is full and block=False or timeout expires.
        """
        with self._not_full:
            if self.maxsize > 0:
                if not block:
                    if len(self._queue) >= self.maxsize:
                        raise QueueFull()
                elif timeout is not None:
                    if timeout < 0:
                        raise ValueError("'timeout' must be a non-negative number")
                    deadline = time.monotonic() + timeout
                    while len(self._queue) >= self.maxsize:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise QueueFull()
                        self._not_full.wait(timeout=remaining)
                else:
                    while len(self._queue) >= self.maxsize:
                        self._not_full.wait()

            self._queue.append(item)
            self._unfinished_tasks += 1
            self._not_empty.notify()

    def get(self, block: bool = True, timeout: Optional[float] = None) -> Any:
        """Remove and return an item from the queue.

        Args:
            block: Whether to block if the queue is empty.
            timeout: Maximum seconds to wait (None = wait forever).

        Returns:
            The next item from the queue.

        Raises:
            QueueEmpty: If the queue is empty and block=False or timeout expires.
        """
        with self._not_empty:
            if not block:
                if not self._queue:
                    raise QueueEmpty()
            elif timeout is not None:
                if timeout < 0:
                    raise ValueError("'timeout' must be a non-negative number")
                deadline = time.monotonic() + timeout
                while not self._queue:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise QueueEmpty()
                    self._not_empty.wait(timeout=remaining)
            else:
                while not self._queue:
                    self._not_empty.wait()

            item = self._queue.popleft()
            self._not_full.notify()
            return item

    def put_nowait(self, item: Any) -> None:
        """Put an item without blocking. Raises QueueFull if full."""
        return self.put(item, block=False)

    def get_nowait(self) -> Any:
        """Get an item without blocking. Raises QueueEmpty if empty."""
        return self.get(block=False)

    def qsize(self) -> int:
        """Return the approximate number of items in the queue."""
        with self._mutex:
            return len(self._queue)

    def empty(self) -> bool:
        """Return True if the queue is empty."""
        with self._mutex:
            return len(self._queue) == 0

    def full(self) -> bool:
        """Return True if the queue is full (always False if maxsize=0)."""
        with self._mutex:
            if self.maxsize <= 0:
                return False
            return len(self._queue) >= self.maxsize

    def task_done(self) -> None:
        """Signal that a previously enqueued task is complete.

        Raises:
            ValueError: If called more times than items placed in the queue.
        """
        with self._all_done:
            if self._unfinished_tasks <= 0:
                raise ValueError("task_done() called too many times")
            self._unfinished_tasks -= 1
            if self._unfinished_tasks == 0:
                self._all_done.notify_all()

    def join(self, timeout: Optional[float] = None) -> None:
        """Block until all items have been gotten and processed.

        Args:
            timeout: Maximum seconds to wait (None = wait forever).
        """
        with self._all_done:
            if timeout is not None:
                deadline = time.monotonic() + timeout
                while self._unfinished_tasks > 0:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return
                    self._all_done.wait(timeout=remaining)
            else:
                while self._unfinished_tasks > 0:
                    self._all_done.wait()
