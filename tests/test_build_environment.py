import json
import pathlib
import subprocess
import textwrap
from unittest.mock import Mock, patch

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import build_environment
from fromager.context import WorkContext
from fromager.requirements_file import RequirementType


def test_install_keeps_earlier_explicit_bounds_across_phases(
    tmp_path: pathlib.Path,
) -> None:
    """A later transitive upgrade must still satisfy the first phase's cap."""
    ctx = Mock(pip_constraint_args=[], pip_wheel_server_args=[])
    with patch.object(build_environment.BuildEnvironment, "_createenv"):
        env = build_environment.BuildEnvironment(
            ctx=ctx, req=Requirement("pyarrow==15.0.2"), sdist_root_dir=tmp_path
        )
    with patch.object(env, "run") as run:
        env.install(iter([Requirement("setuptools<82")]))
        env.install(
            iter([Requirement("setuptools_scm<8"), Requirement("cython>=0.29")])
        )

    second_command = run.call_args_list[1].args[0]
    assert second_command[-3:] == [
        "setuptools<82",
        "setuptools_scm<8",
        "cython>=0.29",
    ]


def test_failed_later_install_reports_earlier_bounds(tmp_path: pathlib.Path) -> None:
    """A conflict report includes the bound from the first phase."""
    ctx = Mock(pip_constraint_args=[], pip_wheel_server_args=[])
    with patch.object(build_environment.BuildEnvironment, "_createenv"):
        env = build_environment.BuildEnvironment(
            ctx=ctx, req=Requirement("pyarrow"), sdist_root_dir=tmp_path
        )
    failure = subprocess.CalledProcessError(
        1, "uv pip install", output="Because you require setuptools>=82"
    )
    with (
        patch.object(env, "run", side_effect=[None, failure]),
        patch("fromager.resolver.resolve", return_value=("", Version("81"))),
    ):
        build_environment._safe_install(
            ctx,
            Requirement("pyarrow"),
            env,
            [Requirement("setuptools<82")],
            RequirementType.BUILD_SYSTEM,
        )
        with pytest.raises(build_environment.MissingDependency) as exc:
            build_environment._safe_install(
                ctx,
                Requirement("pyarrow"),
                env,
                [Requirement("setuptools>=82")],
                RequirementType.BUILD_BACKEND,
            )

    assert [str(req) for req in exc.value.all_reqs] == [
        "setuptools<82",
        "setuptools>=82",
    ]
    assert [str(req) for req in env._installed_requirements] == ["setuptools<82"]


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


def test_get_distributions_valid_json() -> None:
    """get_distributions returns a mapping of package names to versions."""
    env = Mock(spec=build_environment.BuildEnvironment)
    env.python = "/fake/python3"
    env.run.return_value = json.dumps({"setuptools": "69.5.1", "pip": "24.0"})

    result = build_environment.BuildEnvironment.get_distributions(env)

    assert result == {"pip": Version("24.0"), "setuptools": Version("69.5.1")}


def test_get_distributions_invalid_json_raises() -> None:
    """get_distributions raises on invalid JSON instead of UnboundLocalError."""
    env = Mock(spec=build_environment.BuildEnvironment)
    env.python = "/fake/python3"
    env.run.return_value = "not valid json"

    with pytest.raises(json.JSONDecodeError):
        build_environment.BuildEnvironment.get_distributions(env)
