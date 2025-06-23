import pathlib
import tempfile
import zipfile
from unittest.mock import Mock, patch

import pytest
import wheel.cli  # type: ignore
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import build_environment, context, sources, wheels


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
        ctx=testdata_context,
        parent_dir=tmp_path,
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


@patch("fromager.external_commands.run")
def test_add_extra_metadata_allows_legitimate_double_dots(
    mock_run: Mock, tmp_path: pathlib.Path, testdata_context: context.WorkContext
) -> None:
    """Test that add_extra_metadata_to_wheels allows legitimate filenames with '..' in them."""
    req = Requirement("test_pkg==1.0.0")
    version = Version("1.0.0")

    # Create a minimal wheel file with a legitimate file containing ".." in filename
    wheel_dir = tmp_path / "wheel_build"
    wheel_dir.mkdir()
    wheel_file = wheel_dir / "test_pkg-1.0.0-py3-none-any.whl"

    with zipfile.ZipFile(wheel_file, "w") as zf:
        # Add minimal legitimate files
        zf.writestr("test_pkg/__init__.py", "")
        zf.writestr(
            "test_pkg-1.0.0.dist-info/METADATA",
            "Name: test_pkg\nVersion: 1.0.0\n",
        )
        zf.writestr(
            "test_pkg-1.0.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )

        # This should be allowed - ".." is part of filename, not a path component
        zf.writestr("test_pkg/static/js/icon..569adb91.chunk.js", "content")

    # Mock the wheel pack command to avoid actual wheel building
    mock_run.return_value = ""

    # Create a fake rebuilt wheel file to satisfy the function
    (wheel_dir / "test_pkg-1.0.0-0-py3-none-any.whl").touch()

    sdist_dir = tmp_path / "sdist"
    sdist_dir.mkdir()

    # This should NOT raise an error
    result_wheel = wheels.add_extra_metadata_to_wheels(
        ctx=testdata_context,
        req=req,
        version=version,
        extra_environ={},
        sdist_root_dir=sdist_dir,
        wheel_file=wheel_file,
    )

    # Verify the function completed without error
    assert result_wheel.exists()
    mock_run.assert_called_once()


def test_download_wheel_unquotes_url_encoded_filenames(tmp_path: pathlib.Path) -> None:
    """Test that download_wheel properly unquotes URL-encoded characters in filenames."""
    req = Requirement("test_pkg")
    # URL with encoded plus sign (%2B)
    wheel_url = "https://example.test/test_pkg-1.0%2Blocal-py3-none-any.whl"

    mock_wheel, mock_wheel_file = tempfile.mkstemp()
    with zipfile.ZipFile(mock_wheel_file, "w") as zf:
        # Add minimal legitimate files
        zf.writestr("test_pkg/__init__.py", "")
        zf.writestr(
            "test_pkg-1.0+local.dist-info/METADATA",
            "Name: test_pkg\nVersion: 1.0.0\n",
        )
        zf.writestr(
            "test_pkg-1.0+local.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        zf.writestr(
            "test_pkg-1.0+local.dist-info/RECORD",
            "test_pkg/static/js/icon..569adb91.chunk.js,,",
        )

        # This should be allowed - ".." is part of filename, not a path component
        zf.writestr("test_pkg/static/js/icon..569adb91.chunk.js", "content")

    with patch("fromager.request_session.session.get") as mock_get:
        # Mock successful response
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        with open(mock_wheel_file, "rb") as wf:
            mock_response.iter_content.return_value = [wf.read()]
        mock_get.return_value.__enter__.return_value = mock_response

        result_filename = wheels.download_wheel(req, wheel_url, tmp_path)

        # The filename should be unquoted, containing actual + character
        expected_filename = tmp_path / "test_pkg-1.0+local-py3-none-any.whl"
        assert result_filename == expected_filename


def test_sources_download_url_unquotes_filenames(tmp_path: pathlib.Path) -> None:
    """Test that sources.download_url properly unquotes URL-encoded characters in filenames."""
    req = Requirement("test_pkg")
    # URL with encoded plus sign (%2B)
    url = "https://example.test/test_pkg-1.0%2Blocal.tar.gz"

    with patch("fromager.request_session.session.get") as mock_get:
        # Mock successful response
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.iter_content.return_value = [b"test content"]
        mock_get.return_value.__enter__.return_value = mock_response

        result_filename = sources.download_url(
            req=req, destination_dir=tmp_path, url=url
        )

        # The filename should be unquoted, containing actual + character
        expected_filename = tmp_path / "test_pkg-1.0+local.tar.gz"
        assert result_filename == expected_filename


def test_add_extra_metadata_blocks_path_traversal(
    tmp_path: pathlib.Path, testdata_context: context.WorkContext
) -> None:
    """Test that add_extra_metadata_to_wheels blocks actual path traversal attempts."""
    req = Requirement("malicious_pkg==1.0.0")
    version = Version("1.0.0")

    # Create a wheel file with actual path traversal attempt
    wheel_dir = tmp_path / "wheel_build"
    wheel_dir.mkdir()
    wheel_file = wheel_dir / "malicious_pkg-1.0.0-py3-none-any.whl"

    with zipfile.ZipFile(wheel_file, "w") as zf:
        # Add minimal legitimate files
        zf.writestr("malicious_pkg/__init__.py", "")
        zf.writestr(
            "malicious_pkg-1.0.0.dist-info/METADATA",
            "Name: malicious_pkg\nVersion: 1.0.0\n",
        )
        zf.writestr(
            "malicious_pkg-1.0.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )

        # Add a file with actual path traversal (should be blocked)
        zf.writestr("../../../etc/passwd", "malicious content")

    sdist_dir = tmp_path / "sdist"
    sdist_dir.mkdir()

    # This should raise a ValueError due to path traversal attempt
    with pytest.raises(
        ValueError, match="Unsafe path in wheel: \\.\\./\\.\\./\\.\\./etc/passwd"
    ):
        wheels.add_extra_metadata_to_wheels(
            ctx=testdata_context,
            req=req,
            version=version,
            extra_environ={},
            sdist_root_dir=sdist_dir,
            wheel_file=wheel_file,
        )
