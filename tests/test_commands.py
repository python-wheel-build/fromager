import typing

import click

from fromager.commands import bootstrap, build


def get_option_names(cmd: click.Command) -> typing.Iterable[str]:
    return [o.name for o in cmd.params if o.name]


def test_bootstrap_parallel_options() -> None:
    expected: set[str] = set()
    expected.update(get_option_names(bootstrap.bootstrap))
    expected.update(get_option_names(build.build_parallel))
    # bootstrap-parallel enforces sdist_only=True and handles
    # graph_file internally.
    expected.discard("sdist_only")
    expected.discard("graph_file")
    expected.discard("test_mode")

    assert set(get_option_names(bootstrap.bootstrap_parallel)) == expected


def test_bootstrap_has_cache_manager_options() -> None:
    option_names = set(get_option_names(bootstrap.bootstrap))
    assert "use_cache_manager" in option_names
    assert "cache_allow_insecure" in option_names
