#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Tests full bootstrap with build tags

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# bootstrap stevedore with 1 change log
fromager \
  --log-file="$OUTDIR/bootstrap1.log" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings" \
  bootstrap 'stevedore==5.2.0'

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/stevedore-5.2.0-1*.whl
"

pass=true
for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

$pass

# bootstrap stevedore again with 1 change log without a file in the downloads
# cache but with a file in the cache package server. Should not result in a
# build because the file exists in the cache server directory.

find "$OUTDIR/wheels-repo"
# replace the symlink in the index dir with an actual file so it can be
# downloaded, and remove the wheels from the disk cache so we know we get the
# file from the web server
rm -f $OUTDIR/wheels-repo/simple/stevedore/*.whl
mv $OUTDIR/wheels-repo/downloads/stevedore*.whl $OUTDIR/wheels-repo/simple/stevedore/
rm -f $OUTDIR/wheels-repo/build/*.whl
rm -f $OUTDIR/wheels-repo/downloads/*.whl
find "$OUTDIR/wheels-repo"
start_local_wheel_server

LOGFILE="$OUTDIR/bootstrap2.log"
fromager \
  --log-file="$LOGFILE" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-file="$SCRIPTDIR/bootstrap_settings.yaml" \
  bootstrap --cache-wheel-server-url=$WHEEL_SERVER_URL 'stevedore==5.2.0'

if ! grep -q "stevedore-5.2.0: found built wheel on cache server" "$LOGFILE"; then
  echo "FAIL: Did not find log message found built wheel on cache server in $LOGFILE" 1>&2
  pass=false
fi

$pass

# bootstrap stevedore again with 1 change log. Should not result in a build
# because the file exists in the cache server directory.

find "$OUTDIR/wheels-repo"

LOGFILE="$OUTDIR/bootstrap3.log"
fromager \
  --log-file="$LOGFILE" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-file="$SCRIPTDIR/bootstrap_settings.yaml" \
  bootstrap --cache-wheel-server-url=$WHEEL_SERVER_URL 'stevedore==5.2.0'

if ! grep -q "stevedore-5.2.0: found existing wheel " "$LOGFILE"; then
  echo "FAIL: Did not find log message found existing wheel in $LOGFILE" 1>&2
  pass=false
fi

$pass

# bootstrap stevedore with 2 changelog. should result in a build instead of being skipped
LOGFILE="$OUTDIR/bootstrap4.log"
fromager \
  --log-file="$LOGFILE" \
  --error-log-file="$OUTDIR/fromager-errors.log" \
  --sdists-repo="$OUTDIR/sdists-repo" \
  --wheels-repo="$OUTDIR/wheels-repo" \
  --work-dir="$OUTDIR/work-dir" \
  --settings-dir="$SCRIPTDIR/changelog_settings-2" \
  bootstrap --cache-wheel-server-url=$WHEEL_SERVER_URL 'stevedore==5.2.0'

EXPECTED_FILES="
$OUTDIR/wheels-repo/downloads/stevedore-5.2.0-1*.whl
$OUTDIR/wheels-repo/downloads/stevedore-5.2.0-2*.whl
"

pass=true
for pattern in $EXPECTED_FILES; do
  if [ ! -f "${pattern}" ]; then
    echo "Did not find $pattern" 1>&2
    pass=false
  fi
done

if ! grep -q "added extra metadata and build tag" "$LOGFILE"; then
  echo "Did not find message indicating builds would be skipped in $LOGFILE" 1>&2
  pass=false
fi

$pass

# Explicit numbers override both changelogs and rebuild in a reused repository.
mkdir -p "$OUTDIR/explicit-build-settings"
cat > "$OUTDIR/explicit-global-settings.yaml" <<EOF
changelog:
  cpu:
    - Imported variant change
EOF
for counter in 0 1; do
  cat > "$OUTDIR/explicit-build-settings/stevedore.yaml" <<EOF
build_number:
  "5.2.0": $counter
changelog:
  "5.2.0":
    - First imported change
    - Second imported change
EOF

  LOGFILE="$OUTDIR/explicit-build-$counter.log"
  fromager \
    --log-file="$LOGFILE" \
    --error-log-file="$OUTDIR/fromager-errors.log" \
    --sdists-repo="$OUTDIR/sdists-repo" \
    --wheels-repo="$OUTDIR/explicit-wheels-repo" \
    --work-dir="$OUTDIR/explicit-work-dir" \
    --settings-file="$OUTDIR/explicit-global-settings.yaml" \
    --settings-dir="$OUTDIR/explicit-build-settings" \
    bootstrap 'stevedore==5.2.0'

  grep -q "added extra metadata and build tag" "$LOGFILE"
  python - "$OUTDIR/explicit-wheels-repo/downloads" "$counter" <<'PY'
import email.parser
import pathlib
import sys
import zipfile

from packaging.utils import parse_wheel_filename

directory = pathlib.Path(sys.argv[1])
counter = int(sys.argv[2])
wheel = directory / f"stevedore-5.2.0-{counter}-py3-none-any.whl"
assert wheel.is_file(), wheel
assert parse_wheel_filename(wheel.name)[2] == (counter, "")
with zipfile.ZipFile(wheel) as archive:
    metadata_path = "stevedore-5.2.0.dist-info/WHEEL"
    metadata = email.parser.Parser().parsestr(archive.read(metadata_path).decode())
    assert metadata["Build"] == str(counter), metadata
    assert metadata.get_all("Tag") == ["py3-none-any"], metadata
print(f"Verified {wheel.name}: Build: {counter}")
PY
done
test -f "$OUTDIR/explicit-wheels-repo/downloads/stevedore-5.2.0-0-py3-none-any.whl"
test -f "$OUTDIR/explicit-wheels-repo/downloads/stevedore-5.2.0-1-py3-none-any.whl"
