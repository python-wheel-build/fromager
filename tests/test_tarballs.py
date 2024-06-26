import tarfile

from fromager import tarballs


def test_modes_change(tmp_path):
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
