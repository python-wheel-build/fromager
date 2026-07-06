from __future__ import annotations

import abc
import concurrent.futures
import logging
import typing

from ._types import BootstrapPhase
from ._work_item import WorkItem

if typing.TYPE_CHECKING:
    from ._bootstrapper import Bootstrapper

logger = logging.getLogger(__name__)


class Phase(abc.ABC):
    """Abstract base for items pushed onto the bootstrap stack.

    Each subclass encodes one phase of the bootstrap pipeline.
    Wraps a ``WorkItem`` (accumulated per-package state) and implements
    the processing logic for that phase in ``run()``.
    """

    phase: typing.ClassVar[BootstrapPhase]
    tracks_why: typing.ClassVar[bool] = True

    def __init_subclass__(cls, **kwargs: typing.Any) -> None:
        super().__init_subclass__(**kwargs)
        # Enforce that every concrete subclass defines `phase`.  Abstract
        # subclasses (those that still have unimplemented abstract methods)
        # are allowed to omit it; they will be checked when their own concrete
        # subclasses are defined.
        #
        # Note: ABCMeta sets __abstractmethods__ *after* __init_subclass__
        # runs, so we cannot rely on it here.  Instead we inspect the class's
        # MRO for any attribute still marked as abstract.
        is_abstract = any(
            getattr(getattr(cls, attr, None), "__isabstractmethod__", False)
            for attr in dir(cls)
        )
        if not is_abstract and "phase" not in cls.__dict__:
            raise TypeError(f"{cls.__name__} must define the 'phase' class attribute")

    def __init__(self, work_item: WorkItem) -> None:
        self.work_item = work_item
        self.bg_future: concurrent.futures.Future[typing.Any] | None = None

    @abc.abstractmethod
    def run(self, bt: Bootstrapper) -> list[Phase]: ...

    @property
    def requires_exclusive_run(self) -> bool:
        """Return True if this item must run without concurrent background I/O.

        When True, the bootstrap loop drains the background thread pool before
        calling ``run()``. Override in subclasses that require exclusive access.
        """
        return False

    def background_work(
        self, bt: Bootstrapper
    ) -> typing.Callable[[], typing.Any] | None:
        """Return a zero-argument callable for background I/O, or None.

        Override in subclasses that need background prefetching.
        ``bt`` is provided so subclasses can capture Bootstrapper state
        (e.g. resolver, ctx) into the returned closure without storing
        a circular reference on the item itself.
        """
        return None

    def __str__(self) -> str:
        """Human-readable representation: ``"<ClassName>(<req>)"``."""
        wi = self.work_item
        return f"{type(self).__name__}({wi.req})"

    def as_json(self) -> dict[str, typing.Any]:
        """Return a JSON-serialisable dict for stack-state recording."""
        wi = self.work_item
        return {
            "req": str(wi.req),
            "req_type": str(wi.req_type),
            "phase": str(self.phase),
            "resolved_version": str(wi.resolved_version)
            if wi.resolved_version is not None
            else None,
            "source_url": wi.source_url,
            "build_sdist_only": wi.build_sdist_only,
            "why": [
                {"req_type": str(rt), "req": str(r), "version": str(v)}
                for rt, r, v in wi.why_snapshot
            ],
            "parent": (
                {"req": str(wi.parent[0]), "version": str(wi.parent[1])}
                if wi.parent
                else None
            ),
            "build_system_deps": sorted(str(r) for r in wi.build_system_deps),
            "build_backend_deps": sorted(str(r) for r in wi.build_backend_deps),
            "build_sdist_deps": sorted(str(r) for r in wi.build_sdist_deps),
        }
