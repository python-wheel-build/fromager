import dataclasses
import datetime
import logging
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

logger = logging.getLogger(__name__)

# fix for runtime errors caused by inheriting classes that are generic in stubs but not runtime
# https://mypy.readthedocs.io/en/latest/runtime_troubles.html#using-classes-that-are-generic-in-stubs-but-not-at-runtime
if TYPE_CHECKING:
    Metadata = Message[str, str]
else:
    Metadata = Message


@dataclasses.dataclass(frozen=True, order=True, slots=True, repr=False, kw_only=True)
class Candidate:
    name: str
    version: Version
    url: str
    is_sdist: bool | None = dataclasses.field(default=None)
    extras: tuple[str, ...] = dataclasses.field(default=(), compare=False)
    build_tag: BuildTag = dataclasses.field(default=(), compare=False)
    has_metadata: bool = dataclasses.field(default=False, compare=False)
    remote_tag: str | None = dataclasses.field(default=None, compare=False)
    remote_commit: str | None = dataclasses.field(default=None, compare=False)
    upload_time: datetime.datetime | None = dataclasses.field(
        default=None, compare=False
    )

    _metadata: Metadata | None = dataclasses.field(
        default=None, init=False, compare=False
    )
    _dependencies: list[Requirement] | None = dataclasses.field(
        default=None, init=False, compare=False
    )

    def __post_init__(self):
        # force normalized name
        object.__setattr__(self, "name", canonicalize_name(self.name))

    def __repr__(self) -> str:
        if not self.extras:
            return f"<{self.name}=={self.version}>"
        return f"<{self.name}[{','.join(self.extras)}]=={self.version}>"

    @property
    def metadata_url(self) -> str | None:
        """PEP 658: metadata is available at {url}.metadata"""
        if self.has_metadata:
            return self.url + ".metadata"
        return None

    @property
    def metadata(self) -> Metadata:
        if self._metadata is None:
            if not self.has_metadata:
                raise ValueError(f"{self.url} does not have metadata")
            metadata = get_metadata_for_wheel(self.url, self.metadata_url)
            object.__setattr__(self, "_metadata", metadata)
        assert self._metadata
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
            dependencies = list(self._get_dependencies())
            object.__setattr__(self, "_dependencies", dependencies)
        assert self._dependencies
        return self._dependencies

    @property
    def requires_python(self) -> str | None:
        return self.metadata.get("Requires-Python")


def get_metadata_for_wheel(url: str, metadata_url: str | None = None) -> Metadata:
    """
    Get metadata for a wheel, supporting PEP 658 metadata endpoints.

    Args:
        url: URL of the wheel file
        metadata_url: Optional URL of the metadata file (PEP 658)

    Returns:
        Parsed metadata as a Message object
    """
    # Try PEP 658 metadata endpoint first if available
    if metadata_url:
        try:
            logger.debug(
                f"Attempting to fetch metadata from PEP 658 endpoint: {metadata_url}"
            )
            response = session.get(metadata_url)
            response.raise_for_status()

            # Parse metadata directly from the response content
            p = BytesParser()
            metadata = p.parse(BytesIO(response.content), headersonly=True)
            logger.debug(f"Successfully retrieved metadata via PEP 658 for {url}")
            return metadata

        except Exception as e:
            logger.debug(f"Failed to fetch PEP 658 metadata from {metadata_url}: {e}")
            logger.debug(
                "Falling back to downloading full wheel for metadata extraction"
            )

    # Fallback to existing method: download wheel and extract metadata
    logger.debug(f"Downloading full wheel to extract metadata: {url}")
    data = session.get(url).content
    with ZipFile(BytesIO(data)) as z:
        for n in z.namelist():
            if n.endswith(".dist-info/METADATA"):
                p = BytesParser()
                return p.parse(z.open(n), headersonly=True)

    # If we didn't find the metadata, return an empty dict
    return EmailMessage()
