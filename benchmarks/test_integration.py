"""
Integration benchmarks testing full Fromager workflows.

These benchmarks use a local PyPI server for network isolation and measure
end-to-end operations that involve I/O, network, and system calls.

They use CodSpeed's walltime mode on Macro Runners for accurate real-world
measurements.

To run locally:
    hatch run benchmark:run -m "integration"

To skip integration tests:
    hatch run benchmark:run -m "not integration"
"""

from __future__ import annotations

import pathlib
import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from packaging.requirements import Requirement

from fromager import context, resolver

if TYPE_CHECKING:
    from fixtures.pypi_server import LocalPyPI


def _download_and_add_to_local_pypi(
    requirement: str, local_pypi: LocalPyPI, tmp_path: pathlib.Path
) -> None:
    """Download a package from PyPI and add it to the local server.

    Downloads the package to a temp directory, then uses the server's
    add_package() method to place it in the correct PEP 503 structure.
    """
    req = Requirement(requirement)
    package_name = req.name

    # Download to temp directory
    download_dir = tmp_path / "downloads"
    download_dir.mkdir(exist_ok=True)

    subprocess.run(
        ["pip", "download", "--no-deps", "-d", str(download_dir), requirement],
        check=True,
        capture_output=True,
    )

    # Find the downloaded file and add it to the local PyPI
    for file in download_dir.iterdir():
        if file.suffix in (".whl", ".gz"):
            local_pypi.add_package(package_name, file)
            break


@pytest.fixture
def work_context(tmp_path: pathlib.Path, local_pypi: LocalPyPI) -> context.WorkContext:
    """Create a WorkContext configured for benchmarking."""
    ctx = context.WorkContext(
        active_settings=None,
        constraints_file=None,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        variant="cpu",
    )
    ctx.setup()

    # Configure to use local PyPI
    ctx.sdist_server_url = local_pypi.url

    return ctx


@pytest.mark.integration
def test_resolve_version_from_local_pypi(
    benchmark: Any,
    work_context,
    local_pypi: LocalPyPI,
) -> None:
    """Benchmark version resolution against a local PyPI server.

    This is a critical hot path - version resolution is the core operation
    Fromager performs. Measures:
    1. Query the PyPI server for package metadata
    2. Parse version specifiers and HTML responses
    3. Select the best matching version

    Uses benchmark.pedantic() to ensure cache is cleared before each iteration,
    measuring the actual algorithm performance rather than cache hits.
    """
    # Setup: download package to local PyPI (not part of benchmark)
    download_tmp = work_context.work_dir / "downloads"
    download_tmp.mkdir(exist_ok=True)
    _download_and_add_to_local_pypi("packaging==24.2", local_pypi, download_tmp)

    req = Requirement("packaging>=24.0")

    def setup_iteration():
        """Clear resolver cache before each iteration (not measured)."""
        resolver.match_py_req.cache_clear()
        return (), {}  # args, kwargs for run_resolve

    def run_resolve():
        """The actual operation being benchmarked."""
        return resolver.resolve(
            ctx=work_context,
            req=req,
            sdist_server_url=local_pypi.url,
            include_sdists=True,
            include_wheels=True,
        )

    # Use pedantic mode: setup runs before each iteration but isn't timed
    result = benchmark.pedantic(
        run_resolve,
        setup=setup_iteration,
        rounds=20,  # Fewer rounds since cold resolution is slower
        iterations=1,  # One iteration per round (cold cache each time)
    )

    # Verify resolution produced a result
    assert result is not None
    _source_url, version = result
    assert str(version) == "24.2"
