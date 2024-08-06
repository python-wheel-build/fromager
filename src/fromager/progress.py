import sys
import typing
from types import TracebackType

import tqdm as _tqdm

__all__ = ("progress",)

# fix for runtime errors caused by inheriting classes that are generic in stubs but not runtime
# https://mypy.readthedocs.io/en/latest/runtime_troubles.html#using-classes-that-are-generic-in-stubs-but-not-at-runtime
if typing.TYPE_CHECKING:
    ProgressBarTqdm = _tqdm.tqdm[int] | _tqdm.tqdm[typing.Never] | None
else:
    ProgressBarTqdm = _tqdm.tqdm | None


class Progressbar:
    def __init__(self, tqdm: ProgressBarTqdm) -> None:
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

    def __exit__(
        self,
        typ: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._tqdm is not None:
            self._tqdm.__exit__(typ, value, traceback)


def progress(
    it: typing.Iterable[typing.Any], *, unit: str = "pkg", **kwargs: typing.Any
) -> typing.Any:
    """tqdm progress bar"""
    if not sys.stdout.isatty():
        # wider progress bar in CI
        kwargs.setdefault("ncols", 78)
    yield from _tqdm.tqdm(it, unit=unit, **kwargs)


def progress_context(
    total: int, *, unit: str = "pkg", **kwargs: typing.Any
) -> Progressbar:
    """Context manager for progress bar with dynamic updates"""
    if not sys.stdout.isatty():
        # wider progress bar in CI
        kwargs.setdefault("ncols", 78)
    return Progressbar(_tqdm.tqdm(None, total=total, unit=unit, **kwargs))
