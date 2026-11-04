#!/bin/bash
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

# Test that bootstrap, build, and build-sequence use a configured
# `source:` resolver end-to-end: resolve, download, prepare, and build.
#
# The git profile resolves stevedore tags on GitHub and builds from a
# git checkout. The archive profile resolves on PyPI and downloads a
# tarball from a URL template.

SCRIPTDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
source "$SCRIPTDIR/common.sh"

# What are we building?
DIST="stevedore"
VERSION="5.2.0"
WHEEL="wheels-repo/downloads/${DIST}-${VERSION}-0-py3-none-any.whl"
BUILT_SDIST="sdists-repo/builds/${DIST}-${VERSION}.tar.gz"

GIT_SETTINGS="$SCRIPTDIR/source_settings_git"
ARCHIVE_SETTINGS="$SCRIPTDIR/source_settings_archive"

pass=true

remove_dist() {
  rm -rf "$OUTDIR/wheels-repo/downloads/${DIST}"-*
  rm -rf "$OUTDIR/wheels-repo/simple/${DIST}"
  rm -rf "$OUTDIR/sdists-repo/downloads/${DIST}"-*
  rm -rf "$OUTDIR/sdists-repo/builds/${DIST}"-*
  rm -rf "$OUTDIR/work-dir/${DIST}"-*
}

expect_file() {
  if [ ! -f "$OUTDIR/$1" ]; then
    echo "FAIL: Did not find $OUTDIR/$1" 1>&2
    pass=false
  fi
}

expect_no_source_download() {
  if [ -n "$(find "$OUTDIR/sdists-repo/downloads/" -name "${DIST}-*")" ]; then
    echo "FAIL: git profile downloaded a source archive for ${DIST}" 1>&2
    pass=false
  fi
}

expect_ignored_index_url() {
  if ! grep -q "ignoring index URL unreachable_url" "$1"; then
    echo "FAIL: configured resolver did not ignore the caller URL in $1" 1>&2
    pass=false
  fi
}

# 1. Bootstrap with the git profile. This also builds the build
# dependencies that the later steps install from the local wheel server.
fromager \
    $NETWORK_ISOLATION \
    --log-file="$OUTDIR/bootstrap.log" \
    --sdists-repo="$OUTDIR/sdists-repo" \
    --wheels-repo="$OUTDIR/wheels-repo" \
    --work-dir="$OUTDIR/work-dir" \
    --settings-dir="$GIT_SETTINGS" \
    bootstrap "${DIST}==${VERSION}"

expect_file "$WHEEL"

# The build order records the configured provider and the git URL.
if ! python3 - "$OUTDIR/work-dir/build-order.json" "$DIST" <<'EOF'
import json
import sys

path, dist = sys.argv[1:]
with open(path) as f:
    entries = [e for e in json.load(f) if e["dist"] == dist]
assert len(entries) == 1, entries
entry = entries[0]
assert entry["source_provider"] == "github-tag-git", entry
assert entry["source_url_type"] == "override", entry
assert entry["source_url"].startswith(
    "git+https://github.com/python-wheel-build/stevedore-test-repo@"
), entry
EOF
then
  echo "FAIL: build order does not record the configured git source" 1>&2
  pass=false
fi

# 2. Build with the git profile. The caller URL is unreachable, so the
# configured resolver must use its own index.
remove_dist
fromager \
    --log-file="$OUTDIR/build-git.log" \
    --sdists-repo="$OUTDIR/sdists-repo" \
    --wheels-repo="$OUTDIR/wheels-repo" \
    --work-dir="$OUTDIR/work-dir" \
    --settings-dir="$GIT_SETTINGS" \
    build "${DIST}" "${VERSION}" "unreachable_url"

expect_file "$WHEEL"
expect_file "$BUILT_SDIST"
expect_no_source_download
expect_ignored_index_url "$OUTDIR/build-git.log"

# 3. Replay the saved git URL with build-sequence. Only the stevedore
# entry is kept, so the build dependencies are not rebuilt.
remove_dist
python3 - "$OUTDIR/work-dir/build-order.json" "$OUTDIR/source-build-order.json" "$DIST" <<'EOF'
import json
import sys

src, dest, dist = sys.argv[1:]
with open(src) as f:
    entries = [e for e in json.load(f) if e["dist"] == dist]
with open(dest, "w") as f:
    json.dump(entries, f)
EOF
fromager \
    --log-file="$OUTDIR/build-sequence-git.log" \
    --sdists-repo="$OUTDIR/sdists-repo" \
    --wheels-repo="$OUTDIR/wheels-repo" \
    --work-dir="$OUTDIR/work-dir" \
    --settings-dir="$GIT_SETTINGS" \
    build-sequence "$OUTDIR/source-build-order.json"

expect_file "$WHEEL"
expect_file "$BUILT_SDIST"
expect_no_source_download

# 4. Build with the archive profile. The tarball gets the standard name.
remove_dist
fromager \
    --log-file="$OUTDIR/build-archive.log" \
    --sdists-repo="$OUTDIR/sdists-repo" \
    --wheels-repo="$OUTDIR/wheels-repo" \
    --work-dir="$OUTDIR/work-dir" \
    --settings-dir="$ARCHIVE_SETTINGS" \
    build "${DIST}" "${VERSION}" "unreachable_url"

expect_file "$WHEEL"
expect_file "$BUILT_SDIST"
expect_file "sdists-repo/downloads/${DIST}-${VERSION}.tar.gz"
expect_ignored_index_url "$OUTDIR/build-archive.log"

$pass
