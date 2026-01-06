"""Local PyPI server fixture for benchmark isolation."""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
    from pytest import TempPathFactory


@dataclass
class LocalPyPI:
    """Local PyPI server handle."""

    url: str
    process: subprocess.Popen  # type: ignore[type-arg]
    packages_dir: Path


@pytest.fixture(scope="session")
def local_pypi(tmp_path_factory: "TempPathFactory") -> LocalPyPI:
    """Spawn a local pypiserver instance for benchmark isolation.

    This fixture creates a local PyPI server that serves packages from a
    temporary directory, enabling network isolation for benchmarks.

    The server runs for the entire test session and is automatically
    cleaned up when the session ends.
    """
    packages_dir = tmp_path_factory.mktemp("packages")

    # Download packages if requirements file exists
    req_file = Path(__file__).parent.parent / "requirements" / "packages.txt"
    if req_file.exists():
        subprocess.run(
            ["uv", "pip", "download", "-r", str(req_file), "-d", str(packages_dir)],
            check=True,
            capture_output=True,
        )

    port = 18080
    proc = subprocess.Popen(
        ["pypi-server", "run", "-p", str(port), str(packages_dir)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for server startup
    time.sleep(1.0)

    yield LocalPyPI(
        url=f"http://localhost:{port}/simple",
        process=proc,
        packages_dir=packages_dir,
    )

    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def configured_env(local_pypi: LocalPyPI, monkeypatch: "MonkeyPatch") -> LocalPyPI:
    """Configure environment to use local PyPI.

    Sets UV_INDEX_URL and PIP_INDEX_URL environment variables to point
    to the local PyPI server, ensuring package resolution uses the
    isolated server.
    """
    monkeypatch.setenv("UV_INDEX_URL", local_pypi.url)
    monkeypatch.setenv("PIP_INDEX_URL", local_pypi.url)
    monkeypatch.setenv("UV_NO_PROGRESS", "1")
    return local_pypi
