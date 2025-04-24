import pathlib
from unittest.mock import Mock, patch

import pytest
import wheel.cli  # type: ignore
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import build_environment, context, wheels


@patch("fromager.sources.download_url")
def test_invalid_wheel_file_exception(
    mock_download_url: Mock, tmp_path: pathlib.Path
) -> None:
    mock_download_url.return_value = pathlib.Path(tmp_path / "test" / "fake_wheel.txt")
    fake_url = "https://www.thisisafakeurl.com"
    fake_dir = tmp_path / "test"
    fake_dir.mkdir()
    text_file = fake_dir / "fake_wheel.txt"
    text_file.write_text("This is a test file")
    req = Requirement("test_pkg")
    with pytest.raises(wheel.cli.WheelError):
        wheels._download_wheel_check(req, fake_dir, fake_url)


@patch("fromager.build_environment.BuildEnvironment.run")
def test_default_build_wheel(
    mock_run: Mock, tmp_path: pathlib.Path, testdata_context: context.WorkContext
) -> None:
    req = Requirement("test_pkg")
    build_env = build_environment.BuildEnvironment(
        ctx=testdata_context, parent_dir=tmp_path, build_requirements=None, req=req
    )
    pbi = testdata_context.package_build_info(req)
    assert pbi.config_settings

    wheels.default_build_wheel(
        ctx=testdata_context,
        build_env=build_env,
        extra_environ={},
        req=req,
        sdist_root_dir=tmp_path,
        version=Version("1.0"),
        build_dir=tmp_path,
    )

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "--config-settings=setup-args=-Dsystem-freetype=true" in cmd
