import os
import pathlib
import tarfile

from fromager import tarballs


def test_modes_change(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    a = root / "a"
    a.write_text("this is file a")
    a.chmod(0o0600)

    t1 = tmp_path / "out1.tar"
    with tarfile.open(t1, "w") as tf:
        tarballs.tar_reproducible(tf, root)

    a.chmod(0o0666)

    t2 = tmp_path / "out2.tar"
    with tarfile.open(t2, "w") as tf:
        tarballs.tar_reproducible(tf, root)

    t1_contents = t1.read_bytes()
    t2_contents = t2.read_bytes()
    assert t1_contents == t2_contents, "file contents differ"


def test_prefix_strip(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    subdir = root / "subdir"
    subdir.mkdir()
    a = subdir / "a"
    a.write_text("this is file a")

    t1 = tmp_path / "out1.tar"
    with tarfile.open(t1, "w") as tf:
        tarballs.tar_reproducible(tar=tf, basedir=root, prefix=subdir.parent)
    with tarfile.open(t1, "r") as tf:
        names = tf.getnames()
    assert names == [".", "subdir", "subdir/a"]


def test_no_prefix_strip(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    subdir = root / "subdir"
    subdir.mkdir()
    a = subdir / "a"
    a.write_text("this is file a")

    t1 = tmp_path / "out1.tar"
    with tarfile.open(t1, "w") as tf:
        tarballs.tar_reproducible(tar=tf, basedir=root)
    with tarfile.open(t1, "r") as tf:
        names = tf.getnames()
    assert names == [str(p).lstrip(os.sep) for p in [root, subdir, a]]


def test_no_vcs_exclude(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    subdir = root / ".git"
    subdir.mkdir()
    a = subdir / "config"
    a.write_text("this is a VCS file")

    t1 = tmp_path / "out1.tar"
    with tarfile.open(t1, "w") as tf:
        tarballs.tar_reproducible(tar=tf, basedir=root)
    with tarfile.open(t1, "r") as tf:
        names = tf.getnames()
    assert names == [str(p).lstrip(os.sep) for p in [root, subdir, a]]


def test_vcs_exclude(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    a = root / "a"
    a.write_text("this is file a")

    for vcs in tarballs.VCS_DIRS:
        subdir = root / vcs
        subdir.mkdir()
        a = subdir / "config"
        a.write_text("this is a VCS file")

    t1 = tmp_path / "out1.tar"
    with tarfile.open(t1, "w") as tf:
        tarballs.tar_reproducible(tar=tf, basedir=root, exclude_vcs=True)
    with tarfile.open(t1, "r") as tf:
        names = tf.getnames()
    assert names == [str(p).lstrip(os.sep) for p in [root, root / "a"]]


def test_arcname_root(tmp_path: pathlib.Path) -> None:
    """Test that arcname_root sets the top-level directory name.

    This reproduces issue #1315: when basedir is a subdirectory (monorepo case),
    arcname_root should ensure the top-level archive entry is {name}-{version},
    not the basedir's name.
    """
    # Simulate a monorepo structure: mypkg-1.0/python/
    sdist_root = tmp_path / "mypkg-1.0"
    build_dir = sdist_root / "python"
    build_dir.mkdir(parents=True)
    (build_dir / "setup.py").write_text("from setuptools import setup; setup()\n")

    t1 = tmp_path / "out.tar"
    with tarfile.open(t1, "w") as tf:
        tarballs.tar_reproducible(
            tar=tf,
            basedir=build_dir,
            prefix=sdist_root,
            arcname_root="mypkg-1.0",
        )
    with tarfile.open(t1, "r") as tf:
        names = tf.getnames()

    # All entries should be rooted at mypkg-1.0, not python/
    # This ensures the sdist unpacks to mypkg-1.0/, not python/
    assert "mypkg-1.0" in names[0]
    assert "python" not in names[0]  # build_dir's name should not appear
    assert "mypkg-1.0/setup.py" in names
