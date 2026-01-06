"""
Integration benchmarks testing full Fromager workflows.
These benchmarks use a local PyPI server for network isolation.

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

if TYPE_CHECKING:
    from fixtures.pypi_server import LocalPyPI


def _download_and_add_to_local_pypi(
    requirement: str, local_pypi: LocalPyPI, tmp_path: pathlib.Path
) -> None:
    """Download a package from PyPI and add it to the local server.
    
    Downloads the package to a temp directory, then uses the server's
    add_package() method to place it in the correct PEP 503 structure.
    """
    # Parse package name from requirement
    from packaging.requirements import Requirement
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
def work_context(tmp_path: pathlib.Path, local_pypi: LocalPyPI):
    """Create a WorkContext configured for benchmarking."""
    from fromager import context

    # Create required directories
    patches_dir = tmp_path / "patches"
    patches_dir.mkdir(exist_ok=True)
    sdists_repo = tmp_path / "sdists-repo"
    sdists_repo.mkdir(exist_ok=True)
    wheels_repo = tmp_path / "wheels-repo"
    wheels_repo.mkdir(exist_ok=True)
    work_dir = tmp_path / "work-dir"
    work_dir.mkdir(exist_ok=True)

    ctx = context.WorkContext(
        active_settings=None,
        constraints_file=None,
        patches_dir=patches_dir,
        sdists_repo=sdists_repo,
        wheels_repo=wheels_repo,
        work_dir=work_dir,
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

    This tests Fromager's version resolution workflow:
    1. Query the PyPI server for package metadata
    2. Parse version specifiers
    3. Select the best matching version

    Uses the `packaging` package - it's pure Python and fast to download.
    """
    from packaging.requirements import Requirement

    from fromager import resolver

    # Setup: download package to local PyPI (not part of benchmark)
    download_tmp = work_context.work_dir / "downloads"
    download_tmp.mkdir(exist_ok=True)
    _download_and_add_to_local_pypi("packaging==24.2", local_pypi, download_tmp)

    req = Requirement("packaging>=24.0")

    def resolve_version():
        # Clear cache to get cold performance
        resolver.match_py_req.cache_clear()
        # Use Fromager's resolver directly against local PyPI
        return resolver.resolve(
            ctx=work_context,
            req=req,
            sdist_server_url=local_pypi.url,
            include_sdists=True,
            include_wheels=True,
        )

    result = benchmark(resolve_version)

    # Verify resolution produced a result
    assert result is not None
    source_url, version = result
    assert str(version) == "24.2"


@pytest.mark.integration
def test_bootstrapper_resolve_and_add_top_level(
    benchmark: Any,
    work_context,
    local_pypi: LocalPyPI,
) -> None:
    """Benchmark Bootstrapper.resolve_and_add_top_level().

    This tests the pre-resolution phase of bootstrap:
    1. Resolve package version from PyPI
    2. Add to dependency graph as top-level requirement

    Uses actual Fromager Bootstrapper API.
    """
    from packaging.requirements import Requirement

    from fromager import bootstrapper

    # Setup: download package to local PyPI (not part of benchmark)
    # Note: We need tmp_path but work_context uses it - create our own download dir
    download_tmp = work_context.work_dir / "downloads"
    download_tmp.mkdir(exist_ok=True)
    _download_and_add_to_local_pypi("packaging==24.2", local_pypi, download_tmp)

    req = Requirement("packaging>=24.0")

    def resolve_and_add():
        # Create fresh bootstrapper for each iteration
        bt = bootstrapper.Bootstrapper(
            ctx=work_context,
            progressbar=None,
            prev_graph=None,
            cache_wheel_server_url=None,
            sdist_only=True,
            test_mode=False,
        )
        return bt.resolve_and_add_top_level(req)

    result = benchmark(resolve_and_add)

    # Verify resolution succeeded (version may vary if fallback to PyPI)
    assert result is not None
    source_url, version = result
    # The version should satisfy our requirement (>=24.0)
    from packaging.version import Version
    assert Version(str(version)) >= Version("24.0")
