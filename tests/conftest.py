import pytest

from mirror_builder import context


@pytest.fixture
def tmp_context(tmp_path):
    ctx = context.WorkContext(
        tmp_path / 'sdists-repo',
        tmp_path / 'wheels-repo',
        tmp_path / 'work-dir',
        0,
    )
    ctx.setup()
    return ctx
