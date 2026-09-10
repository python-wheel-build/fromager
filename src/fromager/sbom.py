"""Generate SPDX 2.3 SBOM documents for wheels built by Fromager.

Produces minimal SPDX 2.3 JSON documents conforming to PEP 770 for
embedding in the ``.dist-info/sboms/`` directory of built wheels.
"""

from __future__ import annotations

import importlib.metadata
import json
import logging
import pathlib
import re
import typing
from datetime import UTC, datetime

from packageurl import PackageURL
from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import InvalidVersion, Version

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


# CycloneDX hash algorithm names mapped to their SPDX equivalents.
_CYCLONEDX_HASH_TO_SPDX = {
    "SHA-1": "SHA1",
    "SHA-224": "SHA224",
    "SHA-256": "SHA256",
    "SHA-384": "SHA384",
    "SHA-512": "SHA512",
    "SHA3-224": "SHA3-224",
    "SHA3-256": "SHA3-256",
    "SHA3-384": "SHA3-384",
    "SHA3-512": "SHA3-512",
    "BLAKE2B-256": "BLAKE2b-256",
    "BLAKE2B-384": "BLAKE2b-384",
    "BLAKE2B-512": "BLAKE2b-512",
}


def _clean_purl(purl: str) -> str:
    """Drop local ``file://`` download qualifiers, which are build-only paths."""
    try:
        parsed = PackageURL.from_string(purl)
    except ValueError:
        return purl
    qualifiers = dict(parsed.qualifiers or {})
    if not qualifiers.get("download_url", "").startswith("file://"):
        return purl
    del qualifiers["download_url"]
    return PackageURL(
        type=parsed.type,
        namespace=parsed.namespace,
        name=parsed.name,
        version=parsed.version,
        qualifiers=qualifiers or None,
        subpath=parsed.subpath,
    ).to_string()


def _iter_components(
    component: dict[str, typing.Any],
) -> typing.Iterator[dict[str, typing.Any]]:
    """Yield a component and all of its nested sub-components."""
    yield component
    for nested in component.get("components", []):
        yield from _iter_components(nested)


def _component_key(component: dict[str, typing.Any]) -> str:
    """Return a stable identity used to deduplicate components across files."""
    purl = component.get("purl")
    if purl:
        return _clean_purl(purl)
    return "\x00".join(component.get(field, "") for field in ("type", "group", "name"))


def _versions_match(left: str, right: str) -> bool:
    try:
        return Version(left) == Version(right)
    except InvalidVersion:
        return left == right


def _matches_wheel(
    component: dict[str, typing.Any],
    wheel: dict[str, typing.Any],
) -> bool:
    """True if a CycloneDX root is the wheel itself (e.g. an auditwheel root).

    Such a root is folded into ``SPDXRef-wheel`` so its native dependencies are
    not attached to the upstream source.
    """
    purl = component.get("purl")
    if not purl:
        return False
    try:
        parsed = PackageURL.from_string(purl)
    except ValueError:
        return False
    if parsed.type != "pypi" or not parsed.name or not parsed.version:
        return False
    return canonicalize_name(parsed.name) == canonicalize_name(
        wheel["name"]
    ) and _versions_match(parsed.version, wheel["versionInfo"])


def _cyclonedx_license(component: dict[str, typing.Any]) -> str | None:
    """Return the component's declared license as an SPDX expression.

    CycloneDX allows either a single SPDX ``expression`` (already valid SPDX,
    passed through unchanged) or a list of license objects. cargo/maturin always
    emit exactly one entry. A list with multiple entries has undefined AND/OR
    semantics, so we warn and skip it rather than guess a relationship. A named
    (non-SPDX) license has no valid SPDX identifier and is likewise skipped.
    """
    licenses = component.get("licenses", [])
    if not licenses:
        return None
    if len(licenses) > 1:
        logger.warning(
            "component %s has %d license entries with undefined AND/OR "
            "semantics; skipping license",
            component.get("purl") or component.get("name"),
            len(licenses),
        )
        return None
    entry = licenses[0]
    expression = entry.get("expression")
    if expression:
        return str(expression)
    license_info = entry.get("license")
    if isinstance(license_info, dict):
        identifier = license_info.get("id")
        return str(identifier) if identifier else None
    return None


def _cyclonedx_checksums(component: dict[str, typing.Any]) -> list[dict[str, str]]:
    """Convert a component's hashes into SPDX checksum entries."""
    checksums = []
    for entry in component.get("hashes", []):
        algorithm = _CYCLONEDX_HASH_TO_SPDX.get(entry.get("alg", "").upper())
        content = entry.get("content")
        if algorithm and content:
            checksums.append({"algorithm": algorithm, "checksumValue": content})
    return checksums


