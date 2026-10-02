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
from datetime import UTC, datetime

from license_expression import ExpressionError, get_spdx_licensing
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


_CYCLONEDX_HASH_TO_SPDX = {
    "SHA-1": "SHA1",
    "SHA-224": "SHA224",
    "SHA-256": "SHA256",
    "SHA-384": "SHA384",
    "SHA-512": "SHA512",
    # SPDX 2.3 has no SHA3-224 algorithm, so it is intentionally omitted.
    "SHA3-256": "SHA3-256",
    "SHA3-384": "SHA3-384",
    "SHA3-512": "SHA3-512",
    "BLAKE2B-256": "BLAKE2b-256",
    "BLAKE2B-384": "BLAKE2b-384",
    "BLAKE2B-512": "BLAKE2b-512",
}

# Reused across components; parsing SPDX license expressions is relatively costly.
_SPDX_LICENSING = get_spdx_licensing()

# SPDX checksum values must be lowercase or uppercase hexadecimal digits.
_HEX_RE = re.compile(r"[0-9a-fA-F]+")


def _cyclonedx_string(value: typing.Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _cyclonedx_component_purl(component: dict[str, typing.Any]) -> str | None:
    return _cyclonedx_string(component.get("purl"))


def _cyclonedx_spdx_purl(component: dict[str, typing.Any]) -> str | None:
    purl = _cyclonedx_component_purl(component)
    if purl is None:
        return None
    try:
        parsed_purl = PackageURL.from_string(purl)
    except ValueError:
        return purl

    qualifiers = dict(parsed_purl.qualifiers or {})
    download_url = qualifiers.get("download_url")
    if download_url is None or not download_url.startswith("file://"):
        return purl
    del qualifiers["download_url"]
    return PackageURL(
        type=parsed_purl.type,
        namespace=parsed_purl.namespace,
        name=parsed_purl.name,
        version=parsed_purl.version,
        qualifiers=qualifiers or None,
        subpath=parsed_purl.subpath,
    ).to_string()


def _iter_cyclonedx_components(
    component: dict[str, typing.Any],
) -> typing.Iterator[dict[str, typing.Any]]:
    yield component
    nested_components = component.get("components")
    if not isinstance(nested_components, list):
        return
    for nested_component in nested_components:
        if isinstance(nested_component, dict):
            yield from _iter_cyclonedx_components(nested_component)


def _versions_match(left: str, right: str) -> bool:
    try:
        return Version(left) == Version(right)
    except InvalidVersion:
        return left == right


def _is_python_wheel_root(
    component: dict[str, typing.Any],
    sbom: dict[str, typing.Any],
) -> bool:
    purl = _cyclonedx_component_purl(component)
    if purl is None:
        return False
    try:
        parsed_purl = PackageURL.from_string(purl)
    except ValueError:
        return False
    if (
        parsed_purl.type != "pypi"
        or parsed_purl.name is None
        or parsed_purl.version is None
    ):
        return False

    component_name = _cyclonedx_string(component.get("name"))
    component_version = _cyclonedx_string(component.get("version"))
    if component_name is None or component_version is None:
        return False

    packages = sbom.get("packages")
    if not isinstance(packages, list):
        return False
    wheel = next(
        (
            package
            for package in packages
            if isinstance(package, dict) and package.get("SPDXID") == "SPDXRef-wheel"
        ),
        None,
    )
    if wheel is None:
        return False

    wheel_name = _cyclonedx_string(wheel.get("name"))
    wheel_version = _cyclonedx_string(wheel.get("versionInfo"))
    if wheel_name is None or wheel_version is None:
        return False
    return (
        canonicalize_name(parsed_purl.name) == canonicalize_name(wheel_name)
        and _versions_match(parsed_purl.version, wheel_version)
        and canonicalize_name(component_name) == canonicalize_name(wheel_name)
        and _versions_match(component_version, wheel_version)
    )


def _cyclonedx_component_identity(component: dict[str, typing.Any]) -> str:
    purl = _cyclonedx_spdx_purl(component)
    if purl:
        return f"purl:{purl}"

    return "component:" + "\x00".join(
        [
            _cyclonedx_string(component.get("type")) or "",
            _cyclonedx_string(component.get("group")) or "",
            _cyclonedx_string(component.get("name")) or "",
            _cyclonedx_string(component.get("version")) or "",
        ]
    )


def _cyclonedx_spdx_id(component: dict[str, typing.Any]) -> str:
    identity = _cyclonedx_component_identity(component)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"SPDXRef-cyclonedx-{digest}"


def _cyclonedx_license_expression(
    component: dict[str, typing.Any],
) -> str | None:
    licenses = component.get("licenses")
    if not isinstance(licenses, list):
        return None

    expressions: list[str] = []
    for license_choice in licenses:
        if not isinstance(license_choice, dict):
            continue
        expression = _cyclonedx_string(license_choice.get("expression"))
        if not expression:
            license_info = license_choice.get("license")
            if isinstance(license_info, dict):
                expression = _cyclonedx_string(license_info.get("id"))
        if not expression:
            continue
        if _valid_spdx_expression(expression):
            expressions.append(expression)
        else:
            logger.warning(
                "component %s has an invalid SPDX license expression %r; skipping it",
                _cyclonedx_component_purl(component) or component.get("name"),
                expression,
            )

    if not expressions:
        return None
    return " AND ".join(expressions)


def _valid_spdx_expression(expression: str) -> bool:
    """Return True if *expression* is a valid SPDX license expression."""
    try:
        _SPDX_LICENSING.parse(expression, validate=True)
    except ExpressionError:
        return False
    return True


def _cyclonedx_checksums(
    component: dict[str, typing.Any],
) -> list[dict[str, str]]:
    hashes = component.get("hashes")
    if not isinstance(hashes, list):
        return []

    checksums: list[dict[str, str]] = []
    for hash_info in hashes:
        if not isinstance(hash_info, dict):
            continue
        algorithm = _cyclonedx_string(hash_info.get("alg"))
        content = _cyclonedx_string(hash_info.get("content"))
        if not algorithm or not content:
            continue
        normalized_algorithm = _CYCLONEDX_HASH_TO_SPDX.get(algorithm.upper())
        if normalized_algorithm is None:
            continue
        if not _HEX_RE.fullmatch(content):
            logger.warning(
                "component %s has a non-hexadecimal %s checksum %r; skipping it",
                _cyclonedx_component_purl(component) or component.get("name"),
                normalized_algorithm,
                content,
            )
            continue
        checksums.append({"algorithm": normalized_algorithm, "checksumValue": content})
    return checksums


def _cyclonedx_package(
    component: dict[str, typing.Any],
    spdx_id: str,
) -> dict[str, typing.Any]:
    purl = _cyclonedx_spdx_purl(component)
    name = (
        _cyclonedx_string(component.get("name"))
        or purl
        or _cyclonedx_string(component.get("bom-ref"))
        or "unknown"
    )
    version = _cyclonedx_string(component.get("version")) or "NOASSERTION"
    package: dict[str, typing.Any] = {
        "SPDXID": spdx_id,
        "name": name,
        "versionInfo": version,
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

    license_expression = _cyclonedx_license_expression(component)
    if license_expression:
        package["licenseDeclared"] = license_expression

    scope = _cyclonedx_string(component.get("scope"))
    if scope and scope != "required":
        package["comment"] = f"CycloneDX scope: {scope}"

    return package


def _merge_cyclonedx_package(
    package: dict[str, typing.Any],
    component: dict[str, typing.Any],
) -> None:
    """Add non-conflicting metadata from a duplicate CycloneDX component."""
    component_checksums = _cyclonedx_checksums(component)
    if component_checksums:
        checksums = package.setdefault("checksums", [])
        if isinstance(checksums, list):
            existing_checksums = {
                (item.get("algorithm"), item.get("checksumValue"))
                for item in checksums
                if isinstance(item, dict)
            }
            for checksum in component_checksums:
                key = (checksum["algorithm"], checksum["checksumValue"])
                if key not in existing_checksums:
                    checksums.append(checksum)
                    existing_checksums.add(key)

    license_expression = _cyclonedx_license_expression(component)
    if license_expression and "licenseDeclared" not in package:
        package["licenseDeclared"] = license_expression

    scope = _cyclonedx_string(component.get("scope"))
    if scope and scope != "required" and "comment" not in package:
        package["comment"] = f"CycloneDX scope: {scope}"


def _purl_to_spdx_id(sbom: dict[str, typing.Any]) -> dict[str, str]:
    purls: dict[str, str] = {}
    packages = sbom.get("packages")
    if not isinstance(packages, list):
        return purls

    for package in packages:
        if not isinstance(package, dict):
            continue
        spdx_id = _cyclonedx_string(package.get("SPDXID"))
        external_refs = package.get("externalRefs")
        if not spdx_id or not isinstance(external_refs, list):
            continue
        for external_ref in external_refs:
            if not isinstance(external_ref, dict):
                continue
            if external_ref.get("referenceType") != "purl":
                continue
            purl = _cyclonedx_string(external_ref.get("referenceLocator"))
            if purl:
                purls[purl] = spdx_id
    return purls


def _add_spdx_relationship(
    sbom: dict[str, typing.Any],
    relationship: tuple[str, str, str],
) -> None:
    relationships = sbom.setdefault("relationships", [])
    if not isinstance(relationships, list):
        return
    existing = {
        (
            item.get("spdxElementId"),
            item.get("relationshipType"),
            item.get("relatedSpdxElement"),
        )
        for item in relationships
        if isinstance(item, dict)
    }
    if relationship not in existing:
        relationships.append(
            {
                "spdxElementId": relationship[0],
                "relationshipType": relationship[1],
                "relatedSpdxElement": relationship[2],
            }
        )


def merge_cyclonedx_sboms(
    *,
    sbom: dict[str, typing.Any],
    sboms_dir: pathlib.Path,
) -> None:
    """Merge CycloneDX components into a Fromager SPDX document.

    Imported components are related to the wheel with ``CONTAINS``. Local file
    download qualifiers are removed from their PURLs. The original CycloneDX
    files are only read and remain alongside ``fromager.spdx.json``.
    """
    if not sboms_dir.is_dir():
        return

    purl_to_spdx_id = _purl_to_spdx_id(sbom)
    identity_to_spdx_id: dict[str, str] = {}
    packages = sbom.setdefault("packages", [])
    if not isinstance(packages, list):
        return

    for sbom_path in sorted(sboms_dir.iterdir()):
        if not sbom_path.is_file() or sbom_path.name == SBOM_FILENAME:
            continue
        try:
            with sbom_path.open(encoding="utf-8") as sbom_file:
                cyclonedx = json.load(sbom_file)
        except (OSError, json.JSONDecodeError) as err:
            logger.warning("could not read SBOM file %s: %s", sbom_path, err)
            continue

        if not isinstance(cyclonedx, dict) or cyclonedx.get("bomFormat") != "CycloneDX":
            continue

        metadata = cyclonedx.get("metadata")
        root = metadata.get("component") if isinstance(metadata, dict) else None
        components: list[tuple[dict[str, typing.Any], bool]] = []
        if isinstance(root, dict):
            components.extend(
                (component, component is root)
                for component in _iter_cyclonedx_components(root)
            )
        raw_components = cyclonedx.get("components")
        if isinstance(raw_components, list):
            for component in raw_components:
                if isinstance(component, dict):
                    components.extend(
                        (nested_component, False)
                        for nested_component in _iter_cyclonedx_components(component)
                    )

        for component, is_root in components:
            if _cyclonedx_string(component.get("scope")) == "excluded":
                continue

            identity = _cyclonedx_component_identity(component)
            purl = _cyclonedx_spdx_purl(component)
            spdx_id: str | None
            if is_root and _is_python_wheel_root(component, sbom):
                spdx_id = "SPDXRef-wheel"
                if purl:
                    purl_to_spdx_id[purl] = spdx_id
            else:
                spdx_id = identity_to_spdx_id.get(identity)
                if purl:
                    mapped_spdx_id = purl_to_spdx_id.get(purl)
                    if mapped_spdx_id is not None:
                        spdx_id = mapped_spdx_id
                if spdx_id is None:
                    spdx_id = _cyclonedx_spdx_id(component)
                    packages.append(_cyclonedx_package(component, spdx_id))
                    if purl:
                        purl_to_spdx_id[purl] = spdx_id
                else:
                    package = next(
                        package
                        for package in packages
                        if package.get("SPDXID") == spdx_id
                    )
                    _merge_cyclonedx_package(package, component)

            identity_to_spdx_id[identity] = spdx_id
            if spdx_id != "SPDXRef-wheel":
                _add_spdx_relationship(
                    sbom,
                    ("SPDXRef-wheel", "CONTAINS", spdx_id),
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
