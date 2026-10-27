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


def test_update_wheel_mirror_prefers_fresh_prebuilt_wheel(
    tmp_context: context.WorkContext,
) -> None:
    """An explicit fresh wheel replaces an old mirror link with the same name."""
    wheel_name = "foo-1.0-py3-none-any.whl"
    old_wheel = _create_fake_wheel(tmp_context.wheels_downloads, wheel_name)
    server.update_wheel_mirror(tmp_context)
    mirror_wheel = tmp_context.wheel_server_dir / "foo" / wheel_name

    fresh_wheel = _create_fake_wheel(tmp_context.wheels_prebuilt, wheel_name)
    server.update_wheel_mirror(tmp_context)
    assert mirror_wheel.resolve() == old_wheel

    server.update_wheel_mirror(tmp_context, preferred_prebuilt_wheel=fresh_wheel)
    assert mirror_wheel.resolve() == fresh_wheel
    assert old_wheel.is_file()


def test_update_wheel_mirror_failed_relink_keeps_old_wheel(
    tmp_context: context.WorkContext,
) -> None:
    """A failed atomic switch leaves the existing mirror link intact."""
    wheel_name = "foo-1.0-py3-none-any.whl"
    old_wheel = _create_fake_wheel(tmp_context.wheels_downloads, wheel_name)
    server.update_wheel_mirror(tmp_context)
    fresh_wheel = _create_fake_wheel(tmp_context.wheels_prebuilt, wheel_name)
    mirror_wheel = tmp_context.wheel_server_dir / "foo" / wheel_name

    with (
        patch("fromager.server.os.replace", side_effect=OSError("replace failed")),
        pytest.raises(OSError, match="replace failed"),
    ):
        server.update_wheel_mirror(tmp_context, preferred_prebuilt_wheel=fresh_wheel)

    assert mirror_wheel.resolve() == old_wheel
    assert not list(mirror_wheel.parent.glob(f".{wheel_name}.*"))


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


@pytest.mark.parametrize(
    ("mirror_target", "expected"),
    [
        ("downloads", "downloads"),
        ("prebuilt", "prebuilt"),
        (None, None),
        ("outside", None),
        ("dangling", None),
    ],
)
def test_find_mirror_wheel(
    tmp_context: context.WorkContext,
    tmp_path: pathlib.Path,
    mirror_target: str | None,
    expected: str | None,
) -> None:
    """Only mirror links to an existing downloads or prebuilt wheel are returned."""
    wheel_name = "pkg-1.0-py3-none-any.whl"
    directories = {
        "downloads": tmp_context.wheels_downloads,
        "prebuilt": tmp_context.wheels_prebuilt,
        "outside": tmp_path / "outside",
        "dangling": tmp_context.wheels_downloads,
    }
    if mirror_target is not None:
        target = directories[mirror_target] / wheel_name
        target.parent.mkdir(parents=True, exist_ok=True)
        if mirror_target != "dangling":
            target.write_bytes(b"wheel")
        mirror_wheel = tmp_context.wheel_server_dir / "pkg" / wheel_name
        mirror_wheel.parent.mkdir(parents=True, exist_ok=True)
        mirror_wheel.symlink_to(target)

    result = server.find_mirror_wheel(tmp_context, wheel_name)

    if expected is None:
        assert result is None
    else:
        assert result == directories[expected] / wheel_name
