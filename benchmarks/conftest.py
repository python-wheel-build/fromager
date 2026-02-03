"""Benchmark configuration and fixtures."""

import pytest

from fixtures.pypi_server import local_pypi  # noqa: F401


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line(
        "markers", "integration: marks tests as integration benchmarks"
    )
