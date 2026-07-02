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


def _format_provenance(sources: set[str]) -> str:
    """Format provenance sources as a human-readable string.

    Args:
        sources: Set of source file paths or URLs.

    Returns:
        Comma-separated string of sources, e.g.
        ``"/path/to/base.txt, /path/to/override.txt"``.
    """
    return ", ".join(sorted(sources))


class InvalidConstraintError(ValueError):
    pass


class Constraints:
    def __init__(self) -> None:
        # mapping of canonical names to (requirement, provenance sources)
        # NOTE: Requirement.name is not normalized
        self._data: dict[NormalizedName, tuple[Requirement, set[str]]] = {}

    def __iter__(self) -> Generator[NormalizedName, None, None]:
        yield from self._data

    def __bool__(self) -> bool:
        return bool(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def add_constraint(self, unparsed: str, *, provenance: str | None = None) -> None:
        """Add new constraint, must not conflict with any existing constraints.

        Args:
            unparsed: Raw constraint string, e.g. ``"foo>=2.0"``.
            provenance: Path or URL of the file that contains this
                constraint. Used for provenance tracking in error messages
                and merged output.

        .. versionchanged:: 0.83.0
           Non-conflicting constraints are now combined. Constraints with
           conflicts now raise :exc:`InvalidConstraintError`. Inputs without a
           version specifier or with extras or url are also refused.

        .. versionchanged:: 0.84.0
           Added *provenance* parameter for source file tracking.
        """
        req = Requirement(unparsed)
        canon_name = canonicalize_name(req.name)
        existing = self._data.get(canon_name)

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

        if existing is not None:
            previous, prev_sources = existing
            prev_blocked = _is_blocked_specifier(previous.specifier)
            prev_prov = _format_provenance(prev_sources)
            existing_desc = (
                f"{previous} from {prev_prov}" if prev_prov else str(previous)
            )
            new_desc = f"{req} from {provenance}" if provenance else str(req)
            if blocked != prev_blocked:
                raise InvalidConstraintError(
                    f"Cannot combine blocked and non-blocked constraints "
                    f"(existing: {existing_desc}, new: {new_desc})"
                )
            if not blocked:
                logger.debug("combining constraints %s and %s", previous, req)
                new_specifier = req.specifier & previous.specifier
                if new_specifier.is_unsatisfiable():
                    raise InvalidConstraintError(
                        f"Combined specifier '{new_specifier}' is not satisfiable "
                        f"(existing: {existing_desc}, new: {new_desc})"
                    )
                req.specifier = new_specifier
            sources = prev_sources
        else:
            logger.debug(f"adding constraint {req}")
            sources = set()

        if provenance is not None:
            sources.add(provenance)
        self._data[canon_name] = (req, sources)

    def load_constraints_file(self, constraints_file: str | pathlib.Path) -> None:
        """Load constraints from a constraints file or URL."""
        logger.info("loading constraints from %s", constraints_file)
        file_provenance = str(constraints_file)
        content = requirements_file.parse_requirements_file(constraints_file)
        for line in content:
            self.add_constraint(line, provenance=file_provenance)

    def dump_constraints(self, output: typing.TextIO) -> None:
        """Dump combined constraints to a text stream.

        Source files that contributed each constraint are listed as comment
        lines above the constraint line.

        Args:
            output: Writable text stream.

        .. versionchanged:: 0.84.0
           Output now includes provenance comments above each constraint.
        """
        # sort by normalized name, write requirement without markers.
        # They have been evaluated in add_constraint()
        for _name, (req, sources) in sorted(self._data.items()):
            for source in sorted(sources):
                output.write(f"# {source}\n")
            output.write(f"{req.name}{req.specifier}\n")

    def get_constraint(self, name: str) -> Requirement | None:
        """Return the merged constraint for *name*, or ``None``."""
        constraint_entry = self._data.get(canonicalize_name(name))
        if constraint_entry is not None:
            return constraint_entry[0]
        return None

    def get_constraint_with_provenance(
        self, name: str
    ) -> tuple[Requirement, set[str]] | tuple[None, None]:
        """Return the constraint and its provenance sources for *name*.

        Returns:
            ``(requirement, source_files)`` if constrained, or
            ``(None, None)`` if the package has no constraints.
            The returned set is a copy.

        .. versionadded:: 0.84.0
        """
        constraint_entry = self._data.get(canonicalize_name(name))
        if constraint_entry is not None:
            req, sources = constraint_entry
            return req, set(sources)
        return None, None

    def format_provenance(self, name: str) -> str:
        """Return a human-readable provenance string for *name*.

        Returns:
            Comma-separated list of source files, e.g.
            ``"/path/to/base.txt, /path/to/override.txt"``,
            or an empty string if the package has no constraints.

        .. versionadded:: 0.84.0
        """
        constraint_entry = self._data.get(canonicalize_name(name))
        if constraint_entry is not None:
            return _format_provenance(constraint_entry[1])
        return ""

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
