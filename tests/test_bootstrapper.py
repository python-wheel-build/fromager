import json
import pathlib
from unittest.mock import Mock, patch

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import bootstrapper
from fromager.context import WorkContext
from fromager.dependency_graph import DependencyGraph
from fromager.requirements_file import RequirementType, SourceType

old_graph = DependencyGraph()

old_graph.add_dependency(
    parent_name=None,
    parent_version=None,
    req_type=RequirementType.TOP_LEVEL,
    req=Requirement("foo"),
    req_version=Version("1.0.0"),
)

old_graph.add_dependency(
    parent_name=canonicalize_name("foo"),
    parent_version=Version("1.0.0"),
    req_type=RequirementType.INSTALL,
    req=Requirement("pbr>=5"),
    req_version=Version("7"),
)

old_graph.add_dependency(
    parent_name=None,
    parent_version=None,
    req_type=RequirementType.TOP_LEVEL,
    req=Requirement("bar"),
    req_version=Version("1.0.0"),
)

old_graph.add_dependency(
    parent_name=canonicalize_name("bar"),
    parent_version=Version("1.0.0"),
    req_type=RequirementType.INSTALL,
    req=Requirement("pbr>=5,<7"),
    req_version=Version("6"),
)

old_graph.add_dependency(
    parent_name=None,
    parent_version=None,
    req_type=RequirementType.TOP_LEVEL,
    req=Requirement("blah"),
    req_version=Version("1.0.0"),
)

old_graph.add_dependency(
    parent_name=canonicalize_name("blah"),
    parent_version=Version("1.0.0"),
    req_type=RequirementType.INSTALL,
    req=Requirement("pbr==5"),
    req_version=Version("5"),
)


def test_resolve_from_graph_no_changes(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context, None, old_graph)
    bt.why = [(RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0"))]

    # resolving new dependency that doesn't exist in graph
    assert (
        bt._resolve_from_graph(
            req_type=RequirementType.INSTALL,
            req=Requirement("xyz"),
            pre_built=False,
        )
        is None
    )

    # resolving pbr dependency of foo
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5"),
        pre_built=False,
    ) == ("", Version("7"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("bar"), Version("1.0.0"))]
    # resolving pbr dependency of bar
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5,<7"),
        pre_built=False,
    ) == ("", Version("6"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("blah"), Version("1.0.0"))]
    # resolving pbr dependency of blah
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr==5"),
        pre_built=False,
    ) == ("", Version("5"))


def test_resolve_from_graph_install_dep_upgrade(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context, None, old_graph)

    # simulating new bootstrap with a toplevel requirement of pbr==8
    tmp_context.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("pbr==8"),
        req_version=Version("8"),
    )

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0"))]
    # resolving pbr dependency of foo
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5"),
        pre_built=False,
    ) == ("", Version("8"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("bar"), Version("1.0.0"))]
    # resolving pbr dependency of bar
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5,<7"),
        pre_built=False,
    ) == ("", Version("6"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("blah"), Version("1.0.0"))]
    # resolving pbr dependency of blah
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr==5"),
        pre_built=False,
    ) == ("", Version("5"))


def test_resolve_from_graph_install_dep_downgrade(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context, None, old_graph)

    # simulating new bootstrap with a toplevel requirement of pbr<=6
    tmp_context.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("pbr<=6"),
        req_version=Version("6"),
    )

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0"))]
    # resolving pbr dependency of foo
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5"),
        pre_built=False,
    ) == ("", Version("6"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("bar"), Version("1.0.0"))]
    # resolving pbr dependency of bar
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5,<7"),
        pre_built=False,
    ) == ("", Version("6"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("blah"), Version("1.0.0"))]
    # resolving pbr dependency of blah
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr==5"),
        pre_built=False,
    ) == ("", Version("5"))


def test_resolve_from_graph_toplevel_dep(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context, None, old_graph)

    # simulating new bootstrap with a toplevel requirement for foo
    tmp_context.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("foo==2"),
        req_version=Version("2"),
    )

    # simulating new bootstrap with a toplevel requirement of bar (no change)
    tmp_context.dependency_graph.add_dependency(
        parent_name=None,
        parent_version=None,
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("bar"),
        req_version=Version("1.0.0"),
    )

    bt.why = []
    # resolving foo
    assert bt._resolve_from_graph(
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("foo==2"),
        pre_built=False,
    ) == ("", Version("2"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("foo"), Version("2"))]
    # resolving pbr dependency of foo even if foo version changed
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5"),
        pre_built=False,
    ) == ("", Version("7"))

    bt.why = []
    # resolving bar
    assert bt._resolve_from_graph(
        req_type=RequirementType.TOP_LEVEL,
        req=Requirement("bar"),
        pre_built=False,
    ) == ("", Version("1.0.0"))

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("bar"), Version("1.0.0"))]
    # resolving pbr dependency of bar
    assert bt._resolve_from_graph(
        req_type=RequirementType.INSTALL,
        req=Requirement("pbr>=5,<7"),
        pre_built=False,
    ) == ("", Version("6"))


