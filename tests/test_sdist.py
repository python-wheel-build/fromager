from packaging.requirements import Requirement

from fromager import sdist
from fromager.context import WorkContext
from fromager.requirements_file import RequirementType


def test_ignore_based_on_marker(tmp_context: WorkContext):
    version = sdist.handle_requirement(
        ctx=tmp_context,
        req=Requirement('foo; python_version<"3.9"'),
        req_type=RequirementType.TOP_LEVEL,
        why=[],
    )
    assert version == ""
