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
from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression
from packaging.metadata import RawMetadata
from packaging.requirements import Requirement
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import InvalidVersion, Version

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


_CYCLONEDX_HASH_TO_SPDX = {
    "MD5": "MD5",
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
    # BLAKE3 is omitted: spdx-tools requires at least 256 hex digits, while
    # CycloneDX BLAKE3 hashes are usually 64.
}

# SPDX 2.3 checksum values are lowercase hex digits of the digest length.
_SPDX_CHECKSUM_HEX_LENGTHS = {
    "MD5": 32,
    "SHA1": 40,
    "SHA224": 56,
    "SHA256": 64,
    "SHA384": 96,
    "SHA512": 128,
    "SHA3-256": 64,
    "SHA3-384": 96,
    "SHA3-512": 128,
    "BLAKE2b-256": 64,
    "BLAKE2b-384": 96,
    "BLAKE2b-512": 128,
}

_HEX_RE = re.compile(r"[0-9a-fA-F]+")


def _cyclonedx_string(value: typing.Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _cyclonedx_component_purl(component: dict[str, typing.Any]) -> str | None:
    return _cyclonedx_string(component.get("purl"))


def _cyclonedx_spdx_purl(component: dict[str, typing.Any]) -> str | None:
    """Return the component's purl in canonical form, or None if it is invalid.

    Round-tripping through `PackageURL` keeps the same package spelled with
    different qualifier order from becoming two SPDX packages. Local file
    ``download_url`` qualifiers are dropped.
    """
    purl = _cyclonedx_component_purl(component)
    if purl is None:
        return None
    try:
        parsed_purl = PackageURL.from_string(purl)
    except ValueError:
        logger.warning(
            "component %s has an invalid purl %r; ignoring it",
            component.get("name"),
            purl,
        )
        return None

    qualifiers = dict(parsed_purl.qualifiers or {})
    download_url = qualifiers.get("download_url")
    if download_url is not None and download_url.startswith("file://"):
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
    """Yield *component* and its nested components.

    Components with ``excluded`` scope are not shipped, so they are skipped
    together with everything nested under them.
    """
    if _cyclonedx_string(component.get("scope")) == "excluded":
        return
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
    purl: str | None,
    name: str,
    version: str,
) -> bool:
    """Return True if the CycloneDX root *component* is the wheel itself.

    The root is matched against the real package identity (*name* and
    *version* of the built wheel), not the SPDX wheel entry, because
    ``purl`` overrides change the entry but not what the build tool
    reports. *purl* is the component's canonical purl. The component's
    ``name`` and ``version`` fields are optional, but must match if present.
    """
    if purl is None:
        return False
    parsed_purl = PackageURL.from_string(purl)
    if (
        parsed_purl.type != "pypi"
        or parsed_purl.name is None
        or parsed_purl.version is None
    ):
        return False

    component_name = _cyclonedx_string(component.get("name"))
    component_version = _cyclonedx_string(component.get("version"))
    return (
        canonicalize_name(parsed_purl.name) == canonicalize_name(name)
        and _versions_match(parsed_purl.version, version)
        and (
            component_name is None
            or canonicalize_name(component_name) == canonicalize_name(name)
        )
        and (component_version is None or _versions_match(component_version, version))
    )


def _cyclonedx_component_identity(
    component: dict[str, typing.Any], purl: str | None
) -> str:
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


def _cyclonedx_spdx_id(identity: str) -> str:
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
        canonical = _canonical_spdx_expression(expression)
        if canonical is not None:
            expressions.append(canonical)
        else:
            logger.warning(
                "component %s has an invalid SPDX license expression %r; skipping it",
                _cyclonedx_component_purl(component) or component.get("name"),
                expression,
            )

    if not expressions:
        return None
    # Parenthesize OR expressions before joining: SPDX gives AND higher
    # precedence than OR, so an ungrouped OR would weaken the declaration.
    # Canonical expressions always spell the operator in uppercase.
    return " AND ".join(
        f"({expression})" if " OR " in expression else expression
        for expression in expressions
    )


