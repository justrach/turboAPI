"""Background tasks support for TurboAPI.

FastAPI-compatible BackgroundTasks class that runs functions after the response is sent.
"""

import asyncio
import inspect
from typing import Any, Callable


class BackgroundTasks:
    """A collection of background tasks to run after the response is sent.

    Usage:
        @app.post("/send-notification")
        async def send_notification(background_tasks: BackgroundTasks):
            background_tasks.add_task(send_email, "user@example.com", message="Hello")
            return {"message": "Notification sent in the background"}
    """

    def __init__(self):
        self._tasks: list[tuple[Callable, tuple, dict]] = []

    @property
    def tasks(self) -> list[tuple[Callable, tuple, dict]]:
        """Return the list of tasks (FastAPI compatibility)."""
        return self._tasks

    def add_task(self, func: Callable, *args: Any, **kwargs: Any) -> None:
        """Add a task to be run in the background after the response is sent."""
        self._tasks.append((func, args, kwargs))

    async def __call__(self) -> None:
        """Execute all background tasks."""
        for func, args, kwargs in self._tasks:
            if inspect.iscoroutinefunction(func):
                await func(*args, **kwargs)
            else:
                func(*args, **kwargs)

    def run_tasks(self) -> None:
        """Run all tasks synchronously or in an event loop."""
        for func, args, kwargs in self._tasks:
            if inspect.iscoroutinefunction(func):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(func(*args, **kwargs))
                except RuntimeError:
                    asyncio.run(func(*args, **kwargs))
            else:
                func(*args, **kwargs)
