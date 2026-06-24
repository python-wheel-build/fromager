import pathlib
import shutil
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest
from packaging.version import Version

from fromager.gitutils import GIT_HEAD, git_clone_fast, parse_vcs_url

needs_git_command = pytest.mark.skipif(
    shutil.which("git") is None, reason="requires 'git' command"
)


def setuptools_scm_version(root_dir: pathlib.Path) -> Version:
    out = subprocess.check_output(
        [sys.executable, "-m", "setuptools_scm"],
        text=True,
        stderr=subprocess.STDOUT,
        cwd=str(root_dir),
    )
    # last line contains the version
    lastline = out.strip().splitlines()[-1]
    return Version(lastline)


@patch("fromager.external_commands.run")
def test_git_clone_fast(m_run: Mock, tmp_path: pathlib.Path) -> None:
    repo_url = "https://git.test/project.git"
    git_clone_fast(output_dir=tmp_path, repo_url=repo_url)

    assert m_run.call_count == 2
    m_run.assert_any_call(
        [
            "git",
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            repo_url,
            str(tmp_path),
        ],
        network_isolation=False,
    )
    m_run.assert_any_call(
        [
            "git",
            "checkout",
            GIT_HEAD,
        ],
        network_isolation=False,
        cwd=str(tmp_path),
    )


@patch("fromager.external_commands.run")
def test_git_clone_fast_submodules(m_run: Mock, tmp_path: pathlib.Path) -> None:
    repo_url = "https://git.test/project.git"
    tmp_path.joinpath(".gitmodules").touch()
    git_clone_fast(output_dir=tmp_path, repo_url=repo_url)

    assert m_run.call_count == 3
    m_run.assert_called_with(
        [
            "git",
            "submodule",
            "update",
            "--init",
            "--recursive",
            "--filter=blob:none",
            "--jobs=4",
        ],
        cwd=str(tmp_path),
        network_isolation=False,
    )


def test_parse_vcs_url() -> None:
    assert parse_vcs_url("git+https://git.test/org/project.git@v1.0") == (
        "https://git.test/org/project.git",
        "v1.0",
    )
    # '@' in netloc must not be confused with the ref '@'
    assert parse_vcs_url("git+ssh://git@git.test/org/project.git@abc123") == (
        "ssh://git@git.test/org/project.git",
        "abc123",
    )
    # git+file scheme
    assert parse_vcs_url("git+file:///home/user/repo.git@main") == (
        "file:///home/user/repo.git",
        "main",
    )
    # require_ref=False returns GIT_HEAD when no ref is present
    assert parse_vcs_url("git+https://git.test/org/project.git", require_ref=False) == (
        "https://git.test/org/project.git",
        GIT_HEAD,
    )


def test_parse_vcs_url_errors() -> None:
    with pytest.raises(ValueError, match="missing a mandatory ref"):
        parse_vcs_url("git+https://git.test/org/project.git")
    with pytest.raises(ValueError, match="empty ref"):
        parse_vcs_url("git+https://git.test/org/project.git@")
    with pytest.raises(ValueError, match="empty ref"):
        parse_vcs_url("git+https://git.test/org/project.git@", require_ref=False)
    with pytest.raises(ValueError, match="unsupported VCS URL scheme"):
        parse_vcs_url("git+http://git.test/org/project.git@v1.0")


@pytest.mark.network
@needs_git_command
def test_git_clone_real(tmp_path: pathlib.Path) -> None:
    repo_url = "https://github.com/python-wheel-build/fromager.git"
    git_clone_fast(output_dir=tmp_path, repo_url=repo_url, ref="refs/tags/0.73.0")
    assert tmp_path.joinpath("src", "fromager").is_dir()

    # detect version from .git
    assert setuptools_scm_version(tmp_path) == Version("0.73.0")
