import json
import pathlib
import typing
import uuid
from unittest.mock import patch

from conftest import make_sbom_ctx
from packaging.requirements import Requirement
from packaging.version import Version
from spdx_tools.spdx.parser.jsonlikedict.json_like_dict_parser import (
    JsonLikeDictParser,
)
from spdx_tools.spdx.validation.document_validator import validate_full_spdx_document

from fromager import sbom
from fromager.packagesettings import SbomSettings


def _validate_spdx(doc: dict[str, typing.Any]) -> None:
    """Validate an SBOM dict against the SPDX 2.3 spec using spdx-tools."""
    parsed = JsonLikeDictParser().parse(doc)
    errors = validate_full_spdx_document(parsed, spdx_version="SPDX-2.3")
    assert not errors, "\n".join(e.validation_message for e in errors)


def test_generate_sbom_structure(tmp_path: pathlib.Path) -> None:
    """Verify the generated SBOM has the required SPDX 2.3 fields."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("example-pkg==1.2.3"),
        version=Version("1.2.3"),
    )

    assert doc["spdxVersion"] == "SPDX-2.3"
    assert doc["dataLicense"] == "CC0-1.0"
    assert doc["SPDXID"] == "SPDXRef-DOCUMENT"
    assert doc["name"] == "example-pkg-1.2.3"
    assert "documentNamespace" in doc
    assert "creationInfo" in doc
    assert doc["creationInfo"]["created"]
    assert any("fromager" in c for c in doc["creationInfo"]["creators"])
    _validate_spdx(doc)


def test_generate_sbom_default_purls(tmp_path: pathlib.Path) -> None:
    """Verify default purls use pkg:pypi without qualifiers."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("my-package==2.0.0"),
        version=Version("2.0.0"),
    )

    wheel = doc["packages"][0]
    upstream = doc["packages"][1]
    assert wheel["externalRefs"][0]["referenceLocator"] == "pkg:pypi/my-package@2.0.0"
    assert (
        upstream["externalRefs"][0]["referenceLocator"] == "pkg:pypi/my-package@2.0.0"
    )
    _validate_spdx(doc)


def test_generate_sbom_repository_url_qualifier(tmp_path: pathlib.Path) -> None:
    """Verify global repository_url adds qualifier to downstream but not upstream."""
    settings = SbomSettings(
        repository_url="https://packages.redhat.com",  # type: ignore[arg-type]
    )
    ctx = make_sbom_ctx(tmp_path, sbom_settings=settings)
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("numpy==1.26.0"),
        version=Version("1.26.0"),
    )

    wheel = doc["packages"][0]
    upstream = doc["packages"][1]
    assert wheel["externalRefs"][0]["referenceLocator"] == (
        "pkg:pypi/numpy@1.26.0?repository_url=https://packages.redhat.com"
    )
    assert upstream["externalRefs"][0]["referenceLocator"] == "pkg:pypi/numpy@1.26.0"
    _validate_spdx(doc)


def test_generate_sbom_custom_settings(tmp_path: pathlib.Path) -> None:
    """Verify custom supplier, namespace, and creators are used."""
    settings = SbomSettings(
        supplier="Organization: ExampleCo",
        namespace="https://www.example.com",  # type: ignore[arg-type]
        creators=["Organization: ExampleCo"],
    )
    ctx = make_sbom_ctx(tmp_path, sbom_settings=settings)
    fixed_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    with patch("fromager.sbom.uuid.uuid4", return_value=fixed_uuid):
        doc = sbom.generate_sbom(
            ctx=ctx,
            req=Requirement("my-package==2.0.0"),
            version=Version("2.0.0"),
        )

    wheel = doc["packages"][0]
    assert wheel["supplier"] == "Organization: ExampleCo"
    assert doc["documentNamespace"] == (
        f"https://www.example.com/my-package-2.0.0-{fixed_uuid}.spdx.json"
    )
    creators = doc["creationInfo"]["creators"]
    assert "Organization: ExampleCo" in creators
    assert any("fromager" in c for c in creators)
    _validate_spdx(doc)


def test_generate_sbom_document_identity_follows_purl_version_override(
    tmp_path: pathlib.Path,
) -> None:
    """Verify document name and namespace follow the purl version override.

    The document header must identify the built wheel, not the resolved
    upstream version, and must not disagree with the package it
    DESCRIBES.
    """
    ctx = make_sbom_ctx(
        tmp_path,
        sbom_settings=SbomSettings(),
        package_overrides={
            "purl": {
                "version": "0.5.5+corp.1",
                "upstream": "pkg:pypi/test-pkg@0.5.5",
            },
        },
    )
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test-pkg==0.5.5"),
        version=Version("0.5.5"),
    )

    assert doc["name"] == "test-pkg-0.5.5+corp.1"
    assert doc["documentNamespace"].startswith(
        "https://spdx.org/spdxdocs/test-pkg-0.5.5%2Bcorp.1-"
    )
    assert doc["documentNamespace"].endswith(".spdx.json")
    wheel = doc["packages"][0]
    assert wheel["name"] == "test-pkg"
    assert wheel["versionInfo"] == "0.5.5+corp.1"
    upstream = doc["packages"][1]
    assert upstream["versionInfo"] == "0.5.5"
    _validate_spdx(doc)


