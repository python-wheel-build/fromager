import functools
import itertools
import pathlib
import shutil
import textwrap
import typing
from unittest.mock import Mock, patch

import pytest
from packaging.metadata import Metadata
from packaging.requirements import Requirement
from packaging.utils import NormalizedName
from packaging.version import Version

from fromager import build_environment, context, dependencies

_fromager_root = pathlib.Path(__file__).parent.parent


@pytest.mark.parametrize(
    "build_system,expected_results",
    [
        # Empty
        ({}, dependencies._DEFAULT_BACKEND),
        # Only specify requirements (pyarrow)
        (
            {"requires": ["a-dep"]},
            {
                "build-backend": "setuptools.build_meta:__legacy__",
                "backend-path": None,
                "requires": ["a-dep"],
            },
        ),
        # Specify everything
        (
            {
                "build-backend": "setuptools.build_meta:__legacy__",
                "backend-path": None,
                "requires": ["a-dep"],
            },
            {
                "build-backend": "setuptools.build_meta:__legacy__",
                "backend-path": None,
                "requires": ["a-dep"],
            },
        ),
    ],
)
def test_get_build_backend(
    build_system: dict[str, list[str]] | dict[str, str | list[str] | None],
    expected_results: dict[str, typing.Any] | dict[str, str | list[str] | None],
) -> None:
    pyproject_toml = {"build-system": build_system}
    actual = dependencies.get_build_backend(pyproject_toml)
    assert expected_results == actual


def _clean_build_artifacts(f: typing.Callable[..., None]) -> typing.Callable[..., None]:
    @functools.wraps(f)
    def _with_cleanup(*args: typing.Any, **kwds: typing.Any) -> None:
        try:
            f(*args, **kwds)
        finally:
            for d in itertools.chain(
                _fromager_root.glob("fromager-*.dist-info"),
                _fromager_root.glob("fromager.egg-info"),
            ):
                shutil.rmtree(d)

    return _with_cleanup


