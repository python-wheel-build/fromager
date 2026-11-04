"""Generate SPDX 2.3 SBOM documents for wheels built by Fromager.

Produces minimal SPDX 2.3 JSON documents conforming to PEP 770 for
embedding in the ``.dist-info/sboms/`` directory of built wheels.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
import pathlib
import re
import typing
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from urllib.parse import quote

from packageurl import PackageURL
from packaging.metadata import RawMetadata
from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version

from .pkgmetadata import DeclaredLicense, declared_license_from_raw_metadata

if typing.TYPE_CHECKING:
    from . import context
    from .packagesettings import PackageBuildInfo, SbomSettings

logger = logging.getLogger(__name__)

SBOM_FILENAME = "fromager.spdx.json"

_LICENSE_COMMENT = (
    "License inherited from the upstream project's declared Python package "
    "metadata ({source}) and not independently verified by fromager; it may "
    "be imprecise or incomplete."
)
_UNMAPPED_COMMENT = " No unambiguous SPDX mapping for: {raw}."
_NO_LICENSE_COMMENT = (
    "No license information found in the upstream project's declared Python "
    "package metadata."
)
_UNREADABLE_LICENSE_COMMENT = (
    "License information could not be read from the upstream project's "
    "declared Python package metadata."
)
_UNPARSED_COMMENT = " Unparseable fields: {names}."
# Full license texts can be tens of KB; the comment only quotes the start.
_COMMENT_RAW_MAX = 200
_UPSTREAM_REF_COMMENT = (
    "Declared in the upstream project's {source}: {raw}. The license text is "
    "not available in the package metadata."
)
# characters allowed in SPDX ids (SPDX 2.3, idstring)
_SPDX_IDSTRING_CHARS = r"A-Za-z0-9.\-"
_LICENSE_REF_RE = re.compile(rf"LicenseRef-[{_SPDX_IDSTRING_CHARS}]+")


def _license_ref_id(raw: str) -> str:
    """Build a stable LicenseRef id for a declaration without an SPDX id.

    The slug keeps the id readable and the hash keeps it unique, so
    rebuilds produce the same id and SBOMs stay diff-clean.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")[:40].rstrip("-")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"LicenseRef-{slug}-{digest}" if slug else f"LicenseRef-{digest}"


def _quote_for_comment(raw: str) -> str:
    """Shorten a declaration to one line for ``licenseComments``."""
    flat = raw.replace("\n", "; ")
    if len(flat) > _COMMENT_RAW_MAX:
        return flat[:_COMMENT_RAW_MAX] + "..."
    return flat


