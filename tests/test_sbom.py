import json
import pathlib
import re
import typing
import uuid
from unittest.mock import patch

import pytest
from conftest import make_sbom_ctx
from packaging.metadata import RawMetadata
from packaging.requirements import Requirement
from packaging.version import Version
from pydantic import AnyUrl
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


def _metadata(**fields: typing.Any) -> RawMetadata:
    """Build core metadata for the package an SBOM describes."""
    raw = RawMetadata(metadata_version="2.4", name="test", version="1.0")
    raw.update(fields)  # type: ignore[typeddict-item]
    return raw


def _write_cyclonedx_sbom(
    sboms_dir: pathlib.Path,
    filename: str,
    *,
    root_name: str = "example",
    root_version: str = "1.0.0",
) -> None:
    """Write a representative Maturin CycloneDX 1.5 document."""
    root_purl = f"pkg:cargo/{root_name}@{root_version}"
    serde_purl = "pkg:cargo/serde@1.0.0"
    pyo3_purl = "pkg:cargo/pyo3@0.21.0"
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{root_name}",
        "metadata": {
            "tools": [{"vendor": "PyO3", "name": "maturin", "version": "1.15.0"}],
            "component": {
                "type": "library",
                "bom-ref": root_purl,
                "name": root_name,
                "version": root_version,
                "purl": root_purl,
            },
        },
        "components": [
            {
                "type": "library",
                "bom-ref": serde_purl,
                "name": "serde",
                "version": "1.0.0",
                "scope": "required",
                "purl": serde_purl,
                "hashes": [{"alg": "SHA-256", "content": "a" * 64}],
                "licenses": [{"license": {"id": "MIT"}}],
            },
            {
                "type": "library",
                "bom-ref": pyo3_purl,
                "name": "pyo3",
                "version": "0.21.0",
                "scope": "excluded",
                "purl": pyo3_purl,
                "licenses": [{"expression": "Apache-2.0"}],
            },
        ],
        "dependencies": [{"ref": root_purl, "dependsOn": [serde_purl, pyo3_purl]}],
    }
    sboms_dir.mkdir(parents=True, exist_ok=True)
    (sboms_dir / filename).write_text(json.dumps(document))


