import dataclasses
import datetime
import logging
import posixpath
import typing
from io import BytesIO
from urllib.parse import urlparse
from zipfile import ZipFile

from packaging.metadata import Metadata
from packaging.requirements import Requirement
from packaging.utils import BuildTag, canonicalize_name
from packaging.version import Version

from .pkgmetadata.pep376 import dist_info_name
from .request_session import session

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Cooldown:
    """Policy for rejecting recently-published package versions.

    bootstrap_time is fixed at construction so all resolutions in a single run
    share the same cutoff.
    """

    min_age: datetime.timedelta
    bootstrap_time: datetime.datetime = dataclasses.field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )


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

    def __post_init__(self) -> None:
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
            dependencies = list(self._get_dependencies())
            object.__setattr__(self, "_dependencies", dependencies)
        assert self._dependencies
        return self._dependencies

    @property
    def requires_python(self) -> str | None:
        spec = self.metadata.requires_python
        return str(spec) if spec is not None else None


def get_metadata_for_wheel(
    url: str, metadata_url: str | None = None, *, validate: bool = True
) -> Metadata:
    """Get metadata for a wheel, supporting PEP 658 metadata endpoints.

    Args:
        url: URL of the wheel file
        metadata_url: Optional URL of the metadata file (PEP 658)
        validate: Whether to validate metadata (default: True)

    Returns:
        Parsed metadata as a Metadata object
    """
    # Try PEP 658 metadata endpoint first if available
    if metadata_url:
        try:
            logger.debug(
                f"Attempting to fetch metadata from PEP 658 endpoint: {metadata_url}"
            )
            response = session.get(metadata_url)
            response.raise_for_status()

            # Parse metadata directly using packaging.metadata.Metadata
            # (avoiding circular import with dependencies module)
            metadata = Metadata.from_email(response.content, validate=validate)
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
        metadata_path = _wheel_metadata_path(url)
        try:
            metadata_content = z.read(metadata_path)
        except KeyError as err:
            raise ValueError(f"Could not find {metadata_path} in wheel: {url}") from err
        return Metadata.from_email(metadata_content, validate=validate)


def _wheel_metadata_path(url: str) -> str:
    """Derive the METADATA path inside a wheel from its URL."""
    filename = posixpath.basename(urlparse(url).path)
    return f"{dist_info_name(filename)}/METADATA"
