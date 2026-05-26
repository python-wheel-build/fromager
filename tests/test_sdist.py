import pathlib
import tarfile

from packaging.version import Version

from fromager import dependencies, sdist


def test_make_sdist_directory_renames_and_adds_pkg_info(
    tmp_path: pathlib.Path,
) -> None:
    """Directory is renamed and PKG-INFO is created."""
    # Arrange
    src = tmp_path / "SomeProject"
    src.mkdir()
    (src / "setup.py").write_text("# placeholder")

    # Act
    result = sdist.make_sdist_directory(src, "Some-Project", Version("1.2.3"))

    # Assert
    assert result.name == "some_project-1.2.3"
    assert result.exists()
    pkg_info = result / "PKG-INFO"
    assert pkg_info.is_file()
    content = pkg_info.read_text()
    assert "Metadata-Version: 2.2" in content
    assert "Name: Some-Project" in content
    assert "Version: 1.2.3" in content
    assert dependencies.STUB_PKG_INFO_SUMMARY in content


def test_make_sdist_directory_already_correct_name(
    tmp_path: pathlib.Path,
) -> None:
    """No rename when directory already has the expected name."""
    # Arrange
    src = tmp_path / "my_pkg-0.1"
    src.mkdir()

    # Act
    result = sdist.make_sdist_directory(src, "my-pkg", Version("0.1"))

    # Assert
    assert result == src
    assert (result / "PKG-INFO").is_file()


def test_make_sdist_directory_preserves_existing_pkg_info(
    tmp_path: pathlib.Path,
) -> None:
    """Existing PKG-INFO is not overwritten."""
    # Arrange
    src = tmp_path / "mypkg-2.0"
    src.mkdir()
    existing_content = "Metadata-Version: 2.1\nName: mypkg\nVersion: 2.0\n"
    (src / "PKG-INFO").write_text(existing_content)

    # Act
    result = sdist.make_sdist_directory(src, "mypkg", Version("2.0"))

    # Assert
    assert (result / "PKG-INFO").read_text() == existing_content


def test_make_sdist_directory_writes_build_dir_pkg_info(
    tmp_path: pathlib.Path,
) -> None:
    """PKG-INFO is also written to build_dir when it differs from source root."""
    # Arrange
    src = tmp_path / "pkg-1.0"
    src.mkdir()
    build_dir = src / "src"
    build_dir.mkdir()

    # Act
    result = sdist.make_sdist_directory(src, "pkg", Version("1.0"), build_dir=build_dir)

    # Assert
    assert (result / "PKG-INFO").is_file()
    assert (build_dir / "PKG-INFO").is_file()


def test_make_sdist_directory_skips_build_dir_when_same(
    tmp_path: pathlib.Path,
) -> None:
    """When build_dir equals source_dir, only one PKG-INFO is written."""
    # Arrange
    src = tmp_path / "pkg-1.0"
    src.mkdir()

    # Act
    result = sdist.make_sdist_directory(src, "pkg", Version("1.0"), build_dir=src)

    # Assert
    assert (result / "PKG-INFO").is_file()


def test_make_sdist_directory_rebases_build_dir_after_rename(
    tmp_path: pathlib.Path,
) -> None:
    """build_dir subdirectory is correctly rebased when source_dir is renamed."""
    # Arrange
    src = tmp_path / "MyPkg"
    src.mkdir()
    sub = src / "python"
    sub.mkdir()
    (sub / "lib.py").write_text("# code")

    # Act
    result = sdist.make_sdist_directory(src, "MyPkg", Version("1.0"), build_dir=sub)

    # Assert
    assert result.name == "mypkg-1.0"
    expected_build = result / "python"
    assert expected_build.is_dir()
    assert (expected_build / "PKG-INFO").is_file()


def test_repack_as_sdist_creates_tarball(tmp_path: pathlib.Path) -> None:
    """Verify the archive is created with correct name and contents."""
    # Arrange
    src = tmp_path / "project"
    src.mkdir()
    (src / "setup.py").write_text("# placeholder")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    # Act
    result = sdist.repack_as_sdist(src, "project", Version("3.0"), output_dir)

    # Assert
    assert result.name == "project-3.0.tar.gz"
    assert result.is_file()
    with tarfile.open(result, "r:gz") as tf:
        names = tf.getnames()
    assert any("PKG-INFO" in n for n in names)
    assert any("setup.py" in n for n in names)


def test_repack_as_sdist_uses_build_dir(tmp_path: pathlib.Path) -> None:
    """When build_dir is set, the tarball is rooted at build_dir."""
    # Arrange
    src = tmp_path / "mylib-1.0"
    src.mkdir()
    build_sub = src / "python"
    build_sub.mkdir()
    (build_sub / "lib.py").write_text("# code")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    # Act
    result = sdist.repack_as_sdist(
        src, "mylib", Version("1.0"), output_dir, build_dir=build_sub
    )

    # Assert
    assert result.is_file()
    with tarfile.open(result, "r:gz") as tf:
        names = tf.getnames()
    assert any("lib.py" in n for n in names)


def test_repack_as_sdist_normalizes_name(tmp_path: pathlib.Path) -> None:
    """Package name is normalized in the archive filename."""
    # Arrange
    src = tmp_path / "My-Package"
    src.mkdir()
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    # Act
    result = sdist.repack_as_sdist(src, "My-Package", Version("0.1"), output_dir)

    # Assert
    assert result.name == "my_package-0.1.tar.gz"


def test_repack_as_sdist_overwrites_existing(tmp_path: pathlib.Path) -> None:
    """Pre-existing tarball with the same name is replaced."""
    # Arrange
    src = tmp_path / "pkg-1.0"
    src.mkdir()
    (src / "file.txt").write_text("content")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    stale = output_dir / "pkg-1.0.tar.gz"
    stale.write_text("stale")

    # Act
    result = sdist.repack_as_sdist(src, "pkg", Version("1.0"), output_dir)

    # Assert
    assert result.is_file()
    assert result.read_bytes() != b"stale"
