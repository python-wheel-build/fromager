import click
import pytest

from fromager.commands import build


def test_validate_local_version() -> None:
    assert build.validate_local_version(None, None, None) is None
    assert "1.2" == build.validate_local_version(None, None, "1.2")
    assert "1.2" == build.validate_local_version(None, None, "+1.2 ")  # cleanups
    assert "sometext" == build.validate_local_version(None, None, "sometext")
    assert "some.text" == build.validate_local_version(None, None, "some-text")
    with pytest.raises(click.BadParameter):
        build.validate_local_version(None, None, ".1.2")
    with pytest.raises(click.BadParameter):
        build.validate_local_version(None, None, ".some.text")
