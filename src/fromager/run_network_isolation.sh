#!/usr/bin/env -S unshare -rn /bin/bash
#
# Run command with network isolation (CLONE_NEWNET) and set up loopback
# interface in the new network namespace. This is somewhat similar to
# Bubblewrap `bwrap --unshare-net --dev-bind / /`, but works in an
# unprivilged container. The user is root inside the new namespace and mapped
# to the euid/egid if the parent namespace.
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

# replace with command
exec "$@"