def test_generate_sbom_structure(tmp_path: pathlib.Path) -> None:
    """Verify the generated SBOM has the required SPDX 2.3 fields."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("example-pkg==1.2.3"),
        version=Version("1.2.3"),
        metadata=_metadata(),
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
        metadata=_metadata(),
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
        metadata=_metadata(),
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
            metadata=_metadata(),
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
        metadata=_metadata(),
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
        metadata=_metadata(),
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


def test_generate_sbom_wheel_version_used_without_purl_override(
    tmp_path: pathlib.Path,
) -> None:
    """Verify the wheel entry uses the actual wheel version automatically.

    When a patch adds a local version, the SBOM must identify the built
    wheel without requiring a per-package ``purl.version`` override.
    """
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test-pkg==0.5.5"),
        version=Version("0.5.5"),
        wheel_version=Version("0.5.5+local.1"),
        metadata=_metadata(),
    )

    assert doc["name"] == "test-pkg-0.5.5+local.1"
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


@pytest.mark.parametrize(
    ("package_purl", "sbom_type", "expected_wheel"),
    [
        ({"name": "test-pkg-corp"}, "pypi", "pkg:pypi/test-pkg-corp@0.5.5"),
        ({"type": "generic"}, "pypi", "pkg:generic/test-pkg@0.5.5"),
        ({"namespace": "acme"}, "pypi", "pkg:pypi/acme/test-pkg@0.5.5"),
        ({}, "generic", "pkg:generic/test-pkg@0.5.5"),
    ],
)
def test_generate_sbom_upstream_ignores_wheel_purl_overrides(
    tmp_path: pathlib.Path,
    package_purl: dict[str, str],
    sbom_type: str,
    expected_wheel: str,
) -> None:
    """Wheel-only purl settings must not rewrite the source identity."""
    ctx = make_sbom_ctx(
        tmp_path,
        sbom_settings=SbomSettings(purl_type=sbom_type),
        package_overrides={"purl": package_purl},
    )
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test-pkg==0.5.5"),
        version=Version("0.5.5"),
        metadata=_metadata(),
    )

    wheel, upstream = doc["packages"]
    assert wheel["externalRefs"][0]["referenceLocator"] == expected_wheel
    assert upstream["name"] == "test-pkg"
    assert upstream["externalRefs"][0]["referenceLocator"] == (
        "pkg:pypi/test-pkg@0.5.5"
    )
    _validate_spdx(doc)


def test_generate_sbom_purl_version_override_wins_over_wheel_version(
    tmp_path: pathlib.Path,
) -> None:
    """Verify an explicit purl.version override still takes precedence."""
    ctx = make_sbom_ctx(
        tmp_path,
        sbom_settings=SbomSettings(),
        package_overrides={"purl": {"version": "0.5.5+corp.1"}},
    )
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test-pkg==0.5.5"),
        version=Version("0.5.5"),
        wheel_version=Version("0.5.5+local.1"),
        metadata=_metadata(),
    )

    wheel = doc["packages"][0]
    assert wheel["versionInfo"] == "0.5.5+corp.1"
    assert doc["name"] == "test-pkg-0.5.5+corp.1"
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
        "metadata": _metadata(),
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
        metadata=_metadata(),
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
        metadata=_metadata(),
    )

    wheel = doc["packages"][0]
    upstream = doc["packages"][1]
    assert wheel["externalRefs"][0]["referenceLocator"] == (
        "pkg:generic/custom-name@1.0.0"
    )
    # Wheel field overrides must not change the resolved source identity.
    assert upstream["externalRefs"][0]["referenceLocator"] == (
        "pkg:pypi/test-pkg@1.0.0"
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
        metadata=_metadata(),
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
        metadata=_metadata(),
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
        metadata=_metadata(),
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
        metadata=_metadata(),
    )

    wheel_id, upstream_id = (p["SPDXID"] for p in doc["packages"])
    rels = doc["relationships"]
    assert len(rels) == 2
    assert rels[0]["spdxElementId"] == "SPDXRef-DOCUMENT"
    assert rels[0]["relationshipType"] == "DESCRIBES"
    assert rels[0]["relatedSpdxElement"] == wheel_id
    assert rels[1]["spdxElementId"] == wheel_id
    assert rels[1]["relationshipType"] == "GENERATED_FROM"
    assert rels[1]["relatedSpdxElement"] == upstream_id
    _validate_spdx(doc)


def test_generate_sbom_spdx_ids_name_package_and_document(
    tmp_path: pathlib.Path,
) -> None:
    """Verify package SPDX ids carry name, version, and a document suffix."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    fixed_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    with patch("fromager.sbom.uuid.uuid4", return_value=fixed_uuid):
        doc = sbom.generate_sbom(
            ctx=ctx,
            req=Requirement("test==0.1.0"),
            version=Version("0.1.0"),
            metadata=_metadata(),
        )

    assert [p["SPDXID"] for p in doc["packages"]] == [
        "SPDXRef-wheel-test-0.1.0-12345678",
        "SPDXRef-upstream-test-0.1.0-12345678",
    ]
    _validate_spdx(doc)


def test_generate_sbom_spdx_ids_differ_between_packages(
    tmp_path: pathlib.Path,
) -> None:
    """Verify SBOMs of different wheels share no package SPDX ids.

    Tools such as syft merge packages from several SBOMs by SPDX id, so
    shared ids would attribute one wheel's data to another. Both documents
    get the same UUID so only the name and version can keep the ids apart.
    """
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    fixed_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    with patch("fromager.sbom.uuid.uuid4", return_value=fixed_uuid):
        docs = [
            sbom.generate_sbom(
                ctx=ctx,
                req=Requirement(req),
                version=Version(ver),
                metadata=_metadata(),
            )
            for req, ver in [("idna==3.6", "3.6"), ("packaging==26.3", "26.3")]
        ]

    ids = [{p["SPDXID"] for p in doc["packages"]} for doc in docs]
    assert ids[0].isdisjoint(ids[1])


