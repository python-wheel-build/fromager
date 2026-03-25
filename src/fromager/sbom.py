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

from packaging.requirements import Requirement
from packaging.version import Version

if typing.TYPE_CHECKING:
    from . import context

logger = logging.getLogger(__name__)

SBOM_FILENAME = "fromager.spdx.json"


def _build_purl(
    *,
    package_name: str,
    package_version: Version,
    purl_override: str | None,
) -> str | None:
    """Build a package URL for the SBOM.

    If a purl override is set in per-package settings, use it with
    ``str.format()`` substitution (``{name}`` and ``{version}``).
    Otherwise return None so the caller can decide whether to include
    a default purl.
    """
    if purl_override:
        return purl_override.format(name=package_name, version=package_version)
    return None


def generate_sbom(
    *,
    ctx: context.WorkContext,
    req: Requirement,
    version: Version,
) -> dict[str, typing.Any]:
    """Generate a minimal SPDX 2.3 JSON document for a wheel.

    The document contains the wheel as the primary package and a
    DESCRIBES relationship from the document to the package.
    """
    sbom_settings = ctx.settings.sbom_settings
    if sbom_settings is None:
        raise RuntimeError("generate_sbom called but SBOM settings are not configured")

    pbi = ctx.package_build_info(req)
    fromager_version = importlib.metadata.version("fromager")
    timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    creators = list(sbom_settings.creators)
    creators.append(f"Tool: fromager-{fromager_version}")

    namespace = f"{sbom_settings.namespace}/{req.name}-{version}.spdx.json"

    package_entry: dict[str, typing.Any] = {
        "SPDXID": "SPDXRef-wheel",
        "name": req.name,
        "versionInfo": str(version),
        "downloadLocation": "NOASSERTION",
        "supplier": sbom_settings.supplier,
    }

    purl = _build_purl(
        package_name=req.name,
        package_version=version,
        purl_override=pbi.purl,
    )
    if purl:
        package_entry["externalRefs"] = [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": purl,
            }
        ]

    doc: dict[str, typing.Any] = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{req.name}-{version}",
        "documentNamespace": namespace,
        "creationInfo": {
            "created": timestamp,
            "creators": creators,
        },
        "packages": [package_entry],
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-wheel",
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
    sbom_path = sboms_dir / SBOM_FILENAME
    with sbom_path.open("w", encoding="utf-8") as f:
        json.dump(sbom, f, indent=2)
        f.write("\n")
    logger.info("wrote SBOM to %s", sbom_path.name)
    return sbom_path
