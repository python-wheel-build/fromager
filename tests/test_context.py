import os
import pathlib
from unittest.mock import Mock, patch

import pytest
from packaging.requirements import Requirement

from fromager import context


def _make_context(
    tmp_path: pathlib.Path,
    constraints_file: str | None = None,
    wheel_server_url: str = "",
    cleanup: bool = True,
) -> context.WorkContext:
    return context.WorkContext(
        active_settings=None,
        constraints_file=constraints_file,
        patches_dir=tmp_path / "overrides/patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        wheel_server_url=wheel_server_url,
        cleanup=cleanup,
    )


def _all_setup_dirs(ctx: context.WorkContext) -> list[pathlib.Path]:
    return [
        ctx.work_dir,
        ctx.sdists_repo,
        ctx.sdists_downloads,
        ctx.sdists_builds,
        ctx.wheels_repo,
        ctx.wheels_downloads,
        ctx.wheels_prebuilt,
        ctx.wheels_build,
        ctx.uv_cache,
        ctx.logs_dir,
    ]


def test_pip_constraints_args(tmp_path: pathlib.Path) -> None:
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text("\n")  # the file has to exist
    ctx = _make_context(tmp_path, constraints_file=str(constraints_file))
    ctx.setup()
    assert ["--constraint", os.fspath(constraints_file)] == ctx.pip_constraint_args

    ctx = _make_context(tmp_path)
    ctx.setup()
    assert [] == ctx.pip_constraint_args


def test_setup_creates_directories(tmp_path: pathlib.Path) -> None:
    ctx = _make_context(tmp_path)
    ctx.setup()

    for d in _all_setup_dirs(ctx):
        assert d.is_dir(), f"{d} was not created"


def test_setup_is_idempotent(tmp_path: pathlib.Path) -> None:
    ctx = _make_context(tmp_path)
    ctx.setup()

    test_file = ctx.logs_dir / "test_file.txt"
    test_file.write_text("test text")

    ctx.setup()

    for d in _all_setup_dirs(ctx):
        assert d.is_dir(), f"{d} was not created"
    assert test_file.read_text() == "test text"


def test_package_build_info_extracts_name_from_requirement(
    tmp_context: context.WorkContext,
) -> None:
    to_return = Mock()
    with patch.object(
        tmp_context.settings, "package_build_info", return_value=to_return
    ) as mock_pbi:
        result = tmp_context.package_build_info(Requirement("numpy>=1.0"))

    mock_pbi.assert_called_once_with("numpy")
    assert result is to_return


def test_package_build_info_passes_string_directly(
    tmp_context: context.WorkContext,
) -> None:
    to_return = Mock()
    with patch.object(
        tmp_context.settings, "package_build_info", return_value=to_return
    ) as mock_pbi:
        result = tmp_context.package_build_info("numpy")

    mock_pbi.assert_called_once_with("numpy")
    assert result is to_return


def test_wheels_build_default(tmp_context: context.WorkContext) -> None:
    assert tmp_context.wheels_build == tmp_context.wheels_build_base


def test_wheels_build_parallel(tmp_context: context.WorkContext) -> None:
    tmp_context.enable_parallel_builds()

    result = tmp_context.wheels_build

    assert result.parent == tmp_context.wheels_build_base
    assert result.is_dir()


def test_write_to_graph_to_file(tmp_path: pathlib.Path) -> None:
    ctx = _make_context(tmp_path)
    ctx.setup()

    with patch.object(ctx.dependency_graph, "serialize") as mock_serialize:
        ctx.write_to_graph_to_file()

    mock_serialize.assert_called_once()
    assert ctx.graph_file.exists()


def test_pip_wheel_server_args_https(tmp_path: pathlib.Path) -> None:
    ctx = _make_context(tmp_path, wheel_server_url="https://wheels.example.com/simple")
    assert ctx.pip_wheel_server_args == [
        "--index-url",
        "https://wheels.example.com/simple",
    ]


def test_pip_wheel_server_args_http(tmp_path: pathlib.Path) -> None:
    ctx = _make_context(tmp_path, wheel_server_url="http://wheels.example.com/simple")
    assert ctx.pip_wheel_server_args == [
        "--index-url",
        "http://wheels.example.com/simple",
        "--trusted-host",
        "wheels.example.com",
    ]


def test_uv_clean_cache_no_args_raises(tmp_path: pathlib.Path) -> None:
    ctx = _make_context(tmp_path)
    ctx.setup()

    with pytest.raises(ValueError):
        ctx.uv_clean_cache()


@patch("fromager.context.external_commands.run")
def test_uv_clean_cache_calls_run(mock_run: Mock, tmp_path: pathlib.Path) -> None:
    ctx = _make_context(tmp_path)
    ctx.setup()

    ctx.uv_clean_cache(Requirement("numpy"), Requirement("torch"))

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == ["uv", "clean", "cache", "numpy", "torch"]
    extra_env = mock_run.call_args[1]["extra_environ"]
    assert extra_env["UV_CACHE_DIR"] == str(ctx.uv_cache)


def test_clean_build_dirs_raises_when_env_is_child_of_sdist(
    tmp_path: pathlib.Path,
) -> None:
    ctx = _make_context(tmp_path)
    ctx.setup()

    sdist_root = tmp_path / "source"
    sdist_root.mkdir()
    build_env = Mock()
    build_env.path = sdist_root / "venv"
    build_env.path.mkdir()

    with pytest.raises(ValueError):
        ctx.clean_build_dirs(sdist_root_dir=sdist_root, build_env=build_env)

    assert sdist_root.is_dir()
    assert build_env.path.is_dir()


def test_clean_build_dirs_removes_dirs_when_cleanup_enabled(
    tmp_path: pathlib.Path,
) -> None:
    ctx = _make_context(tmp_path, cleanup=True)
    ctx.setup()

    sdist_root = tmp_path / "source"
    sdist_root.mkdir()
    build_env = Mock()
    build_env.path = tmp_path / "build-env"
    build_env.path.mkdir()

    ctx.clean_build_dirs(sdist_root_dir=sdist_root, build_env=build_env)

    assert not sdist_root.exists()
    assert not build_env.path.exists()


def test_clean_build_dirs_keeps_dirs_when_cleanup_disabled(
    tmp_path: pathlib.Path,
) -> None:
    ctx = _make_context(tmp_path, cleanup=False)
    ctx.setup()

    sdist_root = tmp_path / "source"
    sdist_root.mkdir()
    build_env = Mock()
    build_env.path = tmp_path / "build-env"
    build_env.path.mkdir()

    ctx.clean_build_dirs(sdist_root_dir=sdist_root, build_env=build_env)

    assert sdist_root.exists()
    assert build_env.path.exists()
