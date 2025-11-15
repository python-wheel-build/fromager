import textwrap
from unittest.mock import Mock, patch

from packaging.requirements import Requirement
from packaging.version import Version

from fromager import build_environment
from fromager.context import WorkContext
from fromager.requirements_file import RequirementType


@patch("fromager.resolver.resolve")
def test_missing_dependency_format(
    resolve_dist: Mock,
    tmp_context: WorkContext,
) -> None:
    resolutions = {
        "flit_core": "3.9.0",
        "setuptools": "69.5.1",
    }
    resolve_dist.side_effect = lambda ctx, req, sdist_server_url, req_type: (
        "",
        Version(resolutions[req.name]),
    )

    req = Requirement("setuptools>=40.8.0")
    other_reqs = [
        Requirement("flit_core"),
        req,
    ]
    ex = build_environment.MissingDependency(
        tmp_context, RequirementType.BUILD_BACKEND, req, other_reqs
    )
    s = str(ex)
    # Ensure we report the thing we're actually missing
    assert "Failed to install build-backend dependency setuptools>=40.8.0. " in s
    # Ensure we report what version we expected of that thing
    assert "setuptools>=40.8.0 -> 69.5.1" in s
    # Ensure we report what version we expect of all of the other dependencies
    assert "flit_core -> 3.9.0" in s


def test_missing_dependency_pattern() -> None:
    msg = textwrap.dedent("""
        DEBUG uv 0.8.4
        DEBUG Searching for default Python interpreter in virtual environments
        DEBUG Found `cpython-3.13.5-linux-x86_64-gnu` at `.../.venv/bin/python3` (active virtual environment)
        DEBUG Using Python 3.13.5 environment at: .venv
        DEBUG Acquired lock for `.venv`
        DEBUG At least one requirement is not satisfied: fromager==1.0
        DEBUG Using request timeout of 30s
        DEBUG Solving with installed Python version: 3.13.5
        DEBUG Solving with target Python version: >=3.13.5
        DEBUG Adding direct dependency: fromager>=1.0, <1.0+
        DEBUG Found fresh response for: https://pypi.org/simple/fromager/
        DEBUG Searching for a compatible version of fromager (>=1.0, <1.0+)
        DEBUG No compatible version found for: fromager
        x No solution found when resolving dependencies:
        ╰─▶ Because there is no version of fromager==1.0 and you require fromager==1.0, we can conclude that your requirements are unsatisfiable.
        """)
    match = build_environment._uv_missing_dependency_pattern.search(msg)
    assert match is not None


def test_missing_dependency_pattern_resolution_impossible() -> None:
    msg = textwrap.dedent("""
        DEBUG uv 0.8.4
        DEBUG Searching for default Python interpreter in virtual environments
        DEBUG Found `cpython-3.13.5-linux-x86_64-gnu` at `.../.venv/bin/python3` (active virtual environment)
        DEBUG Using Python 3.13.5 environment at: .venv
        DEBUG Acquired lock for `.venv`
        DEBUG At least one requirement is not satisfied: fromager==2.0
        DEBUG Using request timeout of 30s
        DEBUG Solving with installed Python version: 3.13.5
        DEBUG Solving with target Python version: >=3.13.5
        DEBUG Adding direct dependency: fromager>=1.0, <1.0+
        DEBUG Adding direct dependency: fromager>=2.0, <2.0+
        DEBUG Found fresh response for: https://pypi.org/simple/fromager/
        x No solution found when resolving dependencies:
        ╰─▶ Because you require fromager==1.0 and fromager==2.0, we can conclude that your requirements are unsatisfiable.
    """)
    match = build_environment._uv_missing_dependency_pattern.search(msg)
    assert match is not None
