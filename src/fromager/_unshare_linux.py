"""Network isolation with unshare, similar to bubblewrap

- ``unshare -rn`` does not configure a loopback device, which breaks some
  software like OpenMPI's OPAL / mpicc 4.x.
- bubblewrap / ``bwrap`` does not work in unprivilged, rootless containers
  out of the box. It needs additional tweaks and permissions.

The main function performs the same low-level syscalls as ``unshare -rn`` and
creates a loopback device inside the namespace.

unshare(CLONE_NEWUSER|CLONE_NEWNET)     = 0
openat(AT_FDCWD, "/proc/self/uid_map", O_WRONLY) = 3
write(3, "0 1000 1", 8)                 = 8
close(3)                                = 0
openat(AT_FDCWD, "/proc/self/setgroups", O_WRONLY) = 3
write(3, "deny", 4)                     = 4
close(3)                                = 0
openat(AT_FDCWD, "/proc/self/gid_map", O_WRONLY) = 3
write(3, "0 1000 1", 8)                 = 8
close(3)                                = 0
"""

import ctypes
import os
import subprocess
import typing

_unshare: typing.Callable[[int], None] | typing.Callable[[int], int] | None

# <linux/sched.h>
_CLONE_NEWUSER = getattr(os, "CLONE_NEWUSER", 0x10000000)
_CLONE_NEWNET = getattr(os, "CLONE_NEWNET", 0x40000000)

if hasattr(os, "unshare"):
    # Python 3.12
    _unshare = os.unshare
else:
    _LIBC: ctypes.CDLL | None
    try:
        _LIBC = ctypes.cdll.LoadLibrary("libc.so.6")
    except OSError:
        _LIBC = None

    def _errcheck(result, func, arguments):
        if result != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno))

    _unshare = getattr(_LIBC, "unshare", None)
    if _unshare is not None:
        _unshare.argtypes = (ctypes.c_int,)
        _unshare.restype = ctypes.c_int
        _unshare.errcheck = _errcheck


def _write_lowlevel(path: str, value: str) -> None:
    """Low-level write

    open() performs additional syscalls that result in a permission error
    """
    fd = os.open(path, os.O_WRONLY)
    try:
        os.write(fd, value.encode("ascii"))
    finally:
        os.close(fd)


def unshare_network() -> None:
    """Unshare network and user namespace of current (!) process

    Emulate 'unshare -rn -- sh -c 'ip link set lo up; ...'. Designed to be
    used as pre-exec function.
    """
    if _unshare is None:
        raise ValueError("unshare is not supported")
    # get effective uid/gid before unsharing
    euid = os.geteuid()
    egid = os.getegid()

    # unshare network and user namespace
    _unshare(_CLONE_NEWNET | _CLONE_NEWUSER)

    # limit uid/gid mappings
    # map root inside namespace to user's effectice uid/gid, limit mapping
    # size to one uid/gid, and block set groups.
    _write_lowlevel("/proc/self/uid_map", f"0 {euid} 1")
    _write_lowlevel("/proc/self/setgroups", "deny")
    _write_lowlevel("/proc/self/gid_map", f"0 {egid} 1")

    # set up loopback device
    subprocess.check_call(["ip", "link", "set", "lo", "up"])
