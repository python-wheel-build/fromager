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

python3 "$SCRIPTDIR/verify_sbom_licenses.py" "$OUTDIR/wheels-repo/downloads"