def test_generate_sbom_spdx_ids_differ_between_documents(
    tmp_path: pathlib.Path,
) -> None:
    """Verify two SBOMs of the same package share no package SPDX ids.

    Two builds of one version (e.g. for different variants) can carry
    different data; shared ids would let tools merge them into one package.
    """
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    docs = [
        sbom.generate_sbom(
            ctx=ctx,
            req=Requirement("idna==3.6"),
            version=Version("3.6"),
            metadata=_metadata(),
        )
        for _ in range(2)
    ]

    ids = [{p["SPDXID"] for p in doc["packages"]} for doc in docs]
    assert ids[0].isdisjoint(ids[1])


def test_generate_sbom_spdx_ids_are_sanitized(tmp_path: pathlib.Path) -> None:
    """Verify characters SPDX ids do not allow are replaced."""
    ctx = make_sbom_ctx(
        tmp_path,
        sbom_settings=SbomSettings(),
        package_overrides={"purl": {"version": "0.5.5+local.1"}},
    )
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test-pkg==0.5.5"),
        version=Version("0.5.5"),
        metadata=_metadata(),
    )

    wheel_id, upstream_id = (p["SPDXID"] for p in doc["packages"])
    assert re.fullmatch(
        r"SPDXRef-wheel-test-pkg-0\.5\.5-local\.1-[0-9a-f]{8}", wheel_id
    )
    assert re.fullmatch(r"SPDXRef-upstream-test-pkg-0\.5\.5-[0-9a-f]{8}", upstream_id)
    _validate_spdx(doc)


def test_generate_sbom_upstream_supplier(tmp_path: pathlib.Path) -> None:
    """Verify upstream package always has supplier NOASSERTION."""
    settings = SbomSettings(supplier="Organization: Red Hat")
    ctx = make_sbom_ctx(tmp_path, sbom_settings=settings)
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("numpy==1.26.0"),
        version=Version("1.26.0"),
        metadata=_metadata(),
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
        metadata=_metadata(),
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
        metadata=_metadata(),
    )
    sbom.write_sbom(sbom=doc, dist_info_dir=dist_info_dir)

    # Existing file should be untouched
    assert existing.exists()
    assert json.loads(existing.read_text())["bomFormat"] == "CycloneDX"
    # New file should also exist
    assert (sboms_dir / "fromager.spdx.json").exists()


def _license_sbom(
    tmp_path: pathlib.Path, **fields: typing.Any
) -> dict[str, typing.Any]:
    """Generate an SBOM for a package with the given license metadata."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    return sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test==1.0"),
        version=Version("1.0"),
        metadata=_metadata(**fields),
    )


def test_license_ref_id_matches_issue_example() -> None:
    """Verify the LicenseRef id reproduces the example agreed in #1378."""
    result = sbom._license_ref_id("License :: OSI Approved :: BSD License")

    assert result == "LicenseRef-license-osi-approved-bsd-license-a9d12a80"


def test_license_ref_id_without_ascii_slug() -> None:
    """Verify ids stay valid when the text has no leading ASCII words."""
    assert re.fullmatch(r"LicenseRef-[0-9a-f]{8}", sbom._license_ref_id("版权所有"))
    assert sbom._license_ref_id("=====\nThe Kiwi licensing terms").startswith(
        "LicenseRef-the-kiwi-licensing-terms-"
    )


def test_generate_sbom_license_from_expression(tmp_path: pathlib.Path) -> None:
    """Verify a valid License-Expression is used verbatim on both packages."""
    doc = _license_sbom(tmp_path, license_expression="Apache-2.0 OR BSD-2-Clause")

    for package in doc["packages"]:
        assert package["licenseDeclared"] == "Apache-2.0 OR BSD-2-Clause"
        assert package["licenseConcluded"] == "NOASSERTION"
        assert package["licenseComments"] == sbom._LICENSE_COMMENT.format(
            source="License-Expression"
        )
    assert "hasExtractedLicensingInfos" not in doc
    _validate_spdx(doc)


