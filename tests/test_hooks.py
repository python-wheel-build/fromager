from __future__ import annotations

import pathlib
import typing
from importlib.metadata import EntryPoint
from unittest.mock import MagicMock, Mock, patch

import pytest
from packaging.requirements import Requirement

from fromager import hooks


@pytest.fixture(autouse=True)
def _clear_hook_cache() -> typing.Generator[None, None, None]:
    hooks._mgrs.clear()
    yield
    hooks._mgrs.clear()


def _make_fake_ext(plugin: typing.Callable[..., typing.Any]) -> Mock:
    ext = Mock()
    ext.plugin = plugin
    return ext


def _make_fake_mgr(plugins: list[typing.Callable[..., typing.Any]]) -> MagicMock:
    """Return a mock HookManager that iterates over the given plugins."""
    fake_mgr = MagicMock()
    fake_mgr.names.return_value = [p.__name__ for p in plugins]
    fake_mgr.__iter__ = lambda self: iter([_make_fake_ext(p) for p in plugins])
    return fake_mgr


def test_die_on_plugin_load_failure_raises() -> None:
    ep = EntryPoint(name="bad_plugin", value="some.module:func", group="fromager.hooks")
    original_err = ImportError("no such module")

    with pytest.raises(RuntimeError, match="bad_plugin") as exc_info:
        hooks._die_on_plugin_load_failure(
            mgr=Mock(),
            ep=ep,
            err=original_err,
        )

    assert exc_info.value.__cause__ is original_err


@patch("fromager.hooks.hook.HookManager")
def test_get_hooks_creates_manager(mock_hm_cls: Mock) -> None:
    fake_mgr = MagicMock()
    fake_mgr.names.return_value = ["my_hook"]
    mock_hm_cls.return_value = fake_mgr

    result = hooks._get_hooks("post_build")

    mock_hm_cls.assert_called_once_with(
        namespace="fromager.hooks",
        name="post_build",
        invoke_on_load=False,
        on_load_failure_callback=hooks._die_on_plugin_load_failure,
    )
    assert result is fake_mgr


@patch("fromager.hooks.hook.HookManager")
def test_get_hooks_returns_cached(mock_hm_cls: Mock) -> None:
    fake_mgr = MagicMock()
    fake_mgr.names.return_value = ["my_hook"]
    mock_hm_cls.return_value = fake_mgr

    first = hooks._get_hooks("post_build")
    second = hooks._get_hooks("post_build")

    mock_hm_cls.assert_called_once()
    assert first is second


@patch("fromager.hooks._get_hooks")
def test_run_post_build_hooks_exception_propagates(mock_get: Mock) -> None:
    def bad_plugin(**kwargs: typing.Any) -> None:
        raise ValueError("hook failed")

    mock_get.return_value = _make_fake_mgr([bad_plugin])

    with pytest.raises(ValueError, match="hook failed"):
        hooks.run_post_build_hooks(
            ctx=Mock(),
            req=Requirement("pkg"),
            dist_name="pkg",
            dist_version="1.0",
            sdist_filename=pathlib.Path("/tmp/a.tar.gz"),
            wheel_filename=pathlib.Path("/tmp/a.whl"),
        )


@patch("fromager.hooks._get_hooks")
def test_run_post_build_hooks_calls_plugin(mock_get: Mock) -> None:
    called_with: dict[str, typing.Any] = {}

    def fake_plugin(**kwargs: typing.Any) -> None:
        called_with.update(kwargs)

    mock_get.return_value = _make_fake_mgr([fake_plugin])

    ctx = Mock()
    req = Requirement("numpy>=1.0")
    sdist = pathlib.Path("/tmp/numpy-1.0.tar.gz")
    wheel = pathlib.Path("/tmp/numpy-1.0-cp312-linux_x86_64.whl")

    hooks.run_post_build_hooks(
        ctx=ctx,
        req=req,
        dist_name="numpy",
        dist_version="1.0",
        sdist_filename=sdist,
        wheel_filename=wheel,
    )

    mock_get.assert_called_once_with("post_build")
    assert called_with["ctx"] is ctx
    assert called_with["req"] is req
    assert called_with["dist_name"] == "numpy"
    assert called_with["dist_version"] == "1.0"
    assert called_with["sdist_filename"] is sdist
    assert called_with["wheel_filename"] is wheel


