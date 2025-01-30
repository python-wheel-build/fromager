import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager.versionmap import VersionMap


def test_initialize():
    m = VersionMap(
        {
            "1.2": "value for 1.2",
            Version("1.3"): "value for 1.3",
            "1.0": "value for 1.0",
        }
    )
    assert list(m.versions()) == [Version("1.3"), Version("1.2"), Version("1.0")]


def test_lookup():
    m = VersionMap(
        {
            "1.2": "value for 1.2",
            Version("1.3"): "value for 1.3",
            "1.0": "value for 1.0",
        }
    )
    assert m.lookup(Requirement("pkg")) == (Version("1.3"), "value for 1.3")
    assert m.lookup(Requirement("pkg>1.0")) == (Version("1.3"), "value for 1.3")
    assert m.lookup(Requirement("pkg<1.3")) == (Version("1.2"), "value for 1.2")


def test_prerelease():
    m = VersionMap(
        {
            Version("0.4.1b0"): "value for 0.4.1b0",
            "1.2": "value for 1.2",
            Version("1.3"): "value for 1.3",
            "1.0": "value for 1.0",
            "1.5.0a0": "value for 1.5.0a0",
        }
    )
    assert m.lookup(Requirement("pkg")) == (Version("1.3"), "value for 1.3")
    assert m.lookup(Requirement("pkg>1.0")) == (Version("1.3"), "value for 1.3")
    assert m.lookup(Requirement("pkg<1.3")) == (Version("1.2"), "value for 1.2")
    assert m.lookup(Requirement("pkg"), allow_prerelease=True) == (
        Version("1.5.0a0"),
        "value for 1.5.0a0",
    )
    with pytest.raises(ValueError):
        assert (
            m.lookup(Requirement("pkg"), Requirement("pkg<1.0")) == "value for 0.4.1b"
        )
    assert m.lookup(
        Requirement("pkg"), Requirement("pkg<1.0"), allow_prerelease=True
    ) == (Version("0.4.1b0"), "value for 0.4.1b0")


def test_only_prerelease():
    m = VersionMap(
        {
            Version("0.4.1b0"): "value for 0.4.1b0",
            Version("0.6b0"): "value for 0.6b0",
        }
    )
    assert m.lookup(
        Requirement("pkg"), constraint=Requirement("pkg<0.6b"), allow_prerelease=True
    ) == (
        Version("0.4.1b0"),
        "value for 0.4.1b0",
    )


def test_with_constraint():
    m = VersionMap(
        {
            "1.2": "value for 1.2",
            Version("1.3"): "value for 1.3",
            "1.0": "value for 1.0",
        }
    )
    assert m.lookup(Requirement("pkg"), Requirement("pkg<1.3")) == (
        Version("1.2"),
        "value for 1.2",
    )
    assert m.lookup(Requirement("pkg>1.0"), Requirement("pkg==1.2")) == (
        Version("1.2"),
        "value for 1.2",
    )


def test_no_match():
    m = VersionMap(
        {
            "1.2": "value for 1.2",
            Version("1.3"): "value for 1.3",
            "1.0": "value for 1.0",
        }
    )
    with pytest.raises(ValueError):
        m.lookup(Requirement("pkg"), Requirement("pkg<1.0"))
    with pytest.raises(ValueError):
        m.lookup(Requirement("pkg>1.0"), Requirement("pkg<1.0"))
