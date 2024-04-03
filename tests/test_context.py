import pytest
from mirror_builder import context


@pytest.fixture
def tmp_context(tmp_path):
    return context.WorkContext(
        tmp_path / 'sdists-repo',
        tmp_path / 'wheels-repo',
        tmp_path / 'work-dir',
        0,
    )


def test_seen(tmp_context):
    distid = 'testdist-1.2'
    assert not tmp_context.has_been_seen(distid)
    tmp_context.mark_as_seen(distid)
    assert tmp_context.has_been_seen(distid)
