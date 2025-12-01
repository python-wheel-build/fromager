import pathlib
from unittest.mock import Mock, patch

import pytest

from fromager.gitutils import git_clone_fast


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
            "HEAD",
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


@pytest.mark.skip(reason="needs network access")
def test_git_clone_real(tmp_path: pathlib.Path) -> None:
    repo_url = "https://github.com/python-wheel-build/fromager.git"
    git_clone_fast(output_dir=tmp_path, repo_url=repo_url, ref="refs/tags/0.73.0")
    assert tmp_path.joinpath("src", "fromager").is_dir()
