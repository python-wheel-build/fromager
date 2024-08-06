"""A provider that handles packages with "extras".

Python package dependencies can include "extras", which are additional
dependencies that are installed "on demand". For instance, project X could
have an additional set of dependencies if PDF generation features are needed.
These can be defined for an extra "pdf" and requested on install as X[pdf].

The basic resolvelib algorithm cannot handle extras, as it builds a dependency
graph which needs to be static - the edges (dependencies) from a node
(candidate) must be fixed. Extras break this assumption.

To model projects with extras, we define a candidate as being a project with a
specific set of dependencies. This introduces a problem, as the resolver could
produce a solution that demands version 1.0 of X[foo] and version 2.0 of
X[bar]. This is impossible, as there is actually only one project X to be
installed. To address this, we inject an additional dependency for every
candidate with an extra - X[foo] version v depends on X version v. By doing
this, we constrain the solution to require a unique version of X.
"""

import typing

from packaging.requirements import Requirement
from resolvelib.providers import AbstractProvider

from .candidate import Candidate

# fix for runtime errors caused by inheriting classes that are generic in stubs but not runtime
# https://mypy.readthedocs.io/en/latest/runtime_troubles.html#using-classes-that-are-generic-in-stubs-but-not-at-runtime
if typing.TYPE_CHECKING:
    BaseAbstractProvider = AbstractProvider[Requirement, Candidate, str]
else:
    BaseAbstractProvider = AbstractProvider


class ExtrasProvider(BaseAbstractProvider):
    """A provider that handles extras."""

    def get_extras_for(
        self, requirement_or_candidate: Requirement | Candidate
    ) -> typing.Iterable[str]:
        """Given a requirement or candidate, return its extras.

        The extras should be a hashable value.
        """
        raise NotImplementedError

    def get_base_requirement(self, candidate: Candidate) -> Requirement:
        """Given a candidate, return a requirement that specifies that
        project/version.

        """
        raise NotImplementedError