@patch("fromager.hooks._get_hooks")
def test_run_post_bootstrap_hooks_exception_propagates(mock_get: Mock) -> None:
    def bad_plugin(**kwargs: typing.Any) -> None:
        raise ValueError("hook failed")

    mock_get.return_value = _make_fake_mgr([bad_plugin])

    with pytest.raises(ValueError, match="hook failed"):
        hooks.run_post_bootstrap_hooks(
            ctx=Mock(),
            req=Requirement("pkg"),
            dist_name="pkg",
            dist_version="1.0",
            sdist_filename=None,
            wheel_filename=None,
        )


@patch("fromager.hooks._get_hooks")
def test_run_post_bootstrap_hooks_calls_plugin(mock_get: Mock) -> None:
    called_with: dict[str, typing.Any] = {}

    def fake_plugin(**kwargs: typing.Any) -> None:
        called_with.update(kwargs)

    mock_get.return_value = _make_fake_mgr([fake_plugin])

    ctx = Mock()
    req = Requirement("flask>=2.0")

    hooks.run_post_bootstrap_hooks(
        ctx=ctx,
        req=req,
        dist_name="flask",
        dist_version="2.0",
        sdist_filename=None,
        wheel_filename=None,
    )

    mock_get.assert_called_once_with("post_bootstrap")
    assert called_with["ctx"] is ctx
    assert called_with["req"] is req
    assert called_with["dist_name"] == "flask"
    assert called_with["dist_version"] == "2.0"
    assert called_with["sdist_filename"] is None
    assert called_with["wheel_filename"] is None


@patch("fromager.hooks._get_hooks")
def test_run_prebuilt_wheel_hooks_exception_propagates(mock_get: Mock) -> None:
    def bad_plugin(**kwargs: typing.Any) -> None:
        raise ValueError("hook failed")

    mock_get.return_value = _make_fake_mgr([bad_plugin])

    with pytest.raises(ValueError, match="hook failed"):
        hooks.run_prebuilt_wheel_hooks(
            ctx=Mock(),
            req=Requirement("pkg"),
            dist_name="pkg",
            dist_version="1.0",
            wheel_filename=pathlib.Path("/tmp/a.whl"),
        )


@patch("fromager.hooks._get_hooks")
def test_run_prebuilt_wheel_hooks_calls_plugin(mock_get: Mock) -> None:
    called_with: dict[str, typing.Any] = {}

    def fake_plugin(**kwargs: typing.Any) -> None:
        called_with.update(kwargs)

    mock_get.return_value = _make_fake_mgr([fake_plugin])

    ctx = Mock()
    req = Requirement("torch>=2.0")
    wheel = pathlib.Path("/tmp/torch-2.0-cp312-linux_x86_64.whl")

    hooks.run_prebuilt_wheel_hooks(
        ctx=ctx,
        req=req,
        dist_name="torch",
        dist_version="2.0",
        wheel_filename=wheel,
    )

    mock_get.assert_called_once_with("prebuilt_wheel")
    assert called_with["ctx"] is ctx
    assert called_with["req"] is req
    assert called_with["dist_name"] == "torch"
    assert called_with["dist_version"] == "2.0"
    assert called_with["wheel_filename"] is wheel
    assert "sdist_filename" not in called_with


@patch("fromager.hooks.overrides._get_dist_info", return_value=("mypkg", "1.0.0"))
@patch("fromager.hooks.extension.ExtensionManager")
def test_log_hooks_logs_each_extension(
    mock_em_cls: Mock,
    mock_dist_info: Mock,
) -> None:
    ext_a = Mock()
    ext_a.name = "post_build"
    ext_a.module_name = "my_plugins.hooks"

    ext_b = Mock()
    ext_b.name = "post_bootstrap"
    ext_b.module_name = "other_plugins.hooks"

    mock_em_cls.return_value = [ext_a, ext_b]

    hooks.log_hooks()

    mock_em_cls.assert_called_once_with(
        namespace="fromager.hooks",
        invoke_on_load=False,
        on_load_failure_callback=hooks._die_on_plugin_load_failure,
    )
    assert mock_dist_info.call_count == 2
    mock_dist_info.assert_any_call("my_plugins.hooks")
    mock_dist_info.assert_any_call("other_plugins.hooks")