@patch("fromager.dependencies._write_requirements_file")
@_clean_build_artifacts
def test_get_build_system_dependencies(
    _: Mock, tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    pyproject_file = _fromager_root / "pyproject.toml"
    shutil.copyfile(pyproject_file, tmp_path / "pyproject.toml")

    results = dependencies.get_build_system_dependencies(
        ctx=tmp_context,
        req=Requirement("fromager"),
        sdist_root_dir=tmp_path,
    )
    names = set(r.name for r in results)
    assert names == set(["hatchling", "hatch-vcs"])


def test_get_build_system_dependencies_cached(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    sdist_root_dir = tmp_path / "sdist"
    sdist_root_dir.mkdir()

    req_file = tmp_path / "build-system-requirements.txt"
    req_file.write_text("foo==1.0")
    results = dependencies.get_build_system_dependencies(
        ctx=tmp_context,
        req=Requirement("fromager"),
        sdist_root_dir=sdist_root_dir,
    )
    assert results == set([Requirement("foo==1.0")])


@patch("fromager.dependencies._write_requirements_file")
@_clean_build_artifacts
def test_get_build_backend_dependencies(
    _: Mock, tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    # We have to install the build system dependencies into the build
    # environment to get the build sdist dependencies, and we are not running
    # our own local wheel server, so use the public one.
    tmp_context.wheel_server_url = "https://pypi.org/simple"

    req = Requirement("fromager")
    build_env = build_environment.BuildEnvironment(
        ctx=tmp_context,
        parent_dir=tmp_path,
    )
    build_system_dependencies = dependencies.get_build_system_dependencies(
        ctx=tmp_context,
        req=req,
        sdist_root_dir=_fromager_root,
    )
    build_env.install(build_system_dependencies)

    results = dependencies.get_build_backend_dependencies(
        ctx=tmp_context,
        req=req,
        sdist_root_dir=_fromager_root,
        build_env=build_env,
    )
    names = set(r.name for r in results)
    assert names == set()


def test_get_build_backend_dependencies_cached(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    sdist_root_dir = tmp_path / "sdist"
    sdist_root_dir.mkdir()

    req_file = tmp_path / "build-backend-requirements.txt"
    req_file.write_text("foo==1.0")

    build_env = build_environment.BuildEnvironment(
        ctx=tmp_context,
        parent_dir=tmp_path,
    )
    results = dependencies.get_build_backend_dependencies(
        ctx=tmp_context,
        req=Requirement("fromager"),
        sdist_root_dir=sdist_root_dir,
        build_env=build_env,
    )
    assert results == set([Requirement("foo==1.0")])


@patch("fromager.dependencies._write_requirements_file")
@_clean_build_artifacts
def test_get_build_sdist_dependencies(
    _: Mock, tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    # We have to install the build system dependencies into the build
    # environment to get the build sdist dependencies, and we are not running
    # our own local wheel server, so use the public one.
    tmp_context.wheel_server_url = "https://pypi.org/simple"

    req = Requirement("fromager")
    build_env = build_environment.BuildEnvironment(
        ctx=tmp_context,
        parent_dir=tmp_path,
    )
    build_system_dependencies = dependencies.get_build_system_dependencies(
        ctx=tmp_context,
        req=req,
        sdist_root_dir=_fromager_root,
    )
    build_env.install(build_system_dependencies)

    results = dependencies.get_build_sdist_dependencies(
        ctx=tmp_context,
        req=req,
        sdist_root_dir=_fromager_root,
        build_env=build_env,
    )
    names = set(r.name for r in results)
    assert names == set()


def test_get_build_sdist_dependencies_cached(
    tmp_context: context.WorkContext, tmp_path: pathlib.Path
) -> None:
    sdist_root_dir = tmp_path / "sdist"
    sdist_root_dir.mkdir()

    req_file = tmp_path / "build-sdist-requirements.txt"
    req_file.write_text("foo==1.0")

    req = Requirement("fromager")
    build_env = build_environment.BuildEnvironment(
        ctx=tmp_context,
        parent_dir=tmp_path,
    )
    results = dependencies.get_build_sdist_dependencies(
        ctx=tmp_context,
        req=req,
        sdist_root_dir=sdist_root_dir,
        build_env=build_env,
    )
    assert results == set([Requirement("foo==1.0")])


@patch("fromager.dependencies.pep517_metadata_of_sdist")
def test_default_get_install_dependencies_of_sdist(
    m_pep517_metadata_of_sdist: Mock,
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    req = Requirement("huggingface-hub")
    version = Version("1.2.3")
    # sdist metadata name may not be normalized
    metadata_txt = textwrap.dedent(
        """\
        Metadata-Version: 2.3
        Name: HuggingFace_Hub
        Version: 1.2.3
        Requires-Dist: filelock
        Requires-Dist: requests
        """
    )
    metadata = Metadata.from_email(metadata_txt)
    m_pep517_metadata_of_sdist.return_value = metadata

    requirements = dependencies.default_get_install_dependencies_of_sdist(
        ctx=tmp_context,
        req=req,
        version=version,
        sdist_root_dir=tmp_path,
        build_env=Mock(),
        extra_environ={},
        build_dir=tmp_path,
        config_settings={},
    )
    assert requirements == {Requirement("filelock"), Requirement("requests")}

    # bad metadata (version mismatch) is treated as non-fatal error
    metadata_txt = textwrap.dedent(
        """\
        Metadata-Version: 2.3
        Name: HuggingFace_Hub
        Version: 1.2a0
        Requires-Dist: filelock
        Requires-Dist: requests
        """
    )
    metadata = Metadata.from_email(metadata_txt)
    m_pep517_metadata_of_sdist.return_value = metadata
    requirements = dependencies.default_get_install_dependencies_of_sdist(
        ctx=tmp_context,
        req=req,
        version=version,
        sdist_root_dir=tmp_path,
        build_env=Mock(),
        extra_environ={},
        build_dir=tmp_path,
        config_settings={},
    )
    assert requirements == {Requirement("filelock"), Requirement("requests")}
    assert (
        "sdist metadata '1.2a0' does not match public version '1.2.3'"
        in caplog.messages[-1]
    )


@pytest.mark.parametrize(
    "req_str,version_str,dist_name_str,dist_version_str,exc",
    [
        ("mypkg", "1.0", "mypkg", "1.0", None),
        ("MyPKG", "1.0", "mypkg", "1.0", None),
        ("mypkg", "1.0", "MyPKG", "1.0", RuntimeError),
        ("mypkg", "1.0", "otherpkg", "1.0", ValueError),
        ("mypkg", "1.0", "mypkg", "1.1", ValueError),
        ("mypkg", "1.0+local", "mypkg", "1.0+local", None),
        ("mypkg", "1.0", "mypkg", "1.0+local", None),
        ("mypkg", "1.0+local", "mypkg", "1.0", None),
    ],
)
def test_validate_dist_name_version(
    req_str: str,
    version_str: str,
    dist_name_str: str,
    dist_version_str: str,
    exc: type[Exception] | None,
) -> None:
    validate = functools.partial(
        dependencies.validate_dist_name_version,
        req=Requirement(req_str),
        version=Version(version_str),
        what="test",
        dist_name=typing.cast(NormalizedName, dist_name_str),
        dist_version=Version(dist_version_str),
    )
    if exc is None:
        validate()
    else:
        with pytest.raises(exc):
            validate()
