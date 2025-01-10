#!/usr/bin/env -S unshare --uts --net --map-root-user /bin/bash
#
# Run command with network isolation (CLONE_NEWNET) and set up loopback
# interface in the new network namespace. This is somewhat similar to
# Bubblewrap `bwrap --unshare-net --dev-bind / /`, but works in an
# unprivilged container. The user is root inside the new namespace and mapped
# to the euid/egid if the parent namespace.
#
# Unshare UTS namespace, so we can set the hostname to "localhost", so
# lookup of "localhost" does not fail.
#
# Ubuntu 24.04: needs `sysctl kernel.apparmor_restrict_unprivileged_userns=0`
# to address `unshare: write failed /proc/self/uid_map: Operation not permitted`.
#

set -e
set -o pipefail

if [ "$#" -eq 0 ]; then
   echo "$0 command" >&2
   exit 2
fi

# bring loopback up
ip link set lo up

# set hostname to "localhost"
if command -v hostname 2>&1 >/dev/null; then
   hostname localhost
fi

# replace with command
exec "$@"