def test_generate_sbom_upstream_uses_source_version_without_upstream_override(
    tmp_path: pathlib.Path,
) -> None:
    """Keep the source release distinct from a locally versioned wheel."""
    ctx = make_sbom_ctx(
        tmp_path,
        sbom_settings=SbomSettings(),
        package_overrides={"purl": {"version": "0.5.5+local.1"}},
    )
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test-pkg==0.5.5"),
        version=Version("0.5.5"),
    )

    wheel, upstream = doc["packages"]
    assert wheel["versionInfo"] == "0.5.5+local.1"
    assert wheel["externalRefs"][0]["referenceLocator"] == (
        "pkg:pypi/test-pkg@0.5.5%2Blocal.1"
    )
    assert upstream["versionInfo"] == "0.5.5"
    assert upstream["externalRefs"][0]["referenceLocator"] == (
        "pkg:pypi/test-pkg@0.5.5"
    )
    _validate_spdx(doc)


def test_generate_sbom_namespace_is_unique_per_document(
    tmp_path: pathlib.Path,
) -> None:
    """Verify each generated document gets a distinct namespace."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    kwargs: dict[str, typing.Any] = {
        "ctx": ctx,
        "req": Requirement("test-pkg==0.5.5"),
        "version": Version("0.5.5"),
    }

    doc1 = sbom.generate_sbom(**kwargs)
    doc2 = sbom.generate_sbom(**kwargs)

    assert doc1["name"] == doc2["name"]
    assert doc1["documentNamespace"] != doc2["documentNamespace"]
    _validate_spdx(doc1)
    _validate_spdx(doc2)


def test_generate_sbom_namespace_percent_encodes_purl_overrides(
    tmp_path: pathlib.Path,
) -> None:
    """Verify URI-hostile purl overrides are percent-encoded in the namespace."""
    ctx = make_sbom_ctx(
        tmp_path,
        sbom_settings=SbomSettings(),
        package_overrides={
            "purl": {
                "name": "my package",
                "version": "1.0 beta",
            },
        },
    )
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test-pkg==1.0"),
        version=Version("1.0"),
    )

    # Document and package names keep the raw override values
    assert doc["name"] == "my package-1.0 beta"
    wheel = doc["packages"][0]
    assert wheel["name"] == "my package"
    assert wheel["versionInfo"] == "1.0 beta"
    # The namespace percent-encodes them so it stays a valid URI
    namespace = doc["documentNamespace"]
    assert namespace.startswith("https://spdx.org/spdxdocs/my%20package-1.0%20beta-")
    assert " " not in namespace
    assert namespace.endswith(".spdx.json")
    _validate_spdx(doc)


def test_generate_sbom_purl_field_overrides(tmp_path: pathlib.Path) -> None:
    """Verify individual purl field overrides work."""
    ctx = make_sbom_ctx(
        tmp_path,
        sbom_settings=SbomSettings(),
        package_overrides={"purl": {"type": "generic", "name": "custom-name"}},
    )
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test-pkg==1.0.0"),
        version=Version("1.0.0"),
    )

    wheel = doc["packages"][0]
    upstream = doc["packages"][1]
    assert wheel["externalRefs"][0]["referenceLocator"] == (
        "pkg:generic/custom-name@1.0.0"
    )
    # Field overrides carry through to upstream (without qualifiers)
    assert upstream["externalRefs"][0]["referenceLocator"] == (
        "pkg:generic/custom-name@1.0.0"
    )
    # Document identity follows the purl name override
    assert doc["name"] == "custom-name-1.0.0"
    _validate_spdx(doc)


def test_generate_sbom_package_repository_url_override(tmp_path: pathlib.Path) -> None:
    """Verify per-package repository_url overrides the global value."""
    ctx = make_sbom_ctx(
        tmp_path,
        sbom_settings=SbomSettings(
            repository_url="https://packages.redhat.com",  # type: ignore[arg-type]
        ),
        package_overrides={
            "purl": {"repository_url": "https://mirror.example.com/simple"},
        },
    )
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test-pkg==1.0.0"),
        version=Version("1.0.0"),
    )

    wheel = doc["packages"][0]
    upstream = doc["packages"][1]
    assert wheel["externalRefs"][0]["referenceLocator"] == (
        "pkg:pypi/test-pkg@1.0.0?repository_url=https://mirror.example.com/simple"
    )
    # Upstream never gets repository_url
    assert upstream["externalRefs"][0]["referenceLocator"] == "pkg:pypi/test-pkg@1.0.0"
    _validate_spdx(doc)


def test_generate_sbom_upstream_purl_override(tmp_path: pathlib.Path) -> None:
    """Verify upstream purl override for GitHub-sourced packages."""
    ctx = make_sbom_ctx(
        tmp_path,
        sbom_settings=SbomSettings(
            repository_url="https://packages.redhat.com",  # type: ignore[arg-type]
        ),
        package_overrides={
            "purl": {"upstream": "pkg:github/vllm-project/bart-plugin@v0.2.0"},
        },
    )
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test-pkg==0.2.0"),
        version=Version("0.2.0"),
    )

    wheel = doc["packages"][0]
    upstream = doc["packages"][1]
    # Downstream has repository_url qualifier
    assert (
        "repository_url=https://packages.redhat.com"
        in (wheel["externalRefs"][0]["referenceLocator"])
    )
    # Upstream identity comes from the override purl
    assert upstream["name"] == "bart-plugin"
    assert upstream["versionInfo"] == "v0.2.0"
    assert upstream["externalRefs"][0]["referenceLocator"] == (
        "pkg:github/vllm-project/bart-plugin@v0.2.0"
    )
    _validate_spdx(doc)


def test_generate_sbom_canonicalizes_name(tmp_path: pathlib.Path) -> None:
    """Verify package name is canonicalized per PEP 503."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("My_Package==1.0.0"),
        version=Version("1.0.0"),
    )

    wheel = doc["packages"][0]
    assert wheel["name"] == "my-package"
    assert doc["name"] == "my-package-1.0.0"
    assert "pkg:pypi/my-package@1.0.0" in (wheel["externalRefs"][0]["referenceLocator"])
    _validate_spdx(doc)


