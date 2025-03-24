"""Based on https://src.fedoraproject.org/rpms/python-cryptography/blob/rawhide/f/vendor_rust.py"""

import os
import pathlib
import stat
import tarfile

VCS_DIRS = {".bzr", ".git", ".hg", ".svn"}


def _tar_reset(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
    """Reset user, group, mtime, and mode to create reproducible tar"""
    tarinfo.uid = 0
    tarinfo.gid = 0
    tarinfo.uname = "root"
    tarinfo.gname = "root"
    tarinfo.mtime = 0
    if tarinfo.type == tarfile.DIRTYPE or stat.S_IMODE(tarinfo.mode) & stat.S_IXUSR:
        tarinfo.mode = 0o755
    else:
        tarinfo.mode = 0o644
    if tarinfo.pax_headers:
        raise ValueError(tarinfo.name, tarinfo.pax_headers)
    return tarinfo


def tar_reproducible(
    tar: tarfile.TarFile,
    basedir: pathlib.Path,
    prefix: pathlib.Path | None = None,
    *,
    exclude_vcs: bool = False,
) -> None:
    """Create reproducible tar file

    Add content from basedir to already opened tar. If prefix is provided, use
    it to set relative paths for the content being added.

    If ``exclude_vcs`` is True, then Bazaar, git, Mercurial, and subversion
    directories and files are excluded.
    """
    content = [str(basedir)]  # convert from pathlib.Path, if that's what we have
    for root, dirs, files in os.walk(basedir):
        if exclude_vcs:
            # modify lists in-place, so os.walk does not descent into the
            # excluded entries. git submodules have a `.git` file.
            dirs[:] = [directory for directory in dirs if directory not in VCS_DIRS]
            files[:] = [filename for filename in files if filename not in VCS_DIRS]
        for directory in dirs:
            content.append(os.path.join(root, directory))
        for filename in files:
            content.append(os.path.join(root, filename))
    content.sort()

    for fn in content:
        # Ensure that the paths in the tarfile are rooted at the prefix
        # directory, if we have one.
        arcname = fn if prefix is None else os.path.relpath(fn, prefix)
        tar.add(fn, filter=_tar_reset, recursive=False, arcname=arcname)
