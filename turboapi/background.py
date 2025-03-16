"""
Background tasks module for TurboAPI.

This module provides functionality for running background tasks
after the response has been sent to the client.
"""

from typing import Any, Callable, List, Optional, Tuple, Dict
import asyncio

from starlette.background import BackgroundTask, BackgroundTasks as StarletteBackgroundTasks


class BackgroundTasks(StarletteBackgroundTasks):
    """
    BackgroundTasks allows you to define tasks to run in the background
    after returning a response.
    
    Example:
        ```python
        @app.post("/items/")
        async def create_item(background_tasks: BackgroundTasks):
            background_tasks.add_task(notify_admin, message="New item created")
            return {"message": "Item created"}
        ```
    """

    def __init__(self):
        """Initialize the background tasks list."""
        super().__init__()

    def add_task(
        self,
        func: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """
        Add a task to be run in the background.

        Args:
            func: The function to run in the background
            *args: Positional arguments to pass to the function
            **kwargs: Keyword arguments to pass to the function
        """
        super().add_task(func, *args, **kwargs)

    async def run_tasks(self) -> None:
        """Run all background tasks."""
        await super().__call__() 