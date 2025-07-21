"""Based on https://src.fedoraproject.org/rpms/python-cryptography/blob/rawhide/f/vendor_rust.py"""

import os
import pathlib
import stat
import tarfile
import typing

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


def _tar_content(
    *, basedir: pathlib.Path, exclude_vcs: bool = False
) -> typing.Iterable[str]:
    content: list[str] = [str(basedir)]  # include root
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
    return content


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
    content = _tar_content(basedir=basedir, exclude_vcs=exclude_vcs)
    for fn in content:
        # Ensure that the paths in the tarfile are rooted at the prefix
        # directory, if we have one.
        arcname = fn if prefix is None else os.path.relpath(fn, prefix)
        tar.add(fn, filter=_tar_reset, recursive=False, arcname=arcname)


def tar_reproducible_with_prefix(
    tar: tarfile.TarFile,
    basedir: pathlib.Path,
    prefix: str,
    *,
    exclude_vcs: bool = False,
) -> None:
    """Create reproducible tar file with a prefix

    Add content from basedir to already opened tar. All archive names are
    relative to ``basedir`` and with ``prefix` prepended. The ``prefix``
    must be relative and can be ``.``. This is equivalent to
    ``tar -czf $tarfile -C $basedir --transform 's,^,${prefix}/' .`` or
    ``git archive --prefix ${prefix}/``.

    If ``exclude_vcs`` is True, then Bazaar, git, Mercurial, and subversion
    directories and files are excluded.
    """
    if os.sep in prefix:
        raise ValueError("prefix {prefix} cannot contain {os.sep}")
    content = _tar_content(basedir=basedir, exclude_vcs=exclude_vcs)
    for fn in content:
        # archive names are relative to basedir
        # prefix is prepended and path is normalized
        arcname = os.path.normpath(os.path.join(prefix, os.path.relpath(fn, basedir)))
        tar.add(fn, filter=_tar_reset, recursive=False, arcname=arcname)
