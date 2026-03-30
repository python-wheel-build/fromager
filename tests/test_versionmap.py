import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager.versionmap import VersionMap


def test_initialize() -> None:
    m = VersionMap(
        {
            Version("1.2"): "value for 1.2",
            Version("1.3"): "value for 1.3",
            Version("1.0"): "value for 1.0",
        }
    )
    assert list(m.versions()) == [Version("1.3"), Version("1.2"), Version("1.0")]
    assert list(m.iter_pairs()) == [
        (Version("1.3"), "value for 1.3"),
        (Version("1.2"), "value for 1.2"),
        (Version("1.0"), "value for 1.0"),
    ]


def test_lookup() -> None:
    m = VersionMap(
        {
            Version("1.2"): "value for 1.2",
            Version("1.3"): "value for 1.3",
            Version("1.0"): "value for 1.0",
        }
    )
    assert m.lookup(Requirement("pkg")) == (Version("1.3"), "value for 1.3")
    assert m.lookup(Requirement("pkg>1.0")) == (Version("1.3"), "value for 1.3")
    assert m.lookup(Requirement("pkg<1.3")) == (Version("1.2"), "value for 1.2")


def test_prerelease() -> None:
    m = VersionMap(
        {
            Version("0.4.1b0"): "value for 0.4.1b0",
            Version("1.2"): "value for 1.2",
            Version("1.3"): "value for 1.3",
            Version("1.0"): "value for 1.0",
            Version("1.5.0a0"): "value for 1.5.0a0",
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


def test_only_prerelease() -> None:
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


def test_with_constraint() -> None:
    m = VersionMap(
        {
            Version("1.2"): "value for 1.2",
            Version("1.3"): "value for 1.3",
            Version("1.0"): "value for 1.0",
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


def test_no_match() -> None:
    m = VersionMap(
        {
            Version("1.2"): "value for 1.2",
            Version("1.3"): "value for 1.3",
            Version("1.0"): "value for 1.0",
        }
    )
    with pytest.raises(ValueError):
        m.lookup(Requirement("pkg"), Requirement("pkg<1.0"))
    with pytest.raises(ValueError):
        m.lookup(Requirement("pkg>1.0"), Requirement("pkg<1.0"))


def test_getitem() -> None:
    m = VersionMap(
        {
            Version("1.2"): "value for 1.2",
            Version("1.3"): "value for 1.3",
            Version("1.0"): "value for 1.0",
        }
    )
    assert m[Version("1.2")] == "value for 1.2"
    assert m[Version("1.3")] == "value for 1.3"

    with pytest.raises(KeyError):
        m[Version("2.0")]


def test_str_keys_rejected() -> None:
    m: VersionMap = VersionMap()
    with pytest.raises(TypeError, match="Version"):
        m.add("1.0", "x")  # type: ignore[arg-type]
    m_clean = VersionMap({Version("1.0"): "ok"})
    with pytest.raises(TypeError, match="Version"):
        _ = m_clean["1.0"]  # type: ignore[index]


def test_mapping_interface() -> None:
    m = VersionMap(
        {
            Version("1.2"): "a",
            Version("1.0"): "b",
        }
    )
    assert len(m) == 2
    assert Version("1.2") in m
    assert list(m.keys()) == [Version("1.2"), Version("1.0")]
    assert list(m.values()) == ["a", "b"]
    assert list(m.items()) == [(Version("1.2"), "a"), (Version("1.0"), "b")]
