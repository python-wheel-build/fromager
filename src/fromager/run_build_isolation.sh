#!/bin/bash
#
# Run command with build isolation for untrusted build backends.
#
# Uses an ephemeral Unix user for file-level isolation:
# - Cannot read credential files like .netrc (owned by root, mode 600)
# - Gets its own /tmp entries (sticky bit prevents cross-user access)
#
# Combined with Linux namespaces for:
# - Network isolation (no routing in new net namespace)
# - PID isolation (build cannot see other processes)
# - IPC isolation (isolated shared memory, semaphores, message queues)
# - UTS isolation (separate hostname)
#
# The ephemeral user is created before entering the namespace, then
# unshare runs as that user with --map-root-user so it has enough
# privilege to bring up loopback and set hostname inside the namespace.
#
# This works in unprivileged containers (Podman/Docker) without --privileged
# or --cap-add SYS_ADMIN.
#
# Ubuntu 24.04: needs `sysctl kernel.apparmor_restrict_unprivileged_userns=0`
#

set -e
set -o pipefail

if [ "$#" -eq 0 ]; then
   echo "Usage: $0 command [args...]" >&2
   exit 2
fi

# --- Ephemeral user creation (before namespace entry) ---

BUILD_USER="fmr_$(head -c4 /dev/urandom | od -An -tu4 | tr -d ' ')"
useradd -r -M -d /nonexistent -s /sbin/nologin "$BUILD_USER"
trap 'userdel "$BUILD_USER" 2>/dev/null || true' EXIT

# Make build dir writable by ephemeral user if set
if [ -n "${FROMAGER_BUILD_DIR:-}" ] && [ -d "$FROMAGER_BUILD_DIR" ]; then
   chmod -R o+rwX "$FROMAGER_BUILD_DIR" 2>/dev/null || true
fi

# --- Enter namespaces as ephemeral user ---
# setpriv drops to the ephemeral user, then unshare creates namespaces.
# --map-root-user maps the ephemeral user to UID 0 inside the namespace
# so it can run ip/hostname.

BUILD_UID=$(id -u "$BUILD_USER")
BUILD_GID=$(id -g "$BUILD_USER")

exec setpriv --reuid="$BUILD_UID" --regid="$BUILD_GID" --clear-groups -- \
   unshare --uts --net --pid --ipc --fork --map-root-user -- \
   /bin/bash -c '
      # bring loopback up
      if command -v ip 2>&1 >/dev/null; then
         ip link set lo up
      fi
      # set hostname
      if command -v hostname 2>&1 >/dev/null; then
         hostname localhost
      fi
      exec "$@"
   ' -- "$@"
