from __future__ import annotations

import typing

from ._phase_item import PhaseItem
from ._types import BootstrapPhase

if typing.TYPE_CHECKING:
    from ._bootstrapper import Bootstrapper


class CompleteItem(PhaseItem):
    """COMPLETE phase: clean up build directories."""

    phase: typing.ClassVar[BootstrapPhase] = BootstrapPhase.COMPLETE
    tracks_why: typing.ClassVar[bool] = True

    def run(self, bt: Bootstrapper) -> list[PhaseItem]:
        """COMPLETE phase: clean up build directories.

        Returns:
            Empty list (processing finished for this item).
        """
        wi = self.work_item
        if wi.build_result is not None:
            bt.ctx.clean_build_dirs(
                wi.build_result.sdist_root_dir,
                wi.build_result.build_env,
            )
        return []