def test_generate_sbom_license_ambiguous_classifier(tmp_path: pathlib.Path) -> None:
    """Verify an ambiguous classifier yields the Option A output from #1378."""
    doc = _license_sbom(
        tmp_path, classifiers=["License :: OSI Approved :: BSD License"]
    )

    expected = {
        "licenseDeclared": "LicenseRef-license-osi-approved-bsd-license-a9d12a80",
        "licenseConcluded": "NOASSERTION",
        "licenseComments": (
            "License inherited from the upstream project's declared Python "
            "package metadata (License classifiers) and not independently "
            "verified by fromager; it may be imprecise or incomplete. No "
            "unambiguous SPDX mapping for: License :: OSI Approved :: BSD License."
        ),
    }
    for package in doc["packages"]:
        assert {key: package[key] for key in expected} == expected
    assert doc["hasExtractedLicensingInfos"] == [
        {
            "licenseId": "LicenseRef-license-osi-approved-bsd-license-a9d12a80",
            "extractedText": "License :: OSI Approved :: BSD License",
        }
    ]
    _validate_spdx(doc)


def test_generate_sbom_no_license_metadata(tmp_path: pathlib.Path) -> None:
    """Verify missing license data is reported as NOASSERTION."""
    doc = _license_sbom(tmp_path)

    for package in doc["packages"]:
        assert package["licenseDeclared"] == "NOASSERTION"
        assert package["licenseConcluded"] == "NOASSERTION"
        assert package["licenseComments"] == sbom._NO_LICENSE_COMMENT
    assert "hasExtractedLicensingInfos" not in doc
    _validate_spdx(doc)


def test_generate_sbom_license_ref_in_expression(tmp_path: pathlib.Path) -> None:
    """Verify an upstream LicenseRef gets the extracted info SPDX requires."""
    doc = _license_sbom(tmp_path, license_expression="MIT OR LicenseRef-Proprietary")

    assert doc["packages"][0]["licenseDeclared"] == "MIT OR LicenseRef-Proprietary"
    assert doc["hasExtractedLicensingInfos"] == [
        {
            "licenseId": "LicenseRef-Proprietary",
            "name": "Proprietary",
            "extractedText": "NOASSERTION",
            "comment": (
                "Declared in the upstream project's License-Expression: "
                "MIT OR LicenseRef-Proprietary. The license text is not "
                "available in the package metadata."
            ),
        }
    ]
    _validate_spdx(doc)


def test_generate_sbom_license_refs_listed_once_in_order(
    tmp_path: pathlib.Path,
) -> None:
    """Verify each distinct upstream LicenseRef gets exactly one entry."""
    expression = "LicenseRef-B OR (MIT AND LicenseRef-A) OR LicenseRef-B"
    doc = _license_sbom(tmp_path, license_expression=expression)

    assert doc["packages"][0]["licenseDeclared"] == expression
    assert [e["licenseId"] for e in doc["hasExtractedLicensingInfos"]] == [
        "LicenseRef-B",
        "LicenseRef-A",
    ]
    _validate_spdx(doc)


def test_generate_sbom_curated_license_ref(tmp_path: pathlib.Path) -> None:
    """Verify a curated mapping to a LicenseRef also gets extracted info."""
    doc = _license_sbom(tmp_path, license="NVIDIA Proprietary Software")

    assert doc["packages"][0]["licenseDeclared"] == "LicenseRef-NVIDIA-SOFTWARE-LICENSE"
    assert doc["hasExtractedLicensingInfos"] == [
        {
            "licenseId": "LicenseRef-NVIDIA-SOFTWARE-LICENSE",
            "name": "NVIDIA-SOFTWARE-LICENSE",
            "extractedText": "NOASSERTION",
            "comment": (
                "Declared in the upstream project's License: NVIDIA Proprietary "
                "Software. The license text is not available in the package "
                "metadata."
            ),
        }
    ]
    _validate_spdx(doc)


