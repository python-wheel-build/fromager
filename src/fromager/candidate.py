import typing
from io import BytesIO
from zipfile import ZipFile

from packaging.metadata import Metadata, parse_email
from packaging.requirements import Requirement
from packaging.utils import BuildTag, canonicalize_name
from packaging.version import Version

from .request_session import session


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
        deps = self.metadata.requires_dist or []
        extras = self.extras if self.extras else [""]

        for r in deps:
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
        spec = self.metadata.requires_python
        return str(spec) if spec is not None else None


def get_metadata_for_wheel(url: str) -> Metadata:
    data = session.get(url).content
    with ZipFile(BytesIO(data)) as z:
        for n in z.namelist():
            if n.endswith(".dist-info/METADATA"):
                metadata_content = z.read(n)
                raw_metadata, _ = parse_email(metadata_content)
                metadata = Metadata.from_raw(raw_metadata)
                return metadata

    # If we didn't find the metadata, return an empty metadata object
    raw_metadata, _ = parse_email(b"")
    return Metadata.from_raw(raw_metadata)
