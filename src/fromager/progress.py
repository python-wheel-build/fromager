import sys
import typing

import tqdm as _tqdm

__all__ = ("progress",)


def progress(it: typing.Iterable, *, unit="pkg", **kwargs: typing.Any) -> typing.Any:
    """tqdm progress bar"""
    if not sys.stdout.isatty():
        # wider progress bar in CI
        kwargs.setdefault("ncols", 78)
    yield from _tqdm.tqdm(it, unit=unit, **kwargs)