def test_generate_sbom_long_license_text(tmp_path: pathlib.Path) -> None:
    """Verify folded full license text keeps ids and comments short."""
    text = "Copyright (c) 2005-2023, NumPy Developers.\n" + "\n".join(
        f"        line {i} of the license text" for i in range(2000)
    )

    doc = _license_sbom(tmp_path, license=text)

    package = doc["packages"][0]
    (extracted,) = doc["hasExtractedLicensingInfos"]
    assert extracted["licenseId"] == package["licenseDeclared"]
    assert not any(
        line.startswith(" ") for line in extracted["extractedText"].splitlines()
    )
    slug = package["licenseDeclared"].removeprefix("LicenseRef-").rsplit("-", 1)[0]
    assert len(slug) <= 40
    assert len(package["licenseComments"]) <= (
        len(sbom._LICENSE_COMMENT)
        + len(sbom._UNMAPPED_COMMENT)
        + sbom._COMMENT_RAW_MAX
        + 10
    )
    _validate_spdx(doc)


def test_generate_sbom_license_with_unparsed_field(tmp_path: pathlib.Path) -> None:
    """Verify a found license keeps its comment and names unreadable fields."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test==1.0"),
        version=Version("1.0"),
        metadata=_metadata(license_expression="MIT"),
        unparsed_fields=["Classifier"],
    )

    package = doc["packages"][0]
    assert package["licenseDeclared"] == "MIT"
    assert package["licenseComments"] == (
        sbom._LICENSE_COMMENT.format(source="License-Expression")
        + " Unparseable fields: Classifier."
    )
    _validate_spdx(doc)


def test_merge_cyclonedx_sbom_imports_packages_and_relationships(
    tmp_path: pathlib.Path,
) -> None:
    """Verify Maturin CycloneDX data is represented in SPDX."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    document = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("example-pkg==1.2.3"),
        version=Version("1.2.3"),
        metadata=_metadata(),
    )
    sboms_dir = tmp_path / "sboms"
    _write_cyclonedx_sbom(sboms_dir, "example.cyclonedx.json")

    sbom.merge_cyclonedx_sboms(
        sbom=document, sboms_dir=sboms_dir, name="example-pkg", version="1.2.3"
    )

    packages = {package["name"]: package for package in document["packages"]}
    assert {"example-pkg", "example", "serde"} <= packages.keys()
    assert "pyo3" not in packages
    serde = packages["serde"]
    assert serde["externalRefs"][0]["referenceLocator"] == "pkg:cargo/serde@1.0.0"
    assert serde["checksums"] == [{"algorithm": "SHA256", "checksumValue": "a" * 64}]
    assert serde["licenseDeclared"] == "MIT"
    assert "comment" not in serde
    spdx_ids = {package["name"]: package["SPDXID"] for package in document["packages"]}
    relationships = {
        (
            relationship["spdxElementId"],
            relationship["relationshipType"],
            relationship["relatedSpdxElement"],
        )
        for relationship in document["relationships"]
    }
    assert ("SPDXRef-wheel", "CONTAINS", spdx_ids["example"]) in relationships
    assert ("SPDXRef-wheel", "CONTAINS", spdx_ids["serde"]) in relationships
    assert not any(
        relationship_type == "DEPENDS_ON" for _, relationship_type, _ in relationships
    )
    _validate_spdx(document)


def test_cyclonedx_checksums_skips_unsupported_algorithm() -> None:
    """SHA3-224 has no SPDX 2.3 equivalent and must be dropped."""
    component = {
        "name": "serde",
        "hashes": [
            {"alg": "SHA3-224", "content": "a" * 56},
            {"alg": "SHA-256", "content": "b" * 64},
        ],
    }

    checksums = sbom._cyclonedx_checksums(component)

    assert checksums == [{"algorithm": "SHA256", "checksumValue": "b" * 64}]


