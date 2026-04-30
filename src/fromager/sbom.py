"""Generate SPDX 2.3 SBOM documents for wheels built by Fromager.

Produces minimal SPDX 2.3 JSON documents conforming to PEP 770 for
embedding in the ``.dist-info/sboms/`` directory of built wheels.
"""

from __future__ import annotations

import importlib.metadata
import json
import logging
import pathlib
import typing
from datetime import UTC, datetime

from packageurl import PackageURL
from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version

if typing.TYPE_CHECKING:
    from . import context
    from .packagesettings import PackageBuildInfo, SbomSettings

logger = logging.getLogger(__name__)

SBOM_FILENAME = "fromager.spdx.json"


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
    sbom_settings: SbomSettings,
) -> PackageURL:
    """Build the upstream source package URL.

    If ``upstream`` is set in the per-package ``PurlConfig``, it is
    used as-is.  Otherwise, the upstream purl is derived from the same
    base as the downstream purl but without the ``repository_url``
    qualifier.
    """
    pc = pbi.purl_config
    if pc and pc.upstream:
        return PackageURL.from_string(pc.upstream)

    purl_type = pc.type if pc else None
    purl_namespace = pc.namespace if pc else None
    purl_name = pc.name if pc else None
    purl_version = pc.version if pc else None
    return PackageURL(
        type=purl_type or sbom_settings.purl_type,
        namespace=purl_namespace,
        name=purl_name or name,
        version=purl_version or str(version),
    )


def generate_sbom(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
) -> dict[str, typing.Any]:
    """Generate a minimal SPDX 2.3 JSON document for a wheel.

    The document contains the downstream wheel as the primary package,
    the upstream source as a second package, and DESCRIBES /
    GENERATED_FROM relationships.
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

    namespace = f"{sbom_settings.namespace!s}/{name}-{version}.spdx.json"

    downstream = _build_downstream_purl(
        name=name,
        version=version,
        pbi=pbi,
        sbom_settings=sbom_settings,
    )
    upstream = _build_upstream_purl(
        name=name,
        version=version,
        pbi=pbi,
        sbom_settings=sbom_settings,
    )

    wheel_entry: dict[str, typing.Any] = {
        "SPDXID": "SPDXRef-wheel",
        "name": downstream.name,
        "versionInfo": downstream.version or str(version),
        "downloadLocation": "NOASSERTION",
        "supplier": sbom_settings.supplier,
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": downstream.to_string(),
            }
        ],
    }

    upstream_entry: dict[str, typing.Any] = {
        "SPDXID": "SPDXRef-upstream",
        "name": upstream.name,
        "versionInfo": upstream.version or str(version),
        "downloadLocation": "NOASSERTION",
        "supplier": "NOASSERTION",
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
        "name": f"{name}-{version}",
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
                "relatedSpdxElement": "SPDXRef-wheel",
            },
            {
                "spdxElementId": "SPDXRef-wheel",
                "relationshipType": "GENERATED_FROM",
                "relatedSpdxElement": "SPDXRef-upstream",
            },
        ],
    }
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
