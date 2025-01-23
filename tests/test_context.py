import os

from fromager import context


def test_pip_constraints_args(tmp_path):
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text("\n")  # the file has to exist
    ctx = context.WorkContext(
        active_settings=None,
        constraints_files=[constraints_file],
        patches_dir=tmp_path / "overrides/patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
    )
    ctx.setup()
    assert ctx.pip_constraint_args == [
        "--constraint",
        os.fspath(ctx.work_dir / "combined-constraints.txt"),
    ]

    ctx = context.WorkContext(
        active_settings=None,
        constraints_files=[],
        patches_dir=tmp_path / "overrides/patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
    )
    ctx.setup()
    assert [] == ctx.pip_constraint_args
