import os
import sys

import pytest
from packaging.tags import Tag, sys_tags
from packaging.utils import parse_wheel_filename

from fromager.wheel_tags import (
    cpython_target_tags,
    current_cpython_tag,
    find_cpython_binary,
    parse_cpython_tag,
)


def test_matches_sys_tags() -> None:
    """Both default and explicit arguments reproduce sys_tags output."""
    expected = list(sys_tags())
    assert list(cpython_target_tags()) == expected

    free_threaded = "t" in getattr(sys, "abiflags", "")
    explicit = list(
        cpython_target_tags(
            python_version=sys.version_info[:2],
            free_threaded=free_threaded,
        )
    )
    assert explicit == expected


@pytest.mark.parametrize(
    "free_threaded, expected_abi, expected_stable, absent_stable",
    [
        (True, "cp314t", "abi3t", "abi3"),
        (False, "cp314", "abi3", "abi3t"),
    ],
    ids=["free-threaded", "gil-enabled"],
)
def test_abi_tags(
    free_threaded: bool,
    expected_abi: str,
    expected_stable: str,
    absent_stable: str,
) -> None:
    """Free-threaded and GIL-enabled targets get correct ABI and stable ABI."""
    tags = list(
        cpython_target_tags(
            python_version=(3, 14),
            free_threaded=free_threaded,
            platforms=["linux_x86_64"],
        )
    )
    first = tags[0]
    assert first.interpreter == "cp314"
    assert first.abi == expected_abi

    abi_values = {t.abi for t in tags}
    assert expected_stable in abi_values
    assert absent_stable not in abi_values


def test_version_and_platform() -> None:
    """Custom python_version and platforms are respected."""
    tags = list(
        cpython_target_tags(
            python_version=(3, 13),
            free_threaded=False,
            platforms=["linux_aarch64"],
        )
    )
    interpreters = {t.interpreter for t in tags}
    assert "cp313" in interpreters
    if sys.version_info[:2] != (3, 13):
        running = f"cp{sys.version_info[0]}{sys.version_info[1]}"
        assert running not in interpreters

    platform_values = {t.platform for t in tags}
    assert platform_values == {"linux_aarch64", "any"}


# -- Python 3.15 and multi-ABI wheels ----------------------------------


def test_python_315_stable_abis() -> None:
    """3.15 GIL uses abi3 and free-threaded uses abi3t (PEP 803)."""
    platform = "linux_x86_64"
    gil_tags = list(
        cpython_target_tags(
            python_version=(3, 15),
            free_threaded=False,
            platforms=[platform],
        )
    )
    ft_tags = list(
        cpython_target_tags(
            python_version=(3, 15),
            free_threaded=True,
            platforms=[platform],
        )
    )

    assert gil_tags[0] == Tag("cp315", "cp315", platform)
    assert Tag("cp315", "abi3", platform) in gil_tags
    assert not any(t.abi == "abi3t" for t in gil_tags)

    assert ft_tags[0] == Tag("cp315", "cp315t", platform)
    assert Tag("cp315", "abi3t", platform) in ft_tags
    assert not any(t.abi == "abi3" for t in ft_tags)


def test_multi_abi_wheel_matches_both_315_targets() -> None:
    """A cp315-abi3.abi3t wheel carries a tag for each 3.15 ABI."""
    platform = "linux_x86_64"
    _, _, _, wheel_tags = parse_wheel_filename(
        "example-1.0-cp315-abi3.abi3t-linux_x86_64.whl"
    )
    assert wheel_tags == frozenset(
        {
            Tag("cp315", "abi3", platform),
            Tag("cp315", "abi3t", platform),
        }
    )

    gil_tags = set(
        cpython_target_tags(
            python_version=(3, 15),
            free_threaded=False,
            platforms=[platform],
        )
    )
    ft_tags = set(
        cpython_target_tags(
            python_version=(3, 15),
            free_threaded=True,
            platforms=[platform],
        )
    )
    assert wheel_tags & gil_tags == {Tag("cp315", "abi3", platform)}
    assert wheel_tags & ft_tags == {Tag("cp315", "abi3t", platform)}


# -- parse_cpython_tag -------------------------------------------------


@pytest.mark.parametrize(
    "tag, expected_version, expected_ft",
    [
        ("cp312", (3, 12), False),
        ("cp314", (3, 14), False),
        ("cp314t", (3, 14), True),
        ("cp313t", (3, 13), True),
    ],
)
def test_parse_cpython_tag(
    tag: str, expected_version: tuple[int, int], expected_ft: bool
) -> None:
    """Valid cpXY[t] strings are parsed correctly."""
    version, free_threaded = parse_cpython_tag(tag)
    assert version == expected_version
    assert free_threaded == expected_ft


@pytest.mark.parametrize("tag", ["pp310", "cpython314", "cp", "314t", ""])
def test_parse_cpython_tag_invalid(tag: str) -> None:
    """Invalid strings raise ValueError."""
    with pytest.raises(ValueError, match="invalid CPython tag"):
        parse_cpython_tag(tag)


def test_parse_roundtrip_with_target_tags() -> None:
    """Parsed tag fed into cpython_target_tags produces correct first tag."""
    version, free_threaded = parse_cpython_tag("cp313t")
    tags = list(
        cpython_target_tags(
            python_version=version,
            free_threaded=free_threaded,
            platforms=["linux_x86_64"],
        )
    )
    first = tags[0]
    assert first.interpreter == "cp313"
    assert first.abi == "cp313t"


# -- current_cpython_tag -----------------------------------------------


def test_current_cpython_tag() -> None:
    """current_cpython_tag reflects the running interpreter."""
    verdot = f"{sys.version_info[0]}{sys.version_info[1]}"
    suffix = "t" if "t" in getattr(sys, "abiflags", "") else ""
    assert current_cpython_tag() == f"cp{verdot}{suffix}"


def test_current_cpython_tag_roundtrips() -> None:
    """current_cpython_tag output can be parsed back."""
    tag = current_cpython_tag()
    version, free_threaded = parse_cpython_tag(tag)
    assert version == sys.version_info[:2]
    assert free_threaded == ("t" in getattr(sys, "abiflags", ""))


# -- find_cpython_binary -----------------------------------------------


def test_find_cpython_binary_current(tmp_path: object) -> None:
    """Finding a binary for the current interpreter succeeds."""
    tag = current_cpython_tag()
    result = find_cpython_binary(tag)
    # The running interpreter should always be findable
    assert result is not None
    assert os.path.isfile(result)


def test_find_cpython_binary_returns_expected_name() -> None:
    """The returned path ends with the expected binary name."""
    result = find_cpython_binary("cp314")
    if result is not None:
        assert os.path.basename(result) == "python3.14"

    result = find_cpython_binary("cp314t")
    if result is not None:
        assert os.path.basename(result) == "python3.14t"


def test_find_cpython_binary_not_found() -> None:
    """A version that does not exist returns None."""
    assert find_cpython_binary("cp399") is None


def test_find_cpython_binary_invalid_tag() -> None:
    """An invalid tag string raises ValueError."""
    with pytest.raises(ValueError, match="invalid CPython tag"):
        find_cpython_binary("pp310")