def _cyclonedx_package(
    component: dict[str, typing.Any],
    spdx_id: str,
) -> dict[str, typing.Any]:
    """Build an SPDX package entry from a CycloneDX component."""
    purl = component.get("purl")
    purl = _clean_purl(purl) if purl else None
    package: dict[str, typing.Any] = {
        "SPDXID": spdx_id,
        "name": component.get("name") or purl or component.get("bom-ref") or "unknown",
        "versionInfo": component.get("version") or "NOASSERTION",
        "downloadLocation": "NOASSERTION",
        "supplier": "NOASSERTION",
    }
    if purl:
        package["externalRefs"] = [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": purl,
            }
        ]
    checksums = _cyclonedx_checksums(component)
    if checksums:
        package["checksums"] = checksums
    license_expression = _cyclonedx_license(component)
    if license_expression:
        package["licenseDeclared"] = license_expression
    scope = component.get("scope")
    if scope and scope != "required":
        package["comment"] = f"CycloneDX scope: {scope}"
    return package


def _spdx_id(component: dict[str, typing.Any], used_ids: set[str]) -> str:
    """Build a readable, unique SPDXID from the component name and version.

    SPDXIDs allow only ``A-Za-z0-9.-``; other characters (e.g. cargo's ``_``)
    are replaced with ``-``. Distinct components can share a name and version
    (e.g. a crate and its library target), so a numeric suffix disambiguates
    collisions to keep every SPDXID unique.
    """
    name = component.get("name") or "unknown"
    version = component.get("version") or "unknown"
    base = re.sub(r"[^A-Za-z0-9.-]", "-", f"SPDXRef-{name}-{version}")
    candidate = base
    suffix = 1
    while candidate in used_ids:
        suffix += 1
        candidate = f"{base}-{suffix}"
    used_ids.add(candidate)
    return candidate


def _iter_all_components(
    cyclonedx: dict[str, typing.Any],
) -> typing.Iterator[tuple[dict[str, typing.Any], bool]]:
    """Yield every ``(component, is_root)`` pair in a CycloneDX document."""
    root = cyclonedx.get("metadata", {}).get("component")
    if root:
        for component in _iter_components(root):
            yield component, component is root
    for component in cyclonedx.get("components", []):
        for nested in _iter_components(component):
            yield nested, False


def merge_cyclonedx_sboms(
    *,
    sbom: dict[str, typing.Any],
    sboms_dir: pathlib.Path,
) -> None:
    """Merge Maturin CycloneDX components into a Fromager SPDX document.

    Each non-excluded component becomes an SPDX package linked to the wheel with
    ``CONTAINS``. A CycloneDX root matching the wheel is folded into
    ``SPDXRef-wheel``. Local ``file://`` download qualifiers are stripped from
    PURLs. The CycloneDX dependency graph is not copied and the original files
    are left in place.
    """
    if not sboms_dir.is_dir():
        return

    wheel = next(
        (p for p in sbom["packages"] if p.get("SPDXID") == "SPDXRef-wheel"), None
    )
    packages = sbom["packages"]
    relationships = sbom["relationships"]
    used_ids = {p["SPDXID"] for p in packages}
    key_to_id: dict[str, str] = {}
    contained: set[str] = set()
    merged_files: list[str] = []

    for sbom_path in sorted(sboms_dir.iterdir()):
        if not sbom_path.is_file() or sbom_path.name == SBOM_FILENAME:
            continue
        try:
            cyclonedx = json.loads(sbom_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as err:
            logger.warning("could not read SBOM file %s: %s", sbom_path, err)
            continue
        if not isinstance(cyclonedx, dict) or cyclonedx.get("bomFormat") != "CycloneDX":
            continue
        merged_files.append(sbom_path.name)

        for component, is_root in _iter_all_components(cyclonedx):
            if component.get("scope") == "excluded":
                continue

            if is_root and wheel is not None and _matches_wheel(component, wheel):
                spdx_id = "SPDXRef-wheel"
            else:
                key = _component_key(component)
                spdx_id = key_to_id.get(key, "")
                if not spdx_id:
                    spdx_id = _spdx_id(component, used_ids)
                    key_to_id[key] = spdx_id
                    packages.append(_cyclonedx_package(component, spdx_id))

            if spdx_id != "SPDXRef-wheel" and spdx_id not in contained:
                contained.add(spdx_id)
                relationships.append(
                    {
                        "spdxElementId": "SPDXRef-wheel",
                        "relationshipType": "CONTAINS",
                        "relatedSpdxElement": spdx_id,
                    }
                )

    if merged_files:
        sbom["comment"] = (
            "Includes components merged from CycloneDX SBOM(s): "
            + ", ".join(sorted(merged_files))
        )


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