def test_seen(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context)
    req = Requirement("testdist")
    version = Version("1.2")
    assert not bt._has_been_seen(req, version)
    bt._mark_as_seen(req, version)
    assert bt._has_been_seen(req, version)


def test_seen_extras(tmp_context: WorkContext) -> None:
    req1 = Requirement("testdist")
    req2 = Requirement("testdist[extra]")
    version = Version("1.2")
    bt = bootstrapper.Bootstrapper(tmp_context)
    assert not bt._has_been_seen(req1, version)
    bt._mark_as_seen(req1, version)
    assert bt._has_been_seen(req1, version)
    assert not bt._has_been_seen(req2, version)
    bt._mark_as_seen(req2, version)
    assert bt._has_been_seen(req1, version)
    assert bt._has_been_seen(req2, version)


def test_seen_name_canonicalization(tmp_context: WorkContext) -> None:
    req = Requirement("flit_core")
    version = Version("1.2")
    bt = bootstrapper.Bootstrapper(tmp_context)
    assert not bt._has_been_seen(req, version)
    bt._mark_as_seen(req, version)
    assert bt._has_been_seen(req, version)


def test_seen_requirements_sdist(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context)
    req = Requirement("testdist")
    version = Version("1.2")
    assert not bt._has_been_seen(req, version, sdist_only=False)
    assert not bt._has_been_seen(req, version, sdist_only=True)
    # sdist only does not affect wheel status
    bt._mark_as_seen(req, version, sdist_only=True)
    assert bt._has_been_seen(req, version, sdist_only=True)
    assert not bt._has_been_seen(req, version, sdist_only=False)

    bt._mark_as_seen(req, version, sdist_only=False)
    assert bt._has_been_seen(req, version, sdist_only=True)
    assert bt._has_been_seen(req, version, sdist_only=False)

    req2 = Requirement("testwheel")
    assert not bt._has_been_seen(req2, version, sdist_only=False)
    assert not bt._has_been_seen(req2, version, sdist_only=True)
    # full seen affects both sdist and wheel status
    bt._mark_as_seen(req2, version, sdist_only=False)
    assert bt._has_been_seen(req2, version, sdist_only=True)
    assert bt._has_been_seen(req2, version, sdist_only=False)


def test_build_order(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context)
    bt._add_to_build_order(
        req=Requirement("buildme>1.0"),
        version=Version("6.0"),
        source_url="url",
        source_type=SourceType.SDIST,
    )
    bt._add_to_build_order(
        req=Requirement("testdist>1.0"),
        version=Version("1.2"),
        source_url="url",
        source_type=SourceType.SDIST,
    )
    contents_str = bt._build_order_filename.read_text()
    contents = json.loads(contents_str)
    expected = [
        {
            "req": "buildme>1.0",
            "dist": "buildme",
            "version": "6.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
        },
        {
            "req": "testdist>1.0",
            "dist": "testdist",
            "version": "1.2",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
        },
    ]
    assert expected == contents


def test_build_order_repeats(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context)
    bt._add_to_build_order(
        Requirement("buildme>1.0"),
        Version("6.0"),
        "url",
        SourceType.SDIST,
    )
    bt._add_to_build_order(
        Requirement("buildme>1.0"),
        Version("6.0"),
        "url",
        SourceType.SDIST,
    )
    bt._add_to_build_order(
        Requirement("buildme[extra]>1.0"),
        Version("6.0"),
        "url",
        SourceType.SDIST,
    )
    contents_str = bt._build_order_filename.read_text()
    contents = json.loads(contents_str)
    expected = [
        {
            "req": "buildme>1.0",
            "dist": "buildme",
            "version": "6.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
        },
    ]
    assert expected == contents


def test_build_order_name_canonicalization(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context)
    bt._add_to_build_order(
        Requirement("flit-core>1.0"),
        Version("3.9.0"),
        "url",
        SourceType.SDIST,
    )
    bt._add_to_build_order(
        Requirement("flit_core>1.0"),
        Version("3.9.0"),
        "url",
        SourceType.SDIST,
    )
    contents_str = bt._build_order_filename.read_text()
    contents = json.loads(contents_str)
    expected = [
        {
            "req": "flit-core>1.0",
            "dist": "flit-core",
            "version": "3.9.0",
            "prebuilt": False,
            "source_url": "url",
            "source_url_type": "sdist",
            "constraint": "",
        },
    ]
    assert expected == contents


