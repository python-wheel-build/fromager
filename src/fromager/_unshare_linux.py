"""Network isolation with unshare, similar to bubblewrap

- ``unshare -rn`` does not configure a loopback device, which breaks some
  software like OpenMPI's OPAL / mpicc 4.x.
- bubblewrap / ``bwrap`` does not work in unprivilged, rootless containers
  out of the box. It needs additional tweaks and permissions.

The main function performs the same low-level syscalls as ``unshare -rn`` and
creates a loopback device inside the namespace.
"""

import os
import random
import socket
import struct
import sys
import typing

_unshare: typing.Callable[[int], None]

# struct nlmsghdr {
#     __u32 nlmsg_len;
#     __u16 nlmsg_type;
#     __u16 nlmsg_flags;
#     __u32 nlmsg_seq;
#     __u32 nlmsg_pid;
# };
NLMSGHDR = struct.Struct("IHHII")

# struct nlmsgerr {
#     int error;
#     struct nlmsghdr msg;
#     ...
# };
NLMSGERR = struct.Struct("i" + NLMSGHDR.format)

SOL_NETLINK = 270
NETLINK_EXT_ACK = 11
NETLINK_GET_STRICT_CHK = 12

RTM_NEWLINK = 16
NLMSG_ERROR = 2
NLMSG_DONE = 3
NLM_F_REQUEST = 1
NLM_F_ACK = 4

# struct ifinfomsg {
#     unsigned char ifi_family;
#     unsigned char __ifi_pad;
#     unsigned short ifi_type;
#     int ifi_index;
#     unsigned ifi_flags;
#     unsigned ifi_change;
# };
IFINFOMSG = struct.Struct("BxHiII")
IFF_UP = 1


def _ip_link_set_lo_up() -> None:
    """Perform 'ip link set lo up' with netlink

    Use netlink to bring up the loopback device.
    """
    ifi_index = socket.if_nametoindex("lo")
    # random sequence number
    seq = random.randint(1, (1 << 31) - 1)
    pid = os.getpid()

    addr = (0, 0)  # nl_pid, nl_groups
    with socket.socket(
        socket.AF_NETLINK, socket.SOCK_RAW | socket.SOCK_CLOEXEC, socket.NETLINK_ROUTE
    ) as sock:
        # configure netlink socket, some options are not available with
        # older Kernels.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16384)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16384)
        try:
            sock.setsockopt(SOL_NETLINK, NETLINK_EXT_ACK, 1)
        except OSError:
            # Linux 4.20
            pass

        sock.bind(addr)

        try:
            sock.setsockopt(SOL_NETLINK, NETLINK_GET_STRICT_CHK, 1)
        except OSError:
            # Linux 4.12
            pass

        # netlink route new link request
        hdr = NLMSGHDR.pack(
            NLMSGHDR.size + IFINFOMSG.size,  # nlmsg_len
            RTM_NEWLINK,  # nlmsg_type
            NLM_F_REQUEST | NLM_F_ACK,  # nlmsg_flags
            seq,  # nlmsg_seq
            pid,  # nlmsg_pid
        )
        # request interface up of interface
        msg = IFINFOMSG.pack(
            socket.AF_UNSPEC,  # ifi_family
            0,  # ifi_type
            ifi_index,  # ifi_index
            IFF_UP,  # ifi_flags
            IFF_UP,  # ifi_change
        )
        sock.sendmsg((hdr + msg,), (), 0, addr)

        # verify operation
        buf, _, _, _ = sock.recvmsg(1024)
        hdr = buf[0 : NLMSGHDR.size]
        msg = buf[NLMSGHDR.size : NLMSGHDR.size + NLMSGERR.size]
        nlmsg_len, nlmsg_type, nlmsg_flags, nlmsg_seq, nlmsg_pid = NLMSGHDR.unpack(hdr)
        # sanity check
        assert nlmsg_seq == seq
        assert nlmsg_pid == pid
        if nlmsg_type == NLMSG_ERROR:
            # negative errno
            errno = abs(NLMSGERR.unpack(msg)[0])
            if errno != 0:
                raise OSError(errno, os.strerror(errno))


if sys.version_info >= (3, 12):
    # Python 3.12
    _unshare = os.unshare
    _CLONE_NEWNET = os.CLONE_NEWNET
    _CLONE_NEWUSER = os.CLONE_NEWUSER
else:
    import ctypes

    # fallback for Python 3.11
    # <linux/sched.h>
    _CLONE_NEWUSER = 0x10000000
    _CLONE_NEWNET = 0x40000000

    # glibc (2.18 from 2013) and musllibc
    _libc = ctypes.cdll.LoadLibrary("libc.so.6")
    _libc_unshare = _libc.unshare
    _libc_unshare.argtypes = (ctypes.c_int,)
    _libc_unshare.restype = ctypes.c_int

    def _unshare(flags: int) -> None:
        ctypes.set_errno(0)
        res = _libc_unshare(flags)
        if res != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno))


def _write(path: str, value: str) -> None:
    """Dirct write to file descriptor

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
        raise ValueError("Unshare not supported")
    # get effective uid/gid before unsharing
    euid = os.geteuid()
    egid = os.getegid()

    # unshare network in a new user namespace
    _unshare(_CLONE_NEWNET | _CLONE_NEWUSER)

    # limit uid/gid mappings
    # map root inside namespace to user's effectice uid/gid, limit mapping
    # size to one uid/gid, and block set groups.
    _write("/proc/self/uid_map", f"0 {euid} 1")
    _write("/proc/self/setgroups", "deny")
    _write("/proc/self/gid_map", f"0 {egid} 1")

    # bring loopback device up
    # equivalent to `ip link set lo up`
    _ip_link_set_lo_up()


def exec_unshare(*args: str) -> typing.NoReturn:
    if not args:
        sys.exit("No argument")
    unshare_network()
    os.execvp(args[0], args)


if __name__ == "__main__":
    exec_unshare(*sys.argv[1:])
