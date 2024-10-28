from unittest import mock
from unittest.mock import patch

import pytest

from fromager import overrides


def test_invoke_override_with_exact_args():
    def foo(arg1, arg2):
        return arg1 is not None and arg2 is not None

    assert overrides.invoke(foo, arg1="value1", arg2="value2")


def test_invoke_override_with_more_args_than_needed():
    def foo(arg1, arg2):
        return arg1 is not None and arg2 is not None

    assert overrides.invoke(foo, arg1="value1", arg2="value2", arg3="value3")


def test_invoke_override_with_not_enough_args():
    def foo(arg1, arg2):
        return arg1 is not None and arg2 is not None

    with pytest.raises(TypeError):
        overrides.invoke(foo, arg1="value1")


@patch("fromager.overrides.find_override_method")
def test_find_and_invoke(
    find_override_method: mock.Mock,
):
    def default_foo(arg1):
        return arg1 is not None

    find_override_method.return_value = None

    assert overrides.find_and_invoke(
        "pkg", "foo", default_foo, arg1="value1", arg2="value2"
    )
