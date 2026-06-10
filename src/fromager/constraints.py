import logging
import pathlib
import typing
from collections.abc import Generator

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version

from . import requirements_file

logger = logging.getLogger(__name__)


def _is_blocked_specifier(specifier: SpecifierSet) -> bool:
    """Return True if specifier blocks a package entirely.

    The convention ``<0``, ``<0.0``, or ``<0.0.0`` is used to mark a
    package as blocked so that no version can satisfy the constraint.
    """
    specs = list(specifier)
    return (
        len(specs) == 1
        and specs[0].operator == "<"
        and Version(specs[0].version) == Version("0")
    )


def _format_provenance(provenance: dict[str, list[str]]) -> str:
    """Format a per-package provenance dict as a human-readable string.

    Args:
        provenance: Mapping of source file to original constraint lines.

    Returns:
        Formatted string, e.g.
        ``"/path/to/base.txt (>=2.0), /path/to/override.txt (!=2.1.1)"``.
    """
    parts: list[str] = []
    for source, lines in provenance.items():
        specifiers = ", ".join(str(Requirement(line).specifier) for line in lines)
        parts.append(f"{source} ({specifiers})")
    return ", ".join(parts)


class InvalidConstraintError(ValueError):
    pass


class Constraints:
    def __init__(self) -> None:
        # mapping of canonical names to requirements
        # NOTE: Requirement.name is not normalized
        self._data: dict[NormalizedName, Requirement] = {}
        # per-package provenance: {canonical_name: {source_file: [original_lines]}}
        self._provenance: dict[NormalizedName, dict[str, list[str]]] = {}

    def __iter__(self) -> Generator[NormalizedName, None, None]:
        yield from self._data

    def __bool__(self) -> bool:
        return bool(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def add_constraint(self, unparsed: str, *, source: str) -> None:
        """Add new constraint, must not conflict with any existing constraints.

        Args:
            unparsed: Raw constraint string, e.g. ``"foo>=2.0"``.
            source: Path or URL of the file that contains this constraint.
                Required for provenance tracking.

        .. versionchanged:: 0.83.0
           Non-conflicting constraints are now combined. Constraints with
           conflicts now raise :exc:`InvalidConstraintError`. Inputs without a
           version specifier or with extras or url are also refused.

        .. versionchanged:: 0.84.0
           Added *source* parameter for provenance tracking.
        """
        req = Requirement(unparsed)
        canon_name = canonicalize_name(req.name)
        previous = self._data.get(canon_name)

        # validator properties: must have a specifier, must not have extras or URL
        if req.extras:
            raise InvalidConstraintError(f"Constraint {unparsed!r} has extras")
        if req.url:
            raise InvalidConstraintError(f"Constraint {unparsed!r} has an url")
        if not req.specifier:
            raise InvalidConstraintError(f"Constraint {unparsed!r} has no specifiers")

        # A "blocked" specifier (<0, <0.0, <0.0.0) is intentionally
        # unsatisfiable and used to exclude a package from builds.
        blocked = _is_blocked_specifier(req.specifier)

        # verify that incoming constraint is okay by itself
        if not blocked and req.specifier.is_unsatisfiable():
            raise InvalidConstraintError(f"Constraint {unparsed!r} is unsatisfiable")

        if not requirements_file.evaluate_marker(req, req):
            logger.debug(f"Constraint {req} does not match environment")
            return

        if previous is not None:
            prev_blocked = _is_blocked_specifier(previous.specifier)
            if blocked != prev_blocked:
                prev_prov = _format_provenance(self._provenance.get(canon_name, {}))
                raise InvalidConstraintError(
                    f"Cannot combine blocked and non-blocked constraints "
                    f"(existing: {previous} from {prev_prov}, "
                    f"new: {req} from {source})"
                )
            if not blocked:
                logger.debug("combining constraints %s and %s", previous, req)
                new_specifier = req.specifier & previous.specifier
                if new_specifier.is_unsatisfiable():
                    prev_prov = _format_provenance(self._provenance.get(canon_name, {}))
                    raise InvalidConstraintError(
                        f"Combined specifier '{new_specifier}' is not satisfiable "
                        f"(existing: {previous} from {prev_prov}, "
                        f"new: {req} from {source})"
                    )
                req.specifier = new_specifier
        else:
            logger.debug(f"adding constraint {req}")

        self._data[canon_name] = req
        pkg_prov = self._provenance.setdefault(canon_name, {})
        pkg_prov.setdefault(source, []).append(unparsed)

    def load_constraints_file(self, constraints_file: str | pathlib.Path) -> None:
        """Load constraints from a constraints file or URL."""
        logger.info("loading constraints from %s", constraints_file)
        source = str(constraints_file)
        content = requirements_file.parse_requirements_file(constraints_file)
        for line in content:
            self.add_constraint(line, source=source)

    def dump_constraints(self, output: typing.TextIO) -> None:
        """Dump combined constraints to a text stream.

        Each line includes an inline comment showing which source file(s)
        contributed each specifier.

        Args:
            output: Writable text stream.

        .. versionchanged:: 0.84.0
           Output now includes per-line provenance comments.
        """
        # sort by normalized name, write requirement without markers.
        # They have been evaluated in add_constraint()
        for name, req in sorted(self._data.items()):
            line = f"{req.name}{req.specifier}"
            prov = self._provenance.get(name, {})
            if prov:
                line = f"{line}  # {_format_provenance(prov)}"
            output.write(f"{line}\n")

    def get_constraint(self, name: str) -> Requirement | None:
        """Return the merged constraint for *name*, or ``None``."""
        return self._data.get(canonicalize_name(name))

    def get_provenance(self, name: str) -> dict[str, list[str]]:
        """Return provenance info for *name*.

        Returns:
            Mapping of ``{source_file: [original_constraint_lines]}``,
            or an empty dict if the package has no constraints.

        .. versionadded:: 0.84.0
        """
        prov = self._provenance.get(canonicalize_name(name), {})
        return {source: list(lines) for source, lines in prov.items()}

    def allow_prerelease(self, pkg_name: str) -> bool:
        """Return ``True`` if the constraint for *pkg_name* allows prereleases."""
        constraint = self.get_constraint(pkg_name)
        if constraint:
            return bool(constraint.specifier.prereleases)
        return False

    def is_blocked(self, pkg_name: str) -> bool:
        """Return True if the package is blocked by a ``<0`` constraint."""
        constraint = self.get_constraint(pkg_name)
        if constraint:
            return _is_blocked_specifier(constraint.specifier)
        return False

    def is_satisfied_by(self, pkg_name: str, version: Version) -> bool:
        """Return ``True`` if *version* satisfies the constraint for *pkg_name*."""
        constraint = self.get_constraint(pkg_name)
        if constraint:
            return constraint.specifier.contains(version, prereleases=True)
        return True
