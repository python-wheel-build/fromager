import threading
import time

import pytest

from fromager.threading_utils import with_thread_lock


def test_decorated_function_returns_value() -> None:
    @with_thread_lock()
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5
    assert add(a=10, b=20) == 30


def test_mutual_exclusion() -> None:
    events: list[str] = []
    ready = threading.Barrier(2)

    @with_thread_lock()
    def slow() -> None:
        events.append("enter")
        time.sleep(0.05)
        events.append("exit")

    def worker() -> None:
        ready.wait()  # ensure both threads race for the lock
        slow()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert events == ["enter", "exit", "enter", "exit"]


def test_independent_locks_do_not_block_each_other() -> None:
    barrier = threading.Barrier(2)

    @with_thread_lock()
    def func_a() -> None:
        barrier.wait(timeout=2)

    @with_thread_lock()
    def func_b() -> None:
        barrier.wait(timeout=2)

    t1 = threading.Thread(target=func_a)
    t2 = threading.Thread(target=func_b)
    t1.start()
    t2.start()
    t1.join(timeout=3)
    t2.join(timeout=3)

    assert not t1.is_alive()
    assert not t2.is_alive()


def test_lock_released_after_exception() -> None:
    call_count = 0

    @with_thread_lock()
    def throws_on_first_call() -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("first call exception")
        return "ok"

    with pytest.raises(ValueError, match="first call exception"):
        throws_on_first_call()

    assert throws_on_first_call() == "ok"


def test_nested_call_to_different_decorated_function() -> None:
    @with_thread_lock()
    def inner() -> str:
        return "ok"

    @with_thread_lock()
    def outer() -> str:
        result: str = inner()
        return result

    assert outer() == "ok"