def _canonical_spdx_expression(expression: str) -> str | None:
    """Return *expression* in canonical SPDX form, or None if it is invalid.

    Uses the PEP 639 rules, which allow ``LicenseRef-`` identifiers.
    """
    try:
        return canonicalize_license_expression(expression)
    except InvalidLicenseExpression:
        return None


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
        if (
            not _HEX_RE.fullmatch(content)
            or len(content) != _SPDX_CHECKSUM_HEX_LENGTHS[normalized_algorithm]
        ):
            logger.warning(
                "component %s has an invalid %s checksum %r; skipping it",
                _cyclonedx_component_purl(component) or component.get("name"),
                normalized_algorithm,
                content,
            )
            continue
        checksums.append(
            {"algorithm": normalized_algorithm, "checksumValue": content.lower()}
        )
    return checksums


def _cyclonedx_package(
    component: dict[str, typing.Any],
    spdx_id: str,
    purl: str | None,
) -> dict[str, typing.Any]:
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


def _described_spdx_id(sbom: dict[str, typing.Any]) -> str | None:
    """Return the SPDX id of the package the document describes (the wheel).

    Package SPDX ids are not predictable, so the wheel is found through the
    document's DESCRIBES relationship.
    """
    relationships = sbom.get("relationships")
    if not isinstance(relationships, list):
        return None
    for relationship in relationships:
        if (
            isinstance(relationship, dict)
            and relationship.get("spdxElementId") == "SPDXRef-DOCUMENT"
            and relationship.get("relationshipType") == "DESCRIBES"
        ):
            return _cyclonedx_string(relationship.get("relatedSpdxElement"))
    return None


def merge_cyclonedx_sboms(
    *,
    sbom: dict[str, typing.Any],
    sboms_dir: pathlib.Path,
    name: str,
    version: str,
) -> None:
    """Merge CycloneDX components into a Fromager SPDX document.

    *name* and *version* are the real identity of the built wheel (the
    requirement name and the version from the wheel file name). They are
    used to recognize a build tool's root component as the wheel itself,
    independent of any ``purl`` overrides in the SPDX wheel entry.

    Imported components are related to the wheel with ``CONTAINS``. Local file
    download qualifiers are removed from their PURLs. The original CycloneDX
    files are only read and remain alongside ``fromager.spdx.json``.
    """
    if not sboms_dir.is_dir():
        return

    wheel_spdx_id = _described_spdx_id(sbom)
    if wheel_spdx_id is None:
        logger.warning("SBOM has no DESCRIBES relationship; skipping CycloneDX merge")
        return

    packages = sbom.setdefault("packages", [])
    relationships = sbom.setdefault("relationships", [])
    if not isinstance(packages, list) or not isinstance(relationships, list):
        return
    # Only packages created by this merge are reused for duplicates, so
    # build-reported metadata never lands on fromager's own wheel or
    # upstream entries.
    imported: dict[str, dict[str, typing.Any]] = {}
    # Identities of build tool roots recognized as the wheel itself.
    wheel_identities: set[str] = set()

    for sbom_path in sorted(sboms_dir.iterdir()):
        if not sbom_path.is_file() or sbom_path.name == SBOM_FILENAME:
            continue
        try:
            with sbom_path.open(encoding="utf-8") as sbom_file:
                cyclonedx = json.load(sbom_file)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
        ) as err:
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
            purl = _cyclonedx_spdx_purl(component)
            identity = _cyclonedx_component_identity(component, purl)
            if is_root and _is_python_wheel_root(component, purl, name, version):
                wheel_identities.add(identity)
                continue
            if identity in wheel_identities:
                continue

            package = imported.get(identity)
            if package is not None:
                _merge_cyclonedx_package(package, component)
                continue

            spdx_id = _cyclonedx_spdx_id(identity)
            package = _cyclonedx_package(component, spdx_id, purl)
            imported[identity] = package
            packages.append(package)
            relationships.append(
                {
                    "spdxElementId": wheel_spdx_id,
                    "relationshipType": "CONTAINS",
                    "relatedSpdxElement": spdx_id,
                }
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
