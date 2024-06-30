import pytest

from fromager import context, settings


@pytest.fixture
def tmp_context(tmp_path):
    ctx = context.WorkContext(
        active_settings=settings.Settings({}),
        patches_dir="overrides/patches",
        envs_dir="overrides/envs",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        wheel_server_url="",
    )
    ctx.setup()
    return ctx
