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
