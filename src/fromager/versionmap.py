"""Map package versions to Git commit IDs or ref paths."""

import typing

from packaging.requirements import Requirement
from packaging.version import Version


class VersionMap:
    """Associate package versions with Git refs in a separate repository.

    Values are commit IDs or ref paths, such as ``refs/tags/v1.2``.
    The clone URL belongs to the resolver provider.

    .. versionchanged:: 0.104.0
       Values are Git ref strings instead of arbitrary data.
    """

    def __init__(self, initial_content: dict[Version | str, str] | None = None) -> None:
        """Initialize the VersionMap

        Store the inputs associating versions and Git refs. If the
        versions are strings, they are converted to Version instances
        internally. Any exceptions from the conversion are propagated.
        """
        self._content: dict[Version, str] = {}
        for k, v in (initial_content or {}).items():
            self.add(k, v)

    def add(self, key: Version | str, value: str) -> None:
        """Associate a Git ref with a version.

        String keys are converted to Version instances. Any exceptions from the
        conversion are propagated.
        """
        if not isinstance(key, Version):
            key = Version(key)
        self._content[key] = value

    def __getitem__(self, key: Version | str) -> str:
        """Get the Git ref associated with a version.

        String keys are converted to Version instances. Raises KeyError if the
        version is not found.
        """
        if not isinstance(key, Version):
            key = Version(key)
        return self._content[key]

    def versions(self) -> typing.Iterable[Version]:
        """Return the known versions, sorted in descending order."""
        return reversed(sorted(self._content.keys()))

    def lookup(
        self,
        req: Requirement,
        constraint: Requirement | None = None,
        allow_prerelease: bool = False,
    ) -> tuple[Version, str]:
        """Return the matching version and associated Git ref.

        Finds the known version that best matches the requirement and optional
        constraint and returns a tuple containing that version and the
        associated Git ref.
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
