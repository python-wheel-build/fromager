"""Threading utilities for the fromager package."""

import functools
import os
import threading
import typing


def get_cpu_count() -> int:
    """CPU count from scheduler affinity"""
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    else:
        return os.cpu_count() or 1


def with_thread_lock() -> typing.Callable[[typing.Callable], typing.Callable]:
    """Decorator factory that creates a thread-safe wrapper for a function.

    Each decorated function gets its own lock instance, ensuring that different
    functions using this decorator don't block each other.

    Returns:
        A decorator that wraps the target function with thread-safe execution
    """
    lock = threading.Lock()

    def decorator(func: typing.Callable) -> typing.Callable:
        @functools.wraps(func)
        def wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
            with lock:
                return func(*args, **kwargs)

        return wrapper

    return decorator