def test_explain(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context, None, old_graph)
    bt.why = [(RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0"))]
    assert bt._explain == f"{RequirementType.TOP_LEVEL} dependency foo (1.0.0)"

    bt.why = []
    assert bt._explain == ""

    bt.why = [
        (RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0")),
        (RequirementType.BUILD_SYSTEM, Requirement("bar==4.0.0"), Version("4.0.0")),
    ]
    assert (
        bt._explain
        == f"{RequirementType.BUILD_SYSTEM} dependency bar==4.0.0 (4.0.0) for {RequirementType.TOP_LEVEL} dependency foo (1.0.0)"
    )


def test_is_build_requirement(tmp_context: WorkContext) -> None:
    bt = bootstrapper.Bootstrapper(tmp_context, None, old_graph)
    bt.why = []
    assert not bt._processing_build_requirement(RequirementType.TOP_LEVEL)
    assert bt._processing_build_requirement(RequirementType.BUILD_SYSTEM)
    assert bt._processing_build_requirement(RequirementType.BUILD_BACKEND)
    assert bt._processing_build_requirement(RequirementType.BUILD_SDIST)
    assert not bt._processing_build_requirement(RequirementType.INSTALL)

    bt.why = [(RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0"))]
    assert not bt._processing_build_requirement(RequirementType.INSTALL)
    assert bt._processing_build_requirement(RequirementType.BUILD_SYSTEM)
    assert bt._processing_build_requirement(RequirementType.BUILD_BACKEND)
    assert bt._processing_build_requirement(RequirementType.BUILD_SDIST)

    bt.why = [
        (RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0")),
        (RequirementType.BUILD_SYSTEM, Requirement("bar==4.0.0"), Version("4.0.0")),
    ]
    assert bt._processing_build_requirement(RequirementType.INSTALL)
    assert bt._processing_build_requirement(RequirementType.BUILD_SYSTEM)
    assert bt._processing_build_requirement(RequirementType.BUILD_BACKEND)
    assert bt._processing_build_requirement(RequirementType.BUILD_SDIST)


def test_find_cached_wheel_returns_tuple(tmp_context: WorkContext) -> None:
    """Verify _find_cached_wheel returns tuple of (Path|None, Path|None)."""
    bt = bootstrapper.Bootstrapper(tmp_context)

    # Call method (will return None, None since no wheels exist)
    result = bt._find_cached_wheel(
        req=Requirement("test-package"),
        resolved_version=Version("1.0.0"),
    )

    # Verify return type is tuple with 2 elements
    assert isinstance(result, tuple)
    assert len(result) == 2


@patch("fromager.dependencies.get_install_dependencies_of_wheel", return_value=set())
def test_get_install_dependencies_returns_list(
    mock_get_deps: Mock, tmp_context: WorkContext
) -> None:
    """Verify _get_install_dependencies returns list."""
    bt = bootstrapper.Bootstrapper(tmp_context)

    # Create fake wheel file and mock dependencies
    wheel_file = pathlib.Path("/fake/package-1.0.0-py3-none-any.whl")
    unpack_dir = tmp_context.work_dir

    result = bt._get_install_dependencies(
        req=Requirement("test-package"),
        resolved_version=Version("1.0.0"),
        wheel_filename=wheel_file,
        sdist_filename=None,
        sdist_root_dir=None,
        build_env=None,
        unpack_dir=unpack_dir,
    )

    # Verify return type is list
    assert isinstance(result, list)
    # Verify the mocked function was called
    mock_get_deps.assert_called_once()


def test_build_from_source_returns_dataclass(tmp_context: WorkContext) -> None:
    """Verify _build_from_source returns SourceBuildResult with correct values."""
    bt = bootstrapper.Bootstrapper(tmp_context)

    mock_sdist_root = tmp_context.work_dir / "package-1.0.0" / "package-1.0.0"
    mock_sdist_root.parent.mkdir(parents=True, exist_ok=True)
    mock_source_file = tmp_context.work_dir / "package-1.0.0.tar.gz"
    mock_wheel = tmp_context.work_dir / "package-1.0.0-py3-none-any.whl"
    expected_unpack_dir = mock_sdist_root.parent

    with (
        patch("fromager.sources.download_source", return_value=mock_source_file),
        patch("fromager.sources.prepare_source", return_value=mock_sdist_root),
        patch("fromager.sources.get_source_type", return_value=SourceType.SDIST),
        patch.object(bt, "_prepare_build_dependencies"),
        patch.object(bt, "_build_wheel", return_value=(mock_wheel, None)),
    ):
        result = bt._build_from_source(
            req=Requirement("test-package"),
            resolved_version=Version("1.0.0"),
            source_url="https://pypi.org/simple/test-package",
            build_sdist_only=False,
            cached_wheel_filename=None,
            unpacked_cached_wheel=None,
        )

        # Verify return type is SourceBuildResult
        assert isinstance(result, bootstrapper.SourceBuildResult)

        # Verify all expected fields have correct values
        assert result.wheel_filename == mock_wheel
        assert result.sdist_filename is None
        assert result.unpack_dir == expected_unpack_dir
        assert result.sdist_root_dir == mock_sdist_root
        assert result.build_env is not None
        assert result.source_type == SourceType.SDIST