def _license_fields(
    declared: DeclaredLicense | None,
    unparsed_fields: Iterable[str],
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Build SPDX package license fields and extracted licensing infos.

    fromager does not audit licenses, so ``licenseConcluded`` is always
    ``NOASSERTION`` and the comment says the value is inherited from
    upstream. Every ``LicenseRef`` used must be declared in the document.
    A ``LicenseRef`` fromager generates quotes the raw declaration as its
    text. One that upstream named has no license text in the metadata, so
    its text is ``NOASSERTION`` and a comment says where it was declared.
    """
    extracted: list[dict[str, str]] = []
    names = ", ".join(unparsed_fields)
    if declared is None:
        license_declared = "NOASSERTION"
        # unreadable fields may hold a license, so do not claim there is none
        comment = _UNREADABLE_LICENSE_COMMENT if names else _NO_LICENSE_COMMENT
    else:
        comment = _LICENSE_COMMENT.format(source=declared.source)
        if declared.spdx is None:
            license_declared = _license_ref_id(declared.raw)
            comment += _UNMAPPED_COMMENT.format(raw=_quote_for_comment(declared.raw))
            extracted = [{"licenseId": license_declared, "extractedText": declared.raw}]
        else:
            license_declared = declared.spdx
            ref_comment = _UPSTREAM_REF_COMMENT.format(
                source=declared.source, raw=_quote_for_comment(declared.raw)
            )
            extracted = [
                {
                    "licenseId": ref,
                    "name": ref.removeprefix("LicenseRef-"),
                    "extractedText": "NOASSERTION",
                    "comment": ref_comment,
                }
                for ref in dict.fromkeys(_LICENSE_REF_RE.findall(declared.spdx))
            ]
    if names:
        comment += _UNPARSED_COMMENT.format(names=names)
    fields = {
        "licenseDeclared": license_declared,
        "licenseConcluded": "NOASSERTION",
        "licenseComments": comment,
    }
    return fields, extracted


def _spdx_id(kind: str, name: str, version: str, doc_suffix: str) -> str:
    """Build a package SPDX id unique to this package and document.

    SPDX ids only need to be unique within a document, but tools that read
    several SBOMs (e.g. syft scanning an environment) merge packages by id.
    Name and version keep different wheels apart; the per-document suffix
    keeps apart two builds of the same version that may carry different
    data. SPDX ids only allow letters, digits, ``.`` and ``-``.
    """
    spdx_id = f"SPDXRef-{kind}-{name}-{version}-{doc_suffix}"
    return re.sub(rf"[^{_SPDX_IDSTRING_CHARS}]+", "-", spdx_id)


def _build_downstream_purl(
    *,
    name: NormalizedName,
    version: Version,
    pbi: PackageBuildInfo,
    sbom_settings: SbomSettings,
) -> PackageURL:
    """Build the downstream package URL for the wheel.

    A purl is constructed from ``PurlConfig`` field overrides
    (per-package) falling back to global defaults.
    """
    pc = pbi.purl_config
    purl_type = (pc.type if pc else None) or sbom_settings.purl_type
    qualifiers: dict[str, str] = {}
    repo_url = (pc.repository_url if pc else None) or sbom_settings.repository_url
    if repo_url:
        qualifiers["repository_url"] = str(repo_url)

    return PackageURL(
        type=purl_type,
        namespace=pc.namespace if pc else None,
        name=(pc.name if pc else None) or name,
        version=(pc.version if pc else None) or str(version),
        qualifiers=qualifiers or None,
    )


def _build_upstream_purl(
    *,
    name: NormalizedName,
    version: Version,
    pbi: PackageBuildInfo,
) -> PackageURL:
    """Build the upstream source package URL.

    If ``upstream`` is set in the per-package ``PurlConfig``, it is
    used as-is. Otherwise, the source is identified by its resolved
    PyPI name and version, regardless of downstream wheel purl overrides.
    """
    pc = pbi.purl_config
    if pc and pc.upstream:
        return PackageURL.from_string(pc.upstream)

    return PackageURL(
        type="pypi",
        namespace=None,
        name=name,
        version=str(version),
    )


def generate_sbom(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
    metadata: RawMetadata,
    wheel_version: Version | None = None,
    unparsed_fields: Iterable[str] = (),
) -> dict[str, typing.Any]:
    """Generate a minimal SPDX 2.3 JSON document for a wheel.

    The document contains the downstream wheel as the primary package,
    the upstream source as a second package, and DESCRIBES /
    GENERATED_FROM relationships.

    Both packages carry the license declared in the wheel's core
    *metadata*. *unparsed_fields* names license fields that could not be
    read, so the SBOM does not claim they are absent.

    The document name and namespace are derived from the downstream
    purl (including any ``purl`` field overrides), so the document
    identity always matches the wheel package entry it describes.

    ``version`` is the resolved upstream version. ``wheel_version`` is
    the version of the wheel actually built, which may differ when a
    patch adds a local version (e.g. ``1.2.3+local.1``). The wheel
    package entry, its purl, and the document identity use
    ``wheel_version`` when given; the upstream package entry always
    uses ``version``.

    Package SPDX ids include a per-document suffix and are not predictable,
    so consumers should find the wheel package through the document's
    DESCRIBES relationship rather than by a fixed id.

    .. versionchanged:: 0.104.0
       ``metadata`` is required, and both packages carry license fields.
    """
    sbom_settings = ctx.settings.sbom_settings
    if sbom_settings is None:
        raise RuntimeError("generate_sbom called but SBOM settings are not configured")

    pbi = ctx.package_build_info(req)
    name = canonicalize_name(req.name)
    fromager_version = importlib.metadata.version("fromager")
    timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    creators = list(sbom_settings.creators)
    creators.append(f"Tool: fromager-{fromager_version}")

    downstream = _build_downstream_purl(
        name=name,
        version=wheel_version or version,
        pbi=pbi,
        sbom_settings=sbom_settings,
    )
    upstream = _build_upstream_purl(
        name=name,
        version=version,
        pbi=pbi,
    )

    # Derive the document identity from the downstream purl so the
    # document and the package it describes cannot drift apart. The
    # random UUID keeps the namespace unique per generated document,
    # as required by SPDX 2.3. The name and version are percent-encoded
    # so the namespace is always a valid URI, even when purl overrides
    # contain URI-hostile characters.
    doc_name = downstream.name
    doc_version = downstream.version or str(wheel_version or version)
    doc_uuid = uuid.uuid4()
    namespace = (
        f"{sbom_settings.namespace!s}/{quote(doc_name, safe='')}"
        f"-{quote(doc_version, safe='')}-{doc_uuid}.spdx.json"
    )

    upstream_version = upstream.version or str(version)
    doc_suffix = doc_uuid.hex[:8]
    wheel_id = _spdx_id("wheel", doc_name, doc_version, doc_suffix)
    upstream_id = _spdx_id("upstream", upstream.name, upstream_version, doc_suffix)

    license_fields, extracted_licenses = _license_fields(
        declared_license_from_raw_metadata(metadata), unparsed_fields
    )

    wheel_entry: dict[str, typing.Any] = {
        "SPDXID": wheel_id,
        "name": doc_name,
        "versionInfo": doc_version,
        "downloadLocation": "NOASSERTION",
        "supplier": sbom_settings.supplier,
        **license_fields,
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": downstream.to_string(),
            }
        ],
    }

    upstream_entry: dict[str, typing.Any] = {
        "SPDXID": upstream_id,
        "name": upstream.name,
        "versionInfo": upstream_version,
        "downloadLocation": "NOASSERTION",
        "supplier": "NOASSERTION",
        **license_fields,
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": upstream.to_string(),
            }
        ],
    }

    doc: dict[str, typing.Any] = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{doc_name}-{doc_version}",
        "documentNamespace": namespace,
        "creationInfo": {
            "created": timestamp,
            "creators": creators,
        },
        "packages": [wheel_entry, upstream_entry],
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": wheel_id,
            },
            {
                "spdxElementId": wheel_id,
                "relationshipType": "GENERATED_FROM",
                "relatedSpdxElement": upstream_id,
            },
        ],
    }
    if extracted_licenses:
        doc["hasExtractedLicensingInfos"] = extracted_licenses
    return doc


def write_sbom(
    *,
    sbom: dict[str, typing.Any],
    dist_info_dir: pathlib.Path,
) -> pathlib.Path:
    """Write an SBOM document to the .dist-info/sboms/ directory.

    Creates the sboms/ subdirectory if it does not already exist.
    Returns the path to the written file.
    """
    sboms_dir = dist_info_dir / "sboms"
    sboms_dir.mkdir(exist_ok=True)
    # Fromager generates exactly one SBOM per wheel, so overwriting a
    # previous fromager.spdx.json from an earlier run is expected.
    # SBOMs from other tools (e.g. maturin's CycloneDX) use different
    # filenames and are not affected.
    sbom_path = sboms_dir / SBOM_FILENAME
    with sbom_path.open("w", encoding="utf-8") as f:
        json.dump(sbom, f, indent=2)
        f.write("\n")
    logger.info("wrote SBOM to %s", sbom_path)
    return sbom_path