def test_generate_sbom_relationships(tmp_path: pathlib.Path) -> None:
    """Verify DESCRIBES and GENERATED_FROM relationships."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test==0.1.0"),
        version=Version("0.1.0"),
    )

    rels = doc["relationships"]
    assert len(rels) == 2
    assert rels[0]["spdxElementId"] == "SPDXRef-DOCUMENT"
    assert rels[0]["relationshipType"] == "DESCRIBES"
    assert rels[0]["relatedSpdxElement"] == "SPDXRef-wheel"
    assert rels[1]["spdxElementId"] == "SPDXRef-wheel"
    assert rels[1]["relationshipType"] == "GENERATED_FROM"
    assert rels[1]["relatedSpdxElement"] == "SPDXRef-upstream"
    _validate_spdx(doc)


def test_generate_sbom_upstream_supplier(tmp_path: pathlib.Path) -> None:
    """Verify upstream package always has supplier NOASSERTION."""
    settings = SbomSettings(supplier="Organization: Red Hat")
    ctx = make_sbom_ctx(tmp_path, sbom_settings=settings)
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("numpy==1.26.0"),
        version=Version("1.26.0"),
    )

    wheel = doc["packages"][0]
    upstream = doc["packages"][1]
    assert wheel["supplier"] == "Organization: Red Hat"
    assert upstream["supplier"] == "NOASSERTION"
    _validate_spdx(doc)


def test_write_sbom_creates_file(tmp_path: pathlib.Path) -> None:
    """Verify write_sbom creates sboms/ dir and writes valid JSON."""
    dist_info_dir = tmp_path / "pkg-1.0.dist-info"
    dist_info_dir.mkdir()

    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("pkg==1.0"),
        version=Version("1.0"),
    )
    result = sbom.write_sbom(sbom=doc, dist_info_dir=dist_info_dir)

    assert result == dist_info_dir / "sboms" / "fromager.spdx.json"
    assert result.exists()

    content = json.loads(result.read_text())
    assert content["spdxVersion"] == "SPDX-2.3"
    _validate_spdx(content)


def test_write_sbom_preserves_existing_files(tmp_path: pathlib.Path) -> None:
    """Verify write_sbom does not overwrite existing SBOM files."""
    dist_info_dir = tmp_path / "pkg-1.0.dist-info"
    sboms_dir = dist_info_dir / "sboms"
    sboms_dir.mkdir(parents=True)
    existing = sboms_dir / "cyclonedx.json"
    existing.write_text('{"bomFormat": "CycloneDX"}')

    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("pkg==1.0"),
        version=Version("1.0"),
    )
    sbom.write_sbom(sbom=doc, dist_info_dir=dist_info_dir)

    # Existing file should be untouched
    assert existing.exists()
    assert json.loads(existing.read_text())["bomFormat"] == "CycloneDX"
    # New file should also exist
    assert (sboms_dir / "fromager.spdx.json").exists()
