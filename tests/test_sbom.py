import json
import pathlib

from packaging.requirements import Requirement
from packaging.version import Version

from fromager import context, packagesettings, sbom
from fromager.packagesettings import SbomSettings


def _make_ctx(
    tmp_path: pathlib.Path,
    sbom_settings: SbomSettings | None = None,
    purl: str | None = None,
) -> context.WorkContext:
    """Create a minimal WorkContext with SBOM settings."""
    settings_file = packagesettings.SettingsFile(sbom=sbom_settings)
    settings = packagesettings.Settings(
        settings=settings_file,
        package_settings=[],
        patches_dir=tmp_path / "patches",
        variant="cpu",
        max_jobs=None,
    )
    if purl is not None:
        # Create a package setting with purl override
        ps = packagesettings.PackageSettings.from_mapping(
            "test-pkg",
            {"purl": purl},
            source="test",
            has_config=True,
        )
        settings._package_settings[ps.name] = ps
    ctx = context.WorkContext(
        active_settings=settings,
        constraints_file=None,
        patches_dir=tmp_path / "patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
    )
    return ctx


def test_generate_sbom_structure(tmp_path: pathlib.Path) -> None:
    """Verify the generated SBOM has the required SPDX 2.3 fields."""
    ctx = _make_ctx(tmp_path, sbom_settings=SbomSettings())
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


def test_generate_sbom_default_settings(tmp_path: pathlib.Path) -> None:
    """Verify defaults when no custom settings are provided."""
    ctx = _make_ctx(tmp_path, sbom_settings=SbomSettings())
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("my-package==2.0.0"),
        version=Version("2.0.0"),
    )

    pkg = doc["packages"][0]
    assert pkg["supplier"] == "NOASSERTION"
    assert "externalRefs" not in pkg
    assert doc["documentNamespace"] == (
        "https://spdx.org/spdxdocs/my-package-2.0.0.spdx.json"
    )


def test_generate_sbom_custom_settings(tmp_path: pathlib.Path) -> None:
    """Verify custom supplier, namespace, and creators are used."""
    settings = SbomSettings(
        supplier="Organization: ExampleCo",
        namespace="https://www.example.com",
        creators=["Organization: ExampleCo"],
    )
    ctx = _make_ctx(tmp_path, sbom_settings=settings)
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("my-package==2.0.0"),
        version=Version("2.0.0"),
    )

    pkg = doc["packages"][0]
    assert pkg["supplier"] == "Organization: ExampleCo"
    assert doc["documentNamespace"] == (
        "https://www.example.com/my-package-2.0.0.spdx.json"
    )
    creators = doc["creationInfo"]["creators"]
    assert "Organization: ExampleCo" in creators
    assert any("fromager" in c for c in creators)


def test_generate_sbom_purl_override(tmp_path: pathlib.Path) -> None:
    """Verify per-package purl override is used with template substitution."""
    ctx = _make_ctx(
        tmp_path,
        sbom_settings=SbomSettings(),
        purl="pkg:generic/{name}@{version}",
    )
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test-pkg==1.0.0"),
        version=Version("1.0.0"),
    )

    pkg = doc["packages"][0]
    ext_refs = pkg["externalRefs"]
    assert len(ext_refs) == 1
    assert ext_refs[0]["referenceLocator"] == "pkg:generic/test-pkg@1.0.0"


def test_generate_sbom_no_purl_without_override(tmp_path: pathlib.Path) -> None:
    """Verify no externalRefs when no purl override is set."""
    ctx = _make_ctx(tmp_path, sbom_settings=SbomSettings())
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test==0.1.0"),
        version=Version("0.1.0"),
    )

    pkg = doc["packages"][0]
    assert "externalRefs" not in pkg


def test_generate_sbom_describes_relationship(tmp_path: pathlib.Path) -> None:
    """Verify the DESCRIBES relationship exists."""
    ctx = _make_ctx(tmp_path, sbom_settings=SbomSettings())
    doc = sbom.generate_sbom(
        ctx=ctx,
        req=Requirement("test==0.1.0"),
        version=Version("0.1.0"),
    )

    rels = doc["relationships"]
    assert len(rels) == 1
    assert rels[0]["spdxElementId"] == "SPDXRef-DOCUMENT"
    assert rels[0]["relationshipType"] == "DESCRIBES"
    assert rels[0]["relatedSpdxElement"] == "SPDXRef-wheel"


def test_write_sbom_creates_file(tmp_path: pathlib.Path) -> None:
    """Verify write_sbom creates sboms/ dir and writes valid JSON."""
    dist_info_dir = tmp_path / "pkg-1.0.dist-info"
    dist_info_dir.mkdir()

    ctx = _make_ctx(tmp_path, sbom_settings=SbomSettings())
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


def test_write_sbom_preserves_existing_files(tmp_path: pathlib.Path) -> None:
    """Verify write_sbom does not overwrite existing SBOM files."""
    dist_info_dir = tmp_path / "pkg-1.0.dist-info"
    sboms_dir = dist_info_dir / "sboms"
    sboms_dir.mkdir(parents=True)
    existing = sboms_dir / "cyclonedx.json"
    existing.write_text('{"bomFormat": "CycloneDX"}')

    ctx = _make_ctx(tmp_path, sbom_settings=SbomSettings())
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
