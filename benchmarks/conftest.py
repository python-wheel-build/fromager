"""Shared fixtures for Fromager benchmarks."""

import pytest

# Import fixtures from the fixtures module using relative imports
from fixtures import (
    LocalPyPI,
    SubprocessTimer,
    configured_env,
    local_pypi,
    subprocess_timer,
    uv_shim,
    with_uv_shim,
)

# Re-export fixtures for pytest discovery
__all__ = [
    "LocalPyPI",
    "SubprocessTimer",
    "configured_env",
    "local_pypi",
    "subprocess_timer",
    "uv_shim",
    "with_uv_shim",
]


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line(
        "markers", "integration: marks tests as integration benchmarks (run nightly)"
    )
    config.addinivalue_line(
        "markers", "memory: marks tests for memory profiling (requires pytest-memray)"
    )


@pytest.fixture
def sample_requirements() -> list[str]:
    """Sample requirement strings for resolution benchmarks."""
    return [
        "requests>=2.28.0",
        "packaging>=23.0",
        "pydantic>=2.0",
    ]
