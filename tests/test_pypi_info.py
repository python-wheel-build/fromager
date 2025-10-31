from unittest.mock import Mock, patch

import pytest
import requests
from click.testing import CliRunner

from fromager.commands.pypi_info import (
    PackageNotFoundError,
    _get_package_info,
    pypi_info,
)


@pytest.fixture
def mock_package_data():
    """Mock PyPI package data for testing."""
    return {
        "info": {
            "name": "test-package",
            "version": "1.0.0",
            "license": "MIT",
            "home_page": "https://example.com",
            "project_urls": {
                "Repository": "https://github.com/example/test-package",
                "Documentation": "https://docs.example.com",
            },
        },
        "urls": [
            {"packagetype": "sdist", "filename": "test-package-1.0.0.tar.gz"},
            {
                "packagetype": "bdist_wheel",
                "filename": "test_package-1.0.0-py3-none-any.whl",
            },
        ],
    }


@pytest.fixture
def mock_package_data_wheel_only():
    """Mock PyPI package data with only wheel."""
    return {
        "info": {
            "name": "wheel-only-package",
            "version": "2.0.0",
            "license": "",
            "home_page": "",
            "project_urls": {},
        },
        "urls": [
            {
                "packagetype": "bdist_wheel",
                "filename": "wheel_only_package-2.0.0-py3-none-any.whl",
            },
        ],
    }


class TestGetPackageInfo:
    """Tests for _get_package_info function."""

    @patch("fromager.commands.pypi_info.session")
    def test_get_package_info_success_latest(self, mock_session, mock_package_data):
        """Test successful package info retrieval for latest version."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_package_data
        mock_session.get.return_value = mock_response

        result = _get_package_info("https://pypi.org/pypi", "test-package")

        assert result == mock_package_data
        mock_session.get.assert_called_once_with(
            "https://pypi.org/pypi/test-package/json"
        )

    @patch("fromager.commands.pypi_info.session")
    def test_get_package_info_success_specific_version(
        self, mock_session, mock_package_data
    ):
        """Test successful package info retrieval for specific version."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_package_data
        mock_session.get.return_value = mock_response

        result = _get_package_info("https://pypi.org/pypi", "test-package", "1.0.0")

        assert result == mock_package_data
        mock_session.get.assert_called_once_with(
            "https://pypi.org/pypi/test-package/1.0.0/json"
        )

    @patch("fromager.commands.pypi_info.session")
    def test_get_package_info_not_found_package(self, mock_session):
        """Test package not found error."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_session.get.return_value = mock_response

        with pytest.raises(
            PackageNotFoundError, match="Package 'nonexistent' not found on PyPI"
        ):
            _get_package_info("https://pypi.org/pypi", "nonexistent")

    @patch("fromager.commands.pypi_info.session")
    def test_get_package_info_not_found_version(self, mock_session):
        """Test version not found error."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_session.get.return_value = mock_response

        with pytest.raises(
            PackageNotFoundError,
            match=r"Package 'test-package' version '9.9.9' not found on PyPI",
        ):
            _get_package_info("https://pypi.org/pypi", "test-package", "9.9.9")

    @patch("fromager.commands.pypi_info.session")
    def test_get_package_info_http_error(self, mock_session):
        """Test HTTP error handling."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.HTTPError("Server error")
        mock_session.get.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            _get_package_info("https://pypi.org/pypi", "test-package")


class TestPypiInfoCommand:
    """Tests for the pypi-info command."""

    def test_pypi_info_command_success(self, mock_package_data):
        """Test successful pypi-info command execution."""
        runner = CliRunner()

        with patch("fromager.commands.pypi_info._get_package_info") as mock_get_info:
            mock_get_info.return_value = mock_package_data

            result = runner.invoke(pypi_info, ["test-package"], obj=Mock())

            assert result.exit_code == 0
            output = result.output
            assert "Package: test-package" in output
            assert "Version: 1.0.0" in output
            assert "Found on PyPI: Yes" in output
            assert "License: MIT" in output
            assert "Homepage: https://example.com" in output
            assert "Repository: https://github.com/example/test-package" in output
            assert "Has source distribution (sdist): Yes" in output
            assert "Has wheel: Yes" in output

    def test_pypi_info_command_wheel_only(self, mock_package_data_wheel_only):
        """Test info command with wheel-only package."""
        runner = CliRunner()

        with patch("fromager.commands.pypi_info._get_package_info") as mock_get_info:
            mock_get_info.return_value = mock_package_data_wheel_only

            result = runner.invoke(pypi_info, ["wheel-only-package"], obj=Mock())

            assert result.exit_code == 0
            output = result.output
            assert "Package: wheel-only-package" in output
            assert "License: Not specified" in output
            assert "Homepage: Not specified" in output
            assert "Has source distribution (sdist): No" in output
            assert "Has wheel: Yes" in output

    def test_pypi_info_command_with_version_spec(self, mock_package_data):
        """Test info command with version specification."""
        runner = CliRunner()

        with patch("fromager.commands.pypi_info._get_package_info") as mock_get_info:
            mock_get_info.return_value = mock_package_data

            result = runner.invoke(pypi_info, ["test-package==1.0.0"], obj=Mock())

            assert result.exit_code == 0
            mock_get_info.assert_called_once_with(
                "https://pypi.org/pypi", "test-package", "1.0.0"
            )

    def test_pypi_info_command_invalid_package_spec(self):
        """Test info command with invalid package specification."""
        runner = CliRunner()

        result = runner.invoke(pypi_info, ["invalid[package[spec"], obj=Mock())

        assert result.exit_code == 1
        assert "Invalid package specification" in result.output

    def test_pypi_info_command_unsupported_version_spec(self):
        """Test info command with unsupported version specification."""
        runner = CliRunner()

        result = runner.invoke(pypi_info, ["test-package>=1.0.0"], obj=Mock())

        assert result.exit_code == 1
        assert "Only exact version specifications (==) are supported" in result.output

    def test_pypi_info_command_package_not_found(self):
        """Test info command with package not found."""
        runner = CliRunner()

        with patch("fromager.commands.pypi_info._get_package_info") as mock_get_info:
            mock_get_info.side_effect = PackageNotFoundError(
                "Package 'nonexistent' not found on PyPI"
            )

            result = runner.invoke(pypi_info, ["nonexistent"], obj=Mock())

            assert result.exit_code == 1
            assert "Package 'nonexistent' not found on PyPI" in result.output

    def test_pypi_info_command_custom_pypi_url(self, mock_package_data):
        """Test info command with custom PyPI base URL."""
        runner = CliRunner()

        with patch("fromager.commands.pypi_info._get_package_info") as mock_get_info:
            mock_get_info.return_value = mock_package_data

            result = runner.invoke(
                pypi_info,
                ["--pypi-base-url", "https://custom.pypi.org/pypi", "test-package"],
                obj=Mock(),
            )

            assert result.exit_code == 0
            mock_get_info.assert_called_once_with(
                "https://custom.pypi.org/pypi", "test-package", None
            )

    def test_pypi_info_command_general_exception(self):
        """Test info command with general exception."""
        runner = CliRunner()

        with patch("fromager.commands.pypi_info._get_package_info") as mock_get_info:
            mock_get_info.side_effect = Exception("Network error")

            result = runner.invoke(pypi_info, ["test-package"], obj=Mock())

            assert result.exit_code == 1
            assert "Failed to retrieve package information" in result.output
