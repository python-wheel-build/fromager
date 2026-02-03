import os
import pathlib

from fromager import context


def test_pip_constraints_args(tmp_path: pathlib.Path) -> None:
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


def test_output_directory_creation(tmp_path: pathlib.Path) -> None:
    """Verify output directory creation"""

    # default behavior
    # output_dir is None with sdists, wheels and work set to defaults
    ctx = context.WorkContext(
        active_settings=None,
        constraints_file=None,
        patches_dir=tmp_path / "overrides/patches",
        output_dir=None,
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
    )
    ctx.setup()

    assert ctx.sdists_repo == (tmp_path / "sdists-repo").resolve()
    assert ctx.wheels_repo == (tmp_path / "wheels-repo").resolve()
    assert ctx.work_dir == (tmp_path / "work-dir").resolve()

    # set output_dir
    # should override defaults for sdists, wheels and work dirs
    output_dir = tmp_path / "test-output-dir"
    ctx = context.WorkContext(
        active_settings=None,
        constraints_file=None,
        patches_dir=tmp_path / "overrides/patches",
        output_dir=output_dir,
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
    )
    ctx.setup()

    # verify output_dir created
    assert ctx.sdists_repo == (output_dir / "sdists-repo").resolve()
    assert ctx.wheels_repo == (output_dir / "wheels-repo").resolve()
    assert ctx.work_dir == (output_dir / "work-dir").resolve()

    # verify default dirs are not used
    assert ctx.sdists_repo != (tmp_path / "sdists-repo").resolve()
    assert ctx.wheels_repo != (tmp_path / "wheels-repo").resolve()
    assert ctx.work_dir != (tmp_path / "work-dir").resolve()
