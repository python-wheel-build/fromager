from packaging.version import Version

from fromager import local_version


def test_replace_local_version() -> None:
    assert local_version.update_local_version(Version("1.2"), "newval") == Version(
        "1.2+newval"
    )
    assert local_version.update_local_version(
        Version("1.2+oldval"), "newval"
    ) == Version("1.2+oldval.newval")
    assert local_version.update_local_version(Version("1.2"), None) == Version("1.2")
