from __future__ import annotations

import logging

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import context, metrics


@metrics.timeit(description="test description")
def _test_func(
    *,
    ctx: context.WorkContext,
    req: Requirement | None = None,
    version: str | None = None,
) -> str:
    return "ok"


@metrics.timeit(description="test description")
def _test_returns_version(
    *,
    ctx: context.WorkContext,
    req: Requirement | None = None,
) -> tuple[str, Version]:
    return ("http://example.com", Version("1.2.3"))


@metrics.timeit(description="test description")
def _test_raises(
    *,
    ctx: context.WorkContext,
    req: Requirement | None = None,
    version: str | None = None,
) -> None:
    raise RuntimeError("test error")


def test_timeit_stores_timing(tmp_context: context.WorkContext) -> None:
    req = Requirement("numpy>=1.0")

    _test_func(ctx=tmp_context, req=req, version="1.26.0")

    key = "numpy==1.26.0"
    assert key in tmp_context.time_store
    assert tmp_context.time_store[key]["_test_func"] > 0


def test_timeit_stores_description(tmp_context: context.WorkContext) -> None:
    _test_func(ctx=tmp_context)

    assert tmp_context.time_description_store["_test_func"] == "test description"


def test_timeit_no_storage_without_req(tmp_context: context.WorkContext) -> None:
    _test_func(ctx=tmp_context, req=None, version="1.0")

    assert len(tmp_context.time_store) == 0


def test_timeit_no_storage_without_version(tmp_context: context.WorkContext) -> None:
    req = Requirement("numpy>=1.0")

    _test_func(ctx=tmp_context, req=req)

    assert len(tmp_context.time_store) == 0


def test_timeit_returns_original_result(tmp_context: context.WorkContext) -> None:
    result = _test_func(ctx=tmp_context)

    assert result == "ok"


def test_timeit_extracts_version_from_return(
    tmp_context: context.WorkContext,
) -> None:
    req = Requirement("mypkg")

    _test_returns_version(ctx=tmp_context, req=req)

    assert "mypkg==1.2.3" in tmp_context.time_store


def test_timeit_propagates_exception(tmp_context: context.WorkContext) -> None:
    with pytest.raises(RuntimeError, match="test error"):
        _test_raises(ctx=tmp_context)


def test_timeit_no_storage_on_exception(tmp_context: context.WorkContext) -> None:
    req = Requirement("numpy>=1.0")

    with pytest.raises(RuntimeError):
        _test_raises(ctx=tmp_context, req=req, version="1.0")

    assert len(tmp_context.time_store) == 0


def test_summarize_logs_timing(
    tmp_context: context.WorkContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    req = Requirement("numpy>=1.0")
    _test_func(ctx=tmp_context, req=req, version="1.26.0")

    with caplog.at_level(logging.INFO, logger="fromager.metrics"):
        metrics.summarize(tmp_context, "Building")

    records = [r for r in caplog.records if r.name == "fromager.metrics"]
    assert len(records) == 1
    msg = records[0].message
    assert "Building" in msg
    assert "numpy==1.26.0" in msg
    assert "test description" in msg


def test_summarize_empty(
    tmp_context: context.WorkContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="fromager.metrics"):
        metrics.summarize(tmp_context, "Building")

    assert len(caplog.records) == 0


def test_extract_version_from_tuple() -> None:
    ret = ("http://example.com", Version("2.0.0"))
    assert metrics._extract_version_from_return(ret) == Version("2.0.0")


def test_extract_version_bare() -> None:
    ret = Version("3.0.0")
    assert metrics._extract_version_from_return(ret) == Version("3.0.0")


def test_extract_version_no_version_in_iterable() -> None:
    ret = ("http://example.com", "not-a-version")
    assert metrics._extract_version_from_return(ret) is None


def test_extract_version_non_iterable() -> None:
    assert metrics._extract_version_from_return(42) is None


def test_extract_version_none() -> None:
    assert metrics._extract_version_from_return(None) is None
