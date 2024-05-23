import pytest

from mirror_builder import context


@pytest.fixture
def tmp_context(tmp_path):
    ctx = context.WorkContext(
        patches_dir='overrides/patches',
        sdists_repo=tmp_path / 'sdists-repo',
        wheels_repo=tmp_path / 'wheels-repo',
        work_dir=tmp_path / 'work-dir',
        wheel_server_url='',
    )
    ctx.setup()
    return ctx
