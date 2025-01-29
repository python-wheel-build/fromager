"""VersionMap interface for managing package settings in plugins."""

import typing

from packaging.requirements import Requirement
from packaging.version import Version


class VersionMap:
    def __init__(
        self, initial_content: dict[Version | str, typing.Any] | None = None
    ) -> None:
        """Initialize the VersionMap

        Stores the inputs associating versions and arbitrary data. If the
        versions are strings, they are converted to Version instances
        internally. Any exceptions from the conversion are propagated.
        """
        self._content: dict[Version, typing.Any] = {}
        for k, v in (initial_content or {}).items():
            self.add(k, v)

    def add(self, key: Version | str, value: typing.Any) -> None:
        """Add a single value associated with a version

        String keys are converted to Version instances. Any exceptions from the
        conversion are propagated.
        """
        if not isinstance(key, Version):
            key = Version(key)
        self._content[key] = value

    def versions(self) -> typing.Iterable[Version]:
        """Return the known versions, sorted in descending order."""
        return reversed(sorted(self._content.keys()))

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
