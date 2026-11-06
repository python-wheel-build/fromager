#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test that the SBOM embedded in each built wheel carries the license the
# wheel declares in its METADATA (issue #1378).
#
# idna 3.6 only has the ambiguous "BSD License" classifier, so it must get
# a LicenseRef with extracted licensing info. tomli 2.0.1 has the "MIT
# License" classifier, which maps cleanly to MIT.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

fromager \
  --log-file="$OUTDIR/bootstrap.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-file="$SCRIPTDIR/sbom_settings.yaml" \
  bootstrap 'idna==3.6' 'tomli==2.0.1'

find "$OUTDIR/wheels-repo/downloads/" -name '*.whl'

python3 - "$OUTDIR/wheels-repo/downloads" <<'EOF'
import json
import pathlib
import re
import sys
import zipfile

downloads = pathlib.Path(sys.argv[1])
failures = []


def sbom_of(wheel):
    with zipfile.ZipFile(wheel) as zf:
        (name,) = [n for n in zf.namelist() if n.endswith(".dist-info/sboms/fromager.spdx.json")]
        return json.loads(zf.read(name))


def check(condition, message):
    if not condition:
        failures.append(message)


# invariants for every built wheel, including build dependencies
wheels = sorted(downloads.glob("*.whl"))
check(wheels, f"no wheels found in {downloads}")
for wheel in wheels:
    doc = sbom_of(wheel)
    wheel_pkg, upstream_pkg = doc["packages"]
    for key in ("licenseDeclared", "licenseConcluded", "licenseComments"):
        check(key in wheel_pkg and key in upstream_pkg, f"{wheel.name}: {key} missing from a package")
        check(wheel_pkg.get(key) == upstream_pkg.get(key), f"{wheel.name}: {key} differs between packages")
    check(wheel_pkg.get("licenseConcluded") == "NOASSERTION", f"{wheel.name}: licenseConcluded is not NOASSERTION")
    declared_ids = {e["licenseId"] for e in doc.get("hasExtractedLicensingInfos", [])}
    for ref in re.findall(r"LicenseRef-[A-Za-z0-9.\-]+", wheel_pkg.get("licenseDeclared", "")):
        check(ref in declared_ids, f"{wheel.name}: {ref} has no extracted licensing info")

# ambiguous classifier: LicenseRef plus extracted licensing info
idna = sbom_of(next(downloads.glob("idna-3.6-*.whl")))
idna_ref = "LicenseRef-license-osi-approved-bsd-license-a9d12a80"
idna_pkg = idna["packages"][0]
check(idna_pkg.get("licenseDeclared") == idna_ref, f"idna: licenseDeclared is {idna_pkg.get('licenseDeclared')!r}")
check(
    idna.get("hasExtractedLicensingInfos") == [{"licenseId": idna_ref, "extractedText": "License :: OSI Approved :: BSD License"}],
    f"idna: unexpected hasExtractedLicensingInfos {idna.get('hasExtractedLicensingInfos')!r}",
)
check("(License classifiers)" in idna_pkg.get("licenseComments", ""), "idna: comment does not name the source")

# unambiguous classifier: plain SPDX id, no extracted licensing info
tomli = sbom_of(next(downloads.glob("tomli-2.0.1-*.whl")))
tomli_pkg = tomli["packages"][0]
check(tomli_pkg.get("licenseDeclared") == "MIT", f"tomli: licenseDeclared is {tomli_pkg.get('licenseDeclared')!r}")
check("hasExtractedLicensingInfos" not in tomli, "tomli: unexpected hasExtractedLicensingInfos")

for failure in failures:
    print(f"FAIL: {failure}", file=sys.stderr)
print(f"checked {len(wheels)} wheels, {len(failures)} failure(s)")
sys.exit(1 if failures else 0)
EOF
