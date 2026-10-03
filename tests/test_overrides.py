import typing
from unittest import mock
from unittest.mock import patch

import pytest

from fromager import overrides


def test_invoke_override_with_exact_args() -> None:
    def foo(arg1: typing.Any, arg2: typing.Any) -> bool:
        return arg1 is not None and arg2 is not None

    assert overrides.invoke(foo, arg1="value1", arg2="value2")


def test_invoke_override_with_more_args_than_needed() -> None:
    def foo(arg1: typing.Any, arg2: typing.Any) -> bool:
        return arg1 is not None and arg2 is not None

    assert overrides.invoke(foo, arg1="value1", arg2="value2", arg3="value3")


def test_invoke_override_with_not_enough_args() -> None:
    def foo(arg1: typing.Any, arg2: typing.Any) -> bool:
        return arg1 is not None and arg2 is not None

    with pytest.raises(TypeError):
        overrides.invoke(foo, arg1="value1")


@patch("fromager.overrides.find_override_method")
def test_find_and_invoke(
    find_override_method: mock.Mock,
) -> None:
    def default_foo(arg1: typing.Any) -> bool:
        return arg1 is not None

    find_override_method.return_value = None

    assert overrides.find_and_invoke(
        "pkg", "foo", default_foo, arg1="value1", arg2="value2"
    )


def test_list_hooks() -> None:
    hooks = overrides.OverrideHookProtocol.list_hooks()
    assert isinstance(hooks, list)
    assert len(hooks) == 13


def test_get_default_unknown_hook() -> None:
    with pytest.raises(KeyError):
        overrides.OverrideHookProtocol.get_default("no_such_hook")


def test_check_signature_matching() -> None:
    def build_wheel(
        ctx: typing.Any,
        build_env: typing.Any,
        extra_environ: typing.Any,
        req: typing.Any,
        sdist_root_dir: typing.Any,
        version: typing.Any,
        build_dir: typing.Any,
    ) -> None:
        pass

    overrides.OverrideHookProtocol.check_signature(build_wheel)


def test_check_signature_unknown_hook() -> None:
    def no_such_hook() -> None:
        pass

    with pytest.raises(KeyError):
        overrides.OverrideHookProtocol.check_signature(no_such_hook)


def test_check_signature_args_mismatch() -> None:
    def build_wheel(ctx: typing.Any) -> None:
        pass

    with pytest.raises(TypeError, match="argument names mismatch"):
        overrides.OverrideHookProtocol.check_signature(build_wheel)


@pytest.mark.parametrize("hook_name", overrides.OverrideHookProtocol.list_hooks())
def test_protocol_signature_matches_default(hook_name: str) -> None:
    default_fn = overrides.OverrideHookProtocol.get_default(hook_name)
    assert callable(default_fn)
    overrides.OverrideHookProtocol.check_signature(default_fn, hook_name=hook_name)
