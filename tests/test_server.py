from __future__ import annotations

import asyncio
import pathlib
import zipfile
from unittest.mock import Mock, patch

import pytest
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, HTMLResponse

from fromager import context, server


class _FakeRequest:
    """Minimal stand-in for starlette.requests.Request."""

    def __init__(self, path_params: dict[str, str] | None = None) -> None:
        self.path_params = path_params or {}


def _create_fake_wheel(directory: pathlib.Path, name: str) -> pathlib.Path:
    """Create a minimal valid wheel file for testing."""
    wheel_path = directory.joinpath(name)
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("dummy.txt", "fake wheel content")
    return wheel_path


@pytest.fixture
def simple_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a simple index directory with test data."""
    basedir = tmp_path.joinpath("simple")
    basedir.mkdir()
    project_dir = basedir.joinpath("testpkg")
    project_dir.mkdir()
    _create_fake_wheel(project_dir, "testpkg-1.0-py3-none-any.whl")
    project_dir.joinpath("testpkg-1.0-py3-none-any.whl.metadata").write_bytes(
        b"Metadata-Version: 2.1\nName: testpkg\nVersion: 1.0\n"
    )
    project_dir.joinpath("testpkg-1.0.tar.gz").write_bytes(b"fake tarball")
    return basedir


@pytest.fixture
def handler(simple_dir: pathlib.Path) -> server.SimpleHTMLIndex:
    """Create a SimpleHTMLIndex instance for testing."""
    return server.SimpleHTMLIndex(simple_dir)


def test_update_wheel_mirror_moves_to_downloads(
    tmp_context: context.WorkContext,
) -> None:
    """Verify wheels are moved from build dir to downloads dir."""
    _create_fake_wheel(tmp_context.wheels_build, "foo-1.0-py3-none-any.whl")

    server.update_wheel_mirror(tmp_context)

    assert not tmp_context.wheels_build.joinpath("foo-1.0-py3-none-any.whl").exists()
    assert tmp_context.wheels_downloads.joinpath("foo-1.0-py3-none-any.whl").exists()


def test_update_wheel_mirror_creates_symlink(
    tmp_context: context.WorkContext,
) -> None:
    """Verify symlinks are created in the simple index structure."""
    _create_fake_wheel(tmp_context.wheels_build, "foo-1.0-py3-none-any.whl")

    server.update_wheel_mirror(tmp_context)

    symlink = tmp_context.wheel_server_dir.joinpath("foo", "foo-1.0-py3-none-any.whl")
    assert symlink.is_symlink()
    assert symlink.is_file()


def test_update_wheel_mirror_prebuilt_wheels(
    tmp_context: context.WorkContext,
) -> None:
    """Verify wheels in prebuilt directory get symlinked."""
    _create_fake_wheel(tmp_context.wheels_prebuilt, "bar-2.0-py3-none-any.whl")

    server.update_wheel_mirror(tmp_context)

    symlink = tmp_context.wheel_server_dir.joinpath("bar", "bar-2.0-py3-none-any.whl")
    assert symlink.is_symlink()
    assert symlink.is_file()


def test_update_wheel_mirror_cleans_dangling_symlinks(
    tmp_context: context.WorkContext,
) -> None:
    """Verify dangling symlinks are removed and recreated."""
    wheel_path = _create_fake_wheel(
        tmp_context.wheels_downloads, "foo-1.0-py3-none-any.whl"
    )
    server.update_wheel_mirror(tmp_context)

    symlink = tmp_context.wheel_server_dir.joinpath("foo", "foo-1.0-py3-none-any.whl")
    assert symlink.is_symlink()

    # Remove the target to create a dangling symlink
    wheel_path.unlink()
    assert symlink.is_symlink()
    assert not symlink.is_file()  # dangling

    # Re-create the wheel and update again
    _create_fake_wheel(tmp_context.wheels_downloads, "foo-1.0-py3-none-any.whl")
    server.update_wheel_mirror(tmp_context)

    assert symlink.is_symlink()
    assert symlink.is_file()  # no longer dangling


def test_project_page_lists_files(handler: server.SimpleHTMLIndex) -> None:
    """Verify /simple/{project} lists wheel files."""
    request = _FakeRequest({"project": "testpkg"})
    response = asyncio.run(handler.project_page(request))  # type: ignore[arg-type]
    assert isinstance(response, HTMLResponse)
    assert response.status_code == 200
    assert isinstance(response.body, bytes)
    body = response.body.decode()
    assert "testpkg-1.0-py3-none-any.whl" in body
    assert "testpkg-1.0.tar.gz" in body
    assert "testpkg-1.0-py3-none-any.whl.metadata" in body


def test_project_page_missing_project(handler: server.SimpleHTMLIndex) -> None:
    """Verify /simple/{project} raises 404 for unknown project."""
    request = _FakeRequest({"project": "nonexistent"})
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(handler.project_page(request))  # type: ignore[arg-type]
    assert exc_info.value.status_code == 404


def test_serve_wheel_file(handler: server.SimpleHTMLIndex) -> None:
    """Verify serving a .whl file with correct media type."""
    request = _FakeRequest(
        {"project": "testpkg", "filename": "testpkg-1.0-py3-none-any.whl"}
    )
    response = asyncio.run(handler.server_file(request))  # type: ignore[arg-type]
    assert isinstance(response, FileResponse)
    assert response.media_type == "application/zip"


def test_serve_file_not_found(handler: server.SimpleHTMLIndex) -> None:
    """Verify 404 for missing file."""
    request = _FakeRequest(
        {"project": "testpkg", "filename": "nonexistent-1.0-py3-none-any.whl"}
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(handler.server_file(request))  # type: ignore[arg-type]
    assert exc_info.value.status_code == 404


def test_serve_file_bad_extension(
    simple_dir: pathlib.Path,
    handler: server.SimpleHTMLIndex,
) -> None:
    """Verify 400 for unsupported file extension."""
    simple_dir.joinpath("testpkg", "bad.txt").write_text("bad")
    request = _FakeRequest({"project": "testpkg", "filename": "bad.txt"})
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(handler.server_file(request))  # type: ignore[arg-type]
    assert exc_info.value.status_code == 400


@patch("fromager.server.run_wheel_server")
@patch("fromager.server.update_wheel_mirror")
def test_start_wheel_server_uses_external_url(
    mock_mirror: Mock,
    mock_run: Mock,
    tmp_context: context.WorkContext,
) -> None:
    """Verify no local server starts when external URL is configured."""
    tmp_context.wheel_server_url = "http://external:8080/simple/"

    server.start_wheel_server(tmp_context)

    mock_mirror.assert_called_once_with(tmp_context)
    mock_run.assert_not_called()
    assert tmp_context.wheel_server_url == "http://external:8080/simple/"


@patch("fromager.server.run_wheel_server")
@patch("fromager.server.update_wheel_mirror")
def test_start_wheel_server_starts_local(
    mock_mirror: Mock,
    mock_run: Mock,
    tmp_context: context.WorkContext,
) -> None:
    """Verify local server starts when no external URL is set."""
    assert tmp_context.wheel_server_url == ""

    server.start_wheel_server(tmp_context)

    mock_mirror.assert_called_once_with(tmp_context)
    mock_run.assert_called_once_with(tmp_context)
