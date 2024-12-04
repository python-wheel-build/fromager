import os

from fromager import context


def test_pip_constraints_args(tmp_path):
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text("\n")  # the file has to exist
    ctx = context.WorkContext(
        active_settings=None,
        constraints_file=str(constraints_file),
        patches_dir=tmp_path / "overrides/patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
    )
    ctx.setup()
    assert ["--constraint", os.fspath(constraints_file)] == ctx.pip_constraint_args

    ctx = context.WorkContext(
        active_settings=None,
        constraints_file=None,
        patches_dir=tmp_path / "overrides/patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
    )
    ctx.setup()
    assert [] == ctx.pip_constraint_args
