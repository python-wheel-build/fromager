"""Custom metrics collectors for benchmark instrumentation."""

import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator
from unittest import mock

import pytest


@dataclass
class SubprocessMetrics:
    """Container for subprocess timing data."""

    times: list[float] = field(default_factory=list)
    call_count: int = 0
    _total_wall_time: float = 0.0

    @property
    def total_time(self) -> float:
        """Total time spent in subprocesses."""
        return sum(self.times)

    @property
    def overhead_ratio(self) -> float:
        """Ratio of non-subprocess time to total wall time.

        A value of 0.5 means half the time was spent outside subprocesses.
        Useful for understanding where time is being spent in benchmarks.
        """
        if self._total_wall_time == 0:
            return 0.0
        return (self._total_wall_time - self.total_time) / self._total_wall_time


class SubprocessTimer:
    """Context manager to measure subprocess overhead.

    This class patches subprocess.run to measure the time spent in
    subprocess calls, allowing benchmarks to distinguish between
    code execution time and subprocess overhead.

    Example:
        timer = SubprocessTimer()
        with timer.measure():
            # Code that calls subprocess.run
            subprocess.run(["echo", "hello"])

        print(f"Subprocess time: {timer.total_time}")
        print(f"Call count: {timer.call_count}")
    """

    def __init__(self) -> None:
        self.metrics = SubprocessMetrics()

    @contextmanager
    def measure(self) -> Generator[None, None, None]:
        """Patch subprocess.run to measure time in subprocesses."""
        original_run = subprocess.run

        def instrumented_run(
            *args: object, **kwargs: object
        ) -> subprocess.CompletedProcess[object]:
            start = time.perf_counter()
            result = original_run(*args, **kwargs)  # type: ignore[arg-type]
            elapsed = time.perf_counter() - start

            self.metrics.times.append(elapsed)
            self.metrics.call_count += 1
            return result

        wall_start = time.perf_counter()
        with mock.patch("subprocess.run", side_effect=instrumented_run):
            yield
        self.metrics._total_wall_time = time.perf_counter() - wall_start

    @property
    def total_time(self) -> float:
        """Total time spent in subprocesses."""
        return self.metrics.total_time

    @property
    def call_count(self) -> int:
        """Number of subprocess.run calls."""
        return self.metrics.call_count

    @property
    def overhead_ratio(self) -> float:
        """Ratio of non-subprocess time to total wall time."""
        return self.metrics.overhead_ratio


@pytest.fixture
def subprocess_timer() -> SubprocessTimer:
    """Provide a fresh SubprocessTimer for each test.

    Use this fixture to measure subprocess overhead in benchmarks:

        def test_my_benchmark(benchmark, subprocess_timer):
            with subprocess_timer.measure():
                benchmark(my_function_that_calls_subprocesses)

            print(f"Subprocess calls: {subprocess_timer.call_count}")
    """
    return SubprocessTimer()
