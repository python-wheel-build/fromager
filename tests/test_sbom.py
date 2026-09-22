import json
import pathlib
import typing

import pytest
from conftest import make_sbom_ctx
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
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("my-package==2.0.0"),
        version=Version("2.0.0"),
    )

    wheel = doc["packages"][0]
    assert wheel["supplier"] == "Organization: ExampleCo"
    assert doc["documentNamespace"] == (
        "https://www.example.com/my-package-2.0.0.spdx.json"
    )
    creators = doc["creationInfo"]["creators"]
    assert "Organization: ExampleCo" in creators
    assert any("fromager" in c for c in creators)
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


def test_merge_cyclonedx_sbom_imports_packages_and_relationships(
    tmp_path: pathlib.Path,
) -> None:
    """Verify Maturin CycloneDX data is represented in SPDX."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    document = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("example-pkg==1.2.3"),
        version=Version("1.2.3"),
    )
    sboms_dir = tmp_path / "sboms"
    _write_cyclonedx_sbom(sboms_dir, "example.cyclonedx.json")

    sbom.merge_cyclonedx_sboms(sbom=document, sboms_dir=sboms_dir)

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


def test_merge_cyclonedx_sboms_maps_python_root_to_wheel(
    tmp_path: pathlib.Path,
) -> None:
    """Verify an auditwheel Python root is attached to the wheel package."""
    settings = SbomSettings(repository_url=AnyUrl("https://packages.redhat.com"))
    ctx = make_sbom_ctx(tmp_path, sbom_settings=settings)
    document = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("pillow==12.3.0"),
        version=Version("12.3.0"),
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

    sbom.merge_cyclonedx_sboms(sbom=document, sboms_dir=sboms_dir)

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


def test_merge_cyclonedx_sboms_does_not_map_unrelated_python_root_to_wheel(
    tmp_path: pathlib.Path,
) -> None:
    """Verify an unrelated PyPI root remains its own SPDX package."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    document = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("pillow==12.3.0"),
        version=Version("12.3.0"),
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

    sbom.merge_cyclonedx_sboms(sbom=document, sboms_dir=sboms_dir)

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

    sbom.merge_cyclonedx_sboms(sbom=document, sboms_dir=sboms_dir)

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
    )
    sboms_dir = tmp_path / "sboms"
    _write_cyclonedx_sbom(sboms_dir, "first.cyclonedx.json")
    _write_cyclonedx_sbom(
        sboms_dir,
        "second.cyclonedx.json",
        root_name="another",
    )

    sbom.merge_cyclonedx_sboms(sbom=document, sboms_dir=sboms_dir)

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
    )
    sboms_dir = tmp_path / "sboms"
    sboms_dir.mkdir()
    (sboms_dir / "not-an-sbom.json").write_text('{"format": "other"}')
    (sboms_dir / "broken.json").write_text("{")

    with caplog.at_level("WARNING", logger="fromager.sbom"):
        sbom.merge_cyclonedx_sboms(sbom=document, sboms_dir=sboms_dir)

    assert len(document["packages"]) == 2
    assert "could not read" in caplog.text
    _validate_spdx(document)


def test_merge_cyclonedx_sboms_names_spdx_ids_and_disambiguates(
    tmp_path: pathlib.Path,
) -> None:
    """Verify SPDXIDs use name+version and stay unique on collisions."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    document = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("example-pkg==1.2.3"),
        version=Version("1.2.3"),
    )
    # Two distinct components share the same name and version but differ by
    # purl subpath, exactly like a crate and its library target.
    cyclonedx = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": [
            {
                "type": "library",
                "name": "hf_xet",
                "version": "1.6.0",
                "purl": "pkg:cargo/hf_xet@1.6.0",
            },
            {
                "type": "library",
                "name": "hf_xet",
                "version": "1.6.0",
                "purl": "pkg:cargo/hf_xet@1.6.0#src/lib.rs",
            },
        ],
    }
    sboms_dir = tmp_path / "sboms"
    sboms_dir.mkdir()
    (sboms_dir / "hf_xet.cyclonedx.json").write_text(json.dumps(cyclonedx))

    sbom.merge_cyclonedx_sboms(sbom=document, sboms_dir=sboms_dir)

    ids = [package["SPDXID"] for package in document["packages"]]
    # cargo's underscore is sanitized to a dash and IDs remain unique.
    assert "SPDXRef-hf-xet-1.6.0" in ids
    assert "SPDXRef-hf-xet-1.6.0-2" in ids
    assert len(ids) == len(set(ids))
    _validate_spdx(document)


def test_merge_cyclonedx_sboms_warns_on_multiple_license_entries(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify ambiguous multi-license components are skipped with a warning."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    document = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("example-pkg==1.2.3"),
        version=Version("1.2.3"),
    )
    cyclonedx = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": [
            {
                "type": "library",
                "name": "multi",
                "version": "1.0.0",
                "purl": "pkg:cargo/multi@1.0.0",
                "licenses": [
                    {"license": {"id": "MIT"}},
                    {"license": {"id": "Apache-2.0"}},
                ],
            }
        ],
    }
    sboms_dir = tmp_path / "sboms"
    sboms_dir.mkdir()
    (sboms_dir / "multi.cyclonedx.json").write_text(json.dumps(cyclonedx))

    with caplog.at_level("WARNING", logger="fromager.sbom"):
        sbom.merge_cyclonedx_sboms(sbom=document, sboms_dir=sboms_dir)

    multi = next(p for p in document["packages"] if p["name"] == "multi")
    assert "licenseDeclared" not in multi
    assert "license entries" in caplog.text
    _validate_spdx(document)


def test_merge_cyclonedx_sboms_adds_document_comment(
    tmp_path: pathlib.Path,
) -> None:
    """Verify a document comment references the merged CycloneDX files."""
    ctx = make_sbom_ctx(tmp_path, sbom_settings=SbomSettings())
    document = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("example-pkg==1.2.3"),
        version=Version("1.2.3"),
    )
    sboms_dir = tmp_path / "sboms"
    _write_cyclonedx_sbom(sboms_dir, "example.cyclonedx.json")

    sbom.merge_cyclonedx_sboms(sbom=document, sboms_dir=sboms_dir)

    assert "example.cyclonedx.json" in document["comment"]
    _validate_spdx(document)