def test_cyclonedx_checksums_skips_non_hex_content() -> None:
    """Non-hexadecimal checksum content would fail SPDX validation."""
    component = {
        "name": "serde",
        "hashes": [
            {"alg": "SHA-256", "content": "not-a-valid-hash"},
            {"alg": "SHA-512", "content": "c" * 128},
        ],
    }

    checksums = sbom._cyclonedx_checksums(component)

    assert checksums == [{"algorithm": "SHA512", "checksumValue": "c" * 128}]


def test_cyclonedx_license_expression_skips_invalid() -> None:
    """Invalid SPDX expressions must not be copied into licenseDeclared."""
    component = {
        "name": "serde",
        "licenses": [
            {"expression": "MIT"},
            {"expression": "Totally Not A License"},
        ],
    }

    assert sbom._cyclonedx_license_expression(component) == "MIT"


def test_cyclonedx_license_expression_all_invalid_returns_none() -> None:
    """A component with only invalid expressions declares no license."""
    component = {"name": "serde", "licenses": [{"license": {"id": "Bogus-9.9"}}]}

    assert sbom._cyclonedx_license_expression(component) is None


def test_cyclonedx_license_expression_groups_or_operands() -> None:
    """OR expressions must be parenthesized so AND-joining cannot weaken them."""
    component = {
        "name": "serde",
        "licenses": [
            {"expression": "MIT OR Apache-2.0"},
            {"expression": "BSD-3-Clause"},
        ],
    }

    assert (
        sbom._cyclonedx_license_expression(component)
        == "(MIT OR Apache-2.0) AND BSD-3-Clause"
    )


def test_merge_cyclonedx_sboms_maps_python_root_to_wheel(
    tmp_path: pathlib.Path,
) -> None:
    """Verify an auditwheel Python root is attached to the wheel package."""
    settings = SbomSettings(repository_url=AnyUrl("https://pkg.test/simple/"))
    ctx = make_sbom_ctx(tmp_path, sbom_settings=settings)
    document = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("pillow==12.3.0"),
        version=Version("12.3.0"),
        metadata=_metadata(),
    )
    sboms_dir = tmp_path / "sboms"
    auditwheel = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {
            "component": {
                "type": "library",
                "bom-ref": "pkg:pypi/pillow@12.3.0?file_name=pillow.whl",
                "name": "Pillow",
                "version": "12.3.0",
                "purl": "pkg:pypi/pillow@12.3.0?file_name=pillow.whl",
            }
        },
        "components": [
            {
                "type": "library",
                "bom-ref": "pkg:rpm/almalinux/libXau@1.0.9-3.el8",
                "name": "libXau",
                "version": "1.0.9-3.el8",
                "purl": "pkg:rpm/almalinux/libXau@1.0.9-3.el8",
            }
        ],
        "dependencies": [
            {
                "ref": "pkg:pypi/pillow@12.3.0?file_name=pillow.whl",
                "dependsOn": ["pkg:rpm/almalinux/libXau@1.0.9-3.el8"],
            }
        ],
    }
    sboms_dir.mkdir(parents=True)
    (sboms_dir / "auditwheel.cdx.json").write_text(json.dumps(auditwheel))

    sbom.merge_cyclonedx_sboms(
        sbom=document, sboms_dir=sboms_dir, name="pillow", version="12.3.0"
    )

    packages = document["packages"]
    assert len(packages) == 3
    rpm = next(package for package in packages if package["name"] == "libXau")
    relationships = {
        (
            relationship["spdxElementId"],
            relationship["relationshipType"],
            relationship["relatedSpdxElement"],
        )
        for relationship in document["relationships"]
    }
    assert ("SPDXRef-wheel", "CONTAINS", rpm["SPDXID"]) in relationships
    assert not any(
        relationship_type == "DEPENDS_ON" for _, relationship_type, _ in relationships
    )
    _validate_spdx(document)


