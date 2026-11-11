#!/usr/bin/env python3
"""Verify that wheel SBOMs carry the license declared in wheel metadata.

`test_sbom_licenses.sh` passes the directory holding the built wheels. Every
failed check is reported, and the exit status is non-zero when any check
fails.
"""

import json
import pathlib
import re
import sys
import zipfile
from typing import Any

SPDX_FILE_SUFFIX = ".dist-info/sboms/fromager.spdx.json"
LICENSE_REF_RE = re.compile(r"LicenseRef-[A-Za-z0-9.\-]+")

# idna 3.6 only declares the ambiguous "BSD License" classifier, so its
# license becomes a LicenseRef with the classifier as extracted text.
IDNA_LICENSE_REF = "LicenseRef-license-osi-approved-bsd-license-a9d12a80"
IDNA_EXTRACTED_INFO = [
    {
        "licenseId": IDNA_LICENSE_REF,
        "extractedText": "License :: OSI Approved :: BSD License",
    }
]


def sbom_of(wheel: pathlib.Path) -> dict[str, Any]:
    """Return the SBOM embedded in *wheel*."""
    with zipfile.ZipFile(wheel) as zf:
        (name,) = [n for n in zf.namelist() if n.endswith(SPDX_FILE_SUFFIX)]
        doc: dict[str, Any] = json.loads(zf.read(name))
        return doc


def check_license_fields(
    wheel: pathlib.Path, doc: dict[str, Any], failures: list[str]
) -> None:
    """Check the invariants that must hold for every built wheel."""
    wheel_pkg, upstream_pkg = doc["packages"]
    for key in ("licenseDeclared", "licenseConcluded", "licenseComments"):
        if key not in wheel_pkg or key not in upstream_pkg:
            failures.append(f"{wheel.name}: {key} missing from a package")
        elif wheel_pkg[key] != upstream_pkg[key]:
            failures.append(f"{wheel.name}: {key} differs between packages")
    if wheel_pkg.get("licenseConcluded") != "NOASSERTION":
        failures.append(f"{wheel.name}: licenseConcluded is not NOASSERTION")
    declared_ids = {
        info["licenseId"] for info in doc.get("hasExtractedLicensingInfos", [])
    }
    for ref in LICENSE_REF_RE.findall(wheel_pkg.get("licenseDeclared", "")):
        if ref not in declared_ids:
            failures.append(f"{wheel.name}: {ref} has no extracted licensing info")


def check_idna(downloads: pathlib.Path, failures: list[str]) -> None:
    """Check the ambiguous-classifier case in the idna 3.6 wheel."""
    idna = sbom_of(next(downloads.glob("idna-3.6-*.whl")))
    pkg = idna["packages"][0]
    declared = pkg.get("licenseDeclared")
    if declared != IDNA_LICENSE_REF:
        failures.append(f"idna: licenseDeclared is {declared!r}")
    extracted = idna.get("hasExtractedLicensingInfos")
    if extracted != IDNA_EXTRACTED_INFO:
        failures.append(f"idna: unexpected hasExtractedLicensingInfos {extracted!r}")
    if "(License classifiers)" not in pkg.get("licenseComments", ""):
        failures.append("idna: comment does not name the source")


def check_tomli(downloads: pathlib.Path, failures: list[str]) -> None:
    """Check that the unambiguous "MIT License" classifier maps cleanly to MIT."""
    tomli = sbom_of(next(downloads.glob("tomli-2.0.1-*.whl")))
    declared = tomli["packages"][0].get("licenseDeclared")
    if declared != "MIT":
        failures.append(f"tomli: licenseDeclared is {declared!r}")
    if "hasExtractedLicensingInfos" in tomli:
        failures.append("tomli: unexpected hasExtractedLicensingInfos")


def verify(downloads: pathlib.Path) -> tuple[list[str], int]:
    """Return the failed checks and the number of wheels checked."""
    failures: list[str] = []
    wheels = sorted(downloads.glob("*.whl"))
    if not wheels:
        failures.append(f"no wheels found in {downloads}")
    for wheel in wheels:
        check_license_fields(wheel, sbom_of(wheel), failures)

    check_idna(downloads, failures)
    check_tomli(downloads, failures)
    return failures, len(wheels)


def main(argv: list[str]) -> int:
    """Run the checks against the downloads directory in *argv*."""
    if len(argv) != 1:
        program = pathlib.Path(sys.argv[0]).name
        print(f"usage: {program} DOWNLOADS_DIR", file=sys.stderr)
        return 2

    failures, wheel_count = verify(pathlib.Path(argv[0]))
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    print(f"checked {wheel_count} wheels, {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
