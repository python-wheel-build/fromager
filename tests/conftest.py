from unittest.mock import patch

import pytest

from fromager import constraints, context, settings


@pytest.fixture
def tmp_context(tmp_path):
    ctx = context.WorkContext(
        active_settings=settings.Settings({}),
        pkg_constraints=constraints.Constraints({}),
        patches_dir="overrides/patches",
        envs_dir="overrides/envs",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        wheel_server_url="",
    )
    with (
        patch.object(ctx, "cpu_count", return_value=8),
        patch.object(ctx, "available_memory_gib", return_value=15.1),
    ):
        ctx.setup()
        yield ctx