def test_merge_cyclonedx_sboms_maps_python_root_with_purl_version_override(
    tmp_path: pathlib.Path,
) -> None:
    """Verify a purl version override does not stop the root matching."""
    ctx = make_sbom_ctx(
        tmp_path,
        sbom_settings=SbomSettings(),
        package_overrides={"purl": {"version": "0.5.5+local.1"}},
    )
    document = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test-pkg==0.5.5"),
        version=Version("0.5.5"),
    )
    wheel = next(
        package
        for package in document["packages"]
        if package["SPDXID"] == "SPDXRef-wheel"
    )
    assert wheel["versionInfo"] == "0.5.5+local.1"
    root_purl = "pkg:pypi/test-pkg@0.5.5"
    maturin = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {
            "component": {
                "type": "library",
                "bom-ref": root_purl,
                "name": "test-pkg",
                "version": "0.5.5",
                "purl": root_purl,
            }
        },
        "components": [
            {
                "type": "library",
                "bom-ref": "pkg:cargo/serde@1.0.0",
                "name": "serde",
                "version": "1.0.0",
                "purl": "pkg:cargo/serde@1.0.0",
            }
        ],
    }
    sboms_dir = tmp_path / "sboms"
    sboms_dir.mkdir()
    (sboms_dir / "maturin.cdx.json").write_text(json.dumps(maturin))

    sbom.merge_cyclonedx_sboms(
        sbom=document, sboms_dir=sboms_dir, name="test-pkg", version="0.5.5"
    )

    assert len(document["packages"]) == 3
    serde = next(
        package for package in document["packages"] if package["name"] == "serde"
    )
    contains = {
        relationship["relatedSpdxElement"]
        for relationship in document["relationships"]
        if relationship["relationshipType"] == "CONTAINS"
    }
    assert contains == {serde["SPDXID"]}
    _validate_spdx(document)


def test_merge_cyclonedx_sboms_does_not_map_unrelated_python_root_to_wheel(
    tmp_path: pathlib.Path,
) -> None:
    """Verify an unrelated PyPI root remains its own SPDX package."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    document = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("pillow==12.3.0"),
        version=Version("12.3.0"),
        metadata=_metadata(),
    )
    root_purl = "pkg:pypi/unrelated@2.0"
    dependency_purl = "pkg:rpm/almalinux/libXau@1.0.9-3.el8"
    cyclonedx = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {
            "component": {
                "type": "library",
                "bom-ref": root_purl,
                "name": "unrelated",
                "version": "2.0",
                "purl": root_purl,
            }
        },
        "components": [
            {
                "type": "library",
                "bom-ref": dependency_purl,
                "name": "libXau",
                "version": "1.0.9-3.el8",
                "purl": dependency_purl,
            }
        ],
        "dependencies": [
            {"ref": root_purl, "dependsOn": [dependency_purl]},
        ],
    }
    sboms_dir = tmp_path / "sboms"
    sboms_dir.mkdir()
    (sboms_dir / "custom.cyclonedx.json").write_text(json.dumps(cyclonedx))

    sbom.merge_cyclonedx_sboms(
        sbom=document, sboms_dir=sboms_dir, name="example-pkg", version="1.2.3"
    )

    packages = {package["name"]: package for package in document["packages"]}
    assert {"unrelated", "libXau"} <= packages.keys()
    assert packages["unrelated"]["SPDXID"] != "SPDXRef-wheel"
    relationships = {
        (
            relationship["spdxElementId"],
            relationship["relationshipType"],
            relationship["relatedSpdxElement"],
        )
        for relationship in document["relationships"]
    }
    assert (
        "SPDXRef-wheel",
        "CONTAINS",
        packages["unrelated"]["SPDXID"],
    ) in relationships
    assert (
        "SPDXRef-wheel",
        "CONTAINS",
        packages["libXau"]["SPDXID"],
    ) in relationships
    assert not any(
        relationship_type == "DEPENDS_ON" for _, relationship_type, _ in relationships
    )
    _validate_spdx(document)


def test_merge_cyclonedx_sboms_imports_nested_components(
    tmp_path: pathlib.Path,
) -> None:
    """Verify nested target components are imported and linked."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    document = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("example-pkg==1.2.3"),
        version=Version("1.2.3"),
        metadata=_metadata(),
    )
    root_purl = "pkg:cargo/example@1.0.0?download_url=file://."
    target_purl = "pkg:cargo/example-target@1.0.0?download_url=file://../target"
    nested_purl = "pkg:cargo/example-nested@1.0.0"
    cyclonedx = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": root_purl,
                "name": "example",
                "version": "1.0.0",
                "purl": root_purl,
            }
        },
        "components": [
            {
                "type": "library",
                "bom-ref": target_purl,
                "name": "example-target",
                "version": "1.0.0",
                "purl": target_purl,
                "components": [
                    {
                        "type": "library",
                        "bom-ref": nested_purl,
                        "name": "example-nested",
                        "version": "1.0.0",
                        "purl": nested_purl,
                    }
                ],
            }
        ],
        "dependencies": [
            {"ref": root_purl, "dependsOn": [target_purl]},
            {"ref": target_purl, "dependsOn": [nested_purl]},
        ],
    }
    sboms_dir = tmp_path / "sboms"
    sboms_dir.mkdir()
    (sboms_dir / "nested.cyclonedx.json").write_text(json.dumps(cyclonedx))

    sbom.merge_cyclonedx_sboms(
        sbom=document, sboms_dir=sboms_dir, name="example-pkg", version="1.2.3"
    )

    packages = {package["name"]: package for package in document["packages"]}
    assert {"example", "example-target", "example-nested"} <= packages.keys()
    relationships = {
        (
            relationship["spdxElementId"],
            relationship["relationshipType"],
            relationship["relatedSpdxElement"],
        )
        for relationship in document["relationships"]
    }
    assert {
        package["externalRefs"][0]["referenceLocator"]
        for package in (
            packages["example"],
            packages["example-target"],
            packages["example-nested"],
        )
    } == {
        "pkg:cargo/example@1.0.0",
        "pkg:cargo/example-target@1.0.0",
        "pkg:cargo/example-nested@1.0.0",
    }
    for package_name in ("example", "example-target", "example-nested"):
        assert (
            "SPDXRef-wheel",
            "CONTAINS",
            packages[package_name]["SPDXID"],
        ) in relationships
    assert not any(
        relationship_type == "DEPENDS_ON" for _, relationship_type, _ in relationships
    )
    _validate_spdx(document)


