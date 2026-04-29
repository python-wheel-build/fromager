"""VersionMap interface for managing package settings in plugins."""

import typing
from collections.abc import Iterator, Mapping

from packaging.requirements import Requirement
from packaging.version import Version


class VersionMap(Mapping[Version, typing.Any]):
    """Read-only mapping protocol over versions with helpers for resolution.

    Keys must be :class:`packaging.version.Version` instances; callers are
    responsible for parsing strings. Mutate the map via :meth:`add`.
    """

    _content: dict[Version, typing.Any]

    def __init__(
        self, initial_content: Mapping[Version, typing.Any] | None = None
    ) -> None:
        """Initialize the VersionMap.

        Stores associations between versions and arbitrary values (for example
        download URLs for resolution).
        """
        self._content = {}
        for k, v in (initial_content or {}).items():
            self.add(k, v)

    def add(self, key: Version, value: typing.Any) -> None:
        """Associate a value with a version."""
        if not isinstance(key, Version):
            msg = (
                "VersionMap keys must be packaging.version.Version instances, "
                f"not {type(key).__name__}"
            )
            raise TypeError(msg)
        self._content[key] = value

    def __getitem__(self, key: Version) -> typing.Any:
        """Return the value for a version. Raises KeyError if missing."""
        if not isinstance(key, Version):
            msg = (
                "VersionMap keys must be packaging.version.Version instances, "
                f"not {type(key).__name__}"
            )
            raise TypeError(msg)
        return self._content[key]

    def __iter__(self) -> Iterator[Version]:
        """Iterate versions in descending order (highest first)."""
        return reversed(sorted(self._content.keys()))

    def __len__(self) -> int:
        return len(self._content)

    def versions(self) -> Iterator[Version]:
        """Return known versions, sorted in descending order."""
        return iter(self)

    def iter_pairs(self) -> Iterator[tuple[Version, typing.Any]]:
        """Yield ``(version, value)`` tuples in descending version order.

        Typical use is iteration over versions and URLs for custom providers.
        """
        for version in self.versions():
            yield version, self._content[version]

    def lookup(
        self,
        req: Requirement,
        constraint: Requirement | None = None,
        allow_prerelease: bool = False,
    ) -> tuple[Version, typing.Any]:
        """Return the matching version and associated value.

        Finds the known version that best matches the requirement and optional
        constraint and returns a tuple containing that version and the
        associated value.
        """
        for version in self.versions():
            if not req.specifier.contains(version, prereleases=allow_prerelease):
                continue
            if constraint and not constraint.specifier.contains(
                version, prereleases=allow_prerelease
            ):
                continue
            return (version, self._content[version])
        raise ValueError(f"No version matched {req} with constraint {constraint}")
