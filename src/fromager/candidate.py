import typing
from email.message import EmailMessage, Message
from email.parser import BytesParser
from io import BytesIO
from typing import TYPE_CHECKING
from zipfile import ZipFile

from packaging.requirements import Requirement
from packaging.utils import BuildTag, canonicalize_name
from packaging.version import Version

from .request_session import session

# fix for runtime errors caused by inheriting classes that are generic in stubs but not runtime
# https://mypy.readthedocs.io/en/latest/runtime_troubles.html#using-classes-that-are-generic-in-stubs-but-not-at-runtime
if TYPE_CHECKING:
    Metadata = Message[str, str]
else:
    Metadata = Message


class Candidate:
    def __init__(
        self,
        name: str,
        version: Version,
        url: str,
        extras: typing.Iterable[str] | None = None,
        is_sdist: bool | None = None,
        build_tag: BuildTag = (),
    ):
        self.name = canonicalize_name(name)
        self.version = version
        self.url = url
        self.extras = extras
        self.is_sdist = is_sdist
        self.build_tag = build_tag

        self._metadata: Metadata | None = None
        self._dependencies: list[Requirement] | None = None

    def __repr__(self) -> str:
        if not self.extras:
            return f"<{self.name}=={self.version}>"
        return f"<{self.name}[{','.join(self.extras)}]=={self.version}>"

    @property
    def metadata(self) -> Metadata:
        if self._metadata is None:
            self._metadata = get_metadata_for_wheel(self.url)
        return self._metadata

    def _get_dependencies(self) -> typing.Iterable[Requirement]:
        deps = self.metadata.get_all("Requires-Dist", [])
        extras = self.extras if self.extras else [""]

        for d in deps:
            r = Requirement(d)
            if r.marker is None:
                yield r
            else:
                for e in extras:
                    if r.marker.evaluate({"extra": e}):
                        yield r

    @property
    def dependencies(self) -> list[Requirement]:
        if self._dependencies is None:
            self._dependencies = list(self._get_dependencies())
        return self._dependencies

    @property
    def requires_python(self) -> str | None:
        return self.metadata.get("Requires-Python")


def get_metadata_for_wheel(url: str) -> Metadata:
    data = session.get(url).content
    with ZipFile(BytesIO(data)) as z:
        for n in z.namelist():
            if n.endswith(".dist-info/METADATA"):
                p = BytesParser()
                return p.parse(z.open(n), headersonly=True)

    # If we didn't find the metadata, return an empty dict
    return EmailMessage()