def test_merge_cyclonedx_sboms_deduplicates_packages_by_purl(
    tmp_path: pathlib.Path,
) -> None:
    """Verify repeated Cargo components produce one SPDX package."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    document = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("example-pkg==1.2.3"),
        version=Version("1.2.3"),
        metadata=_metadata(),
    )
    sboms_dir = tmp_path / "sboms"
    _write_cyclonedx_sbom(sboms_dir, "first.cyclonedx.json")
    _write_cyclonedx_sbom(
        sboms_dir,
        "second.cyclonedx.json",
        root_name="another",
    )

    sbom.merge_cyclonedx_sboms(
        sbom=document, sboms_dir=sboms_dir, name="example-pkg", version="1.2.3"
    )

    serde_packages = [
        package for package in document["packages"] if package["name"] == "serde"
    ]
    assert len(serde_packages) == 1
    assert (
        sum(
            relationship["relationshipType"] == "CONTAINS"
            and relationship["relatedSpdxElement"] == serde_packages[0]["SPDXID"]
            for relationship in document["relationships"]
        )
        == 1
    )
    _validate_spdx(document)


def test_merge_cyclonedx_sboms_ignores_invalid_and_other_formats(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify unrelated or unreadable SBOM files do not break the merge."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    document = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("example-pkg==1.2.3"),
        version=Version("1.2.3"),
        metadata=_metadata(),
    )
    sboms_dir = tmp_path / "sboms"
    sboms_dir.mkdir()
    (sboms_dir / "not-an-sbom.json").write_text('{"format": "other"}')
    (sboms_dir / "broken.json").write_text("{")

    with caplog.at_level("WARNING", logger="fromager.sbom"):
        sbom.merge_cyclonedx_sboms(
            sbom=document, sboms_dir=sboms_dir, name="example-pkg", version="1.2.3"
        )

    assert len(document["packages"]) == 2
    assert "could not read" in caplog.text
    _validate_spdx(document)
