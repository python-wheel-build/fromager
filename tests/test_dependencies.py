import functools
import itertools
import os
import pathlib
import shutil
import textwrap
import typing
import zipfile
from unittest.mock import Mock, patch

import hatchling.build
import pytest
from packaging.metadata import Metadata
from packaging.requirements import Requirement
from packaging.utils import NormalizedName
from packaging.version import Version

from fromager import build_environment, context, dependencies


def build_test_wheel(
    tmp_path: pathlib.Path,
    name: str,
    version: str,
    pkg_deps: list[str] | None = None,
    optional_deps: dict[str, list[str]] | None = None,
) -> pathlib.Path:
    """Build a real wheel using hatchling for testing.

    Args:
        tmp_path: Temporary directory for building
        name: Package name
        version: Package version
        pkg_deps: List of dependencies (e.g., ["requests>=2.0", "urllib3"])
        optional_deps: Dict of extras (e.g., {"test": ["pytest"]})

    Returns:
        Path to the built wheel file
    """
    # Create package directory structure
    pkg_dir = tmp_path / "pkg_source"
    pkg_dir.mkdir()
    src_dir = pkg_dir / "src" / name.replace("-", "_")
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text('"""Test package."""\n')

    # Build pyproject.toml
    deps_str = ""
    if pkg_deps:
        deps_list = ", ".join(f'"{d}"' for d in pkg_deps)
        deps_str = f"dependencies = [{deps_list}]"

    optional_deps_str = ""
    if optional_deps:
        optional_deps_str = "[project.optional-dependencies]\n"
        for extra, extra_deps in optional_deps.items():
            extra_deps_list = ", ".join(f'"{d}"' for d in extra_deps)
            optional_deps_str += f"{extra} = [{extra_deps_list}]\n"

    pyproject_content = textwrap.dedent(f"""\
        [build-system]
        requires = ["hatchling"]
        build-backend = "hatchling.build"

        [project]
        name = "{name}"
        version = "{version}"
        {deps_str}

        {optional_deps_str}

        [tool.hatch.build.targets.wheel]
        packages = ["src/{name.replace("-", "_")}"]
    """)
    (pkg_dir / "pyproject.toml").write_text(pyproject_content)

    # Build the wheel using hatchling directly
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()

    original_cwd = pathlib.Path.cwd()
    try:
        os.chdir(pkg_dir)
        wheel_filename: str = hatchling.build.build_wheel(str(wheel_dir))
    finally:
        os.chdir(original_cwd)

    return wheel_dir / wheel_filename


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


def test_get_install_dependencies_of_wheel(tmp_path: pathlib.Path) -> None:
    """Test extracting install dependencies from a wheel file built with real tools."""
    # Arrange: Build a real wheel with dependencies
    wheel_file = build_test_wheel(
        tmp_path,
        name="test-pkg",
        version="1.0.0",
        pkg_deps=["requests>=2.0", "urllib3"],
        optional_deps={"test": ["pytest"]},
    )

    req = Requirement("test-pkg")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    # Act
    result = dependencies.get_install_dependencies_of_wheel(req, wheel_file, output_dir)

    # Assert: Should get requests and urllib3, but not pytest (extra not requested)
    result_names = {r.name for r in result}
    assert result_names == {"requests", "urllib3"}


def test_get_install_dependencies_of_wheel_no_deps(tmp_path: pathlib.Path) -> None:
    """Test extracting dependencies from a wheel with no dependencies."""
    # Arrange: Build a real wheel without dependencies
    wheel_file = build_test_wheel(
        tmp_path,
        name="simple-pkg",
        version="1.0.0",
    )

    req = Requirement("simple-pkg")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    # Act
    result = dependencies.get_install_dependencies_of_wheel(req, wheel_file, output_dir)

    # Assert
    assert result == set()


def test_get_metadata_from_wheel_missing_metadata(tmp_path: pathlib.Path) -> None:
    """Test that missing METADATA file raises ValueError."""
    # Arrange: Create a wheel file without METADATA
    wheel_file = tmp_path / "broken_pkg-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_file, "w") as zf:
        zf.writestr("broken_pkg/__init__.py", "")

    # Act & Assert
    with pytest.raises(ValueError, match="Could not find METADATA file"):
        dependencies._get_metadata_from_wheel(wheel_file)


def test_get_metadata_from_wheel_with_build_tag(tmp_path: pathlib.Path) -> None:
    """Test extracting metadata from a wheel with a build tag in the filename.

    Wheel format: {distribution}-{version}-{build}-{python}-{abi}-{platform}.whl
    The build tag is optional. parse_wheel_filename correctly separates the version
    from the build tag, so the dist-info path is computed correctly.
    """
    # Arrange: Create a wheel with a build tag (123)
    wheel_file = tmp_path / "mypkg-1.0.0-123-py3-none-any.whl"
    metadata_content = textwrap.dedent("""\
        Metadata-Version: 2.1
        Name: mypkg
        Version: 1.0.0
        Requires-Dist: requests
    """)
    with zipfile.ZipFile(wheel_file, "w") as zf:
        # dist-info directory is {name}-{version}.dist-info (no build tag)
        zf.writestr("mypkg-1.0.0.dist-info/METADATA", metadata_content)
        zf.writestr("mypkg-1.0.0.dist-info/WHEEL", "Wheel-Version: 1.0")
        zf.writestr("mypkg/__init__.py", "")

    # Act: parse_wheel_filename correctly extracts version=1.0.0 (not 123)
    metadata = dependencies._get_metadata_from_wheel(wheel_file)

    # Assert
    assert metadata.name == "mypkg"
    assert str(metadata.version) == "1.0.0"
    assert metadata.requires_dist is not None
    assert len(metadata.requires_dist) == 1
    assert str(metadata.requires_dist[0]) == "requests"


def test_get_metadata_from_wheel_validation_disabled(tmp_path: pathlib.Path) -> None:
    """Test that validation can be disabled when parsing wheel metadata.

    Some wheels may have metadata that doesn't strictly conform to PEP standards
    but is still usable. The validate=False option allows parsing such metadata.
    """
    # Arrange: Create a wheel with slightly non-conformant metadata
    # (missing Metadata-Version which is technically required)
    wheel_file = tmp_path / "testpkg-1.0.0-py3-none-any.whl"
    metadata_content = textwrap.dedent("""\
        Name: testpkg
        Version: 1.0.0
        Requires-Dist: urllib3
    """)
    with zipfile.ZipFile(wheel_file, "w") as zf:
        zf.writestr("testpkg-1.0.0.dist-info/METADATA", metadata_content)
        zf.writestr("testpkg-1.0.0.dist-info/WHEEL", "Wheel-Version: 1.0")
        zf.writestr("testpkg/__init__.py", "")

    # Act: Parse with validation disabled
    metadata = dependencies._get_metadata_from_wheel(wheel_file, validate=False)

    # Assert: Should still parse the basic fields
    assert metadata.name == "testpkg"
    assert str(metadata.version) == "1.0.0"
