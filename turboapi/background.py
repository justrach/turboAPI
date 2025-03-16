"""
Background tasks module for TurboAPI.

This module provides functionality for running background tasks
after the response has been sent to the client.
"""

from typing import Any, Callable, List, Optional, Tuple
import asyncio


class BackgroundTasks:
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
        self.tasks: List[Tuple[Callable, Tuple[Any, ...], Dict[str, Any]]] = []

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
        self.tasks.append((func, args, kwargs))

    async def run_tasks(self) -> None:
        """Run all background tasks."""
        for func, args, kwargs in self.tasks:
            try:
                if asyncio.iscoroutinefunction(func):
                    await func(*args, **kwargs)
                else:
                    await asyncio.get_event_loop().run_in_executor(
                        None, func, *args, **kwargs
                    )
            except Exception as e:
                # Log the error but don't raise it to avoid affecting the response
                import logging
                logging.error(f"Error running background task {func.__name__}: {str(e)}") 