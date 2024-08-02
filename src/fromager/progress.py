import sys
import typing

import tqdm as _tqdm

__all__ = ("progress",)


class Progressbar:
    def __init__(self, tqdm: _tqdm.tqdm | None) -> None:
        self._tqdm = tqdm

    def update_total(self, n: int) -> None:
        if self._tqdm is not None and self._tqdm.total is not None:
            self._tqdm.total += n

    def update(self, n: int = 1) -> bool | None:
        if self._tqdm is not None:
            return self._tqdm.update(n)
        return None

    def __enter__(self) -> "Progressbar":
        if self._tqdm is not None:
            self._tqdm.__enter__()
        return self

    def __exit__(self, typ, value, traceback) -> None:
        if self._tqdm is not None:
            self._tqdm.__exit__(typ, value, traceback)


def progress(it: typing.Iterable, *, unit="pkg", **kwargs: typing.Any) -> typing.Any:
    """tqdm progress bar"""
    if not sys.stdout.isatty():
        # wider progress bar in CI
        kwargs.setdefault("ncols", 78)
    yield from _tqdm.tqdm(it, unit=unit, **kwargs)


def progress_context(total: int, *, unit="pkg", **kwargs: typing.Any) -> Progressbar:
    """Context manager for progress bar with dynamic updates"""
    if not sys.stdout.isatty():
        # wider progress bar in CI
        kwargs.setdefault("ncols", 78)
    return Progressbar(_tqdm.tqdm(None, total=total, unit=unit, **kwargs))
