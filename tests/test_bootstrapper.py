import json

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from fromager import bootstrapper
from fromager.context import WorkContext
from fromager.dependency_graph import DependencyGraph
from fromager.requirements_file import RequirementType

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


def test_resolve_from_graph_no_changes(tmp_context: WorkContext):
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


def test_resolve_from_graph_install_dep_upgrade(tmp_context: WorkContext):
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


def test_resolve_from_graph_install_dep_downgrade(tmp_context: WorkContext):
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


def test_resolve_from_graph_toplevel_dep(tmp_context: WorkContext):
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


def test_seen(tmp_context):
    bt = bootstrapper.Bootstrapper(tmp_context)
    req = Requirement("testdist")
    version = "1.2"
    assert not bt._has_been_seen(req, version)
    bt._mark_as_seen(req, version)
    assert bt._has_been_seen(req, version)


def test_seen_extras(tmp_context):
    req1 = Requirement("testdist")
    req2 = Requirement("testdist[extra]")
    version = "1.2"
    bt = bootstrapper.Bootstrapper(tmp_context)
    assert not bt._has_been_seen(req1, version)
    bt._mark_as_seen(req1, version)
    assert bt._has_been_seen(req1, version)
    assert not bt._has_been_seen(req2, version)
    bt._mark_as_seen(req2, version)
    assert bt._has_been_seen(req1, version)
    assert bt._has_been_seen(req2, version)


def test_seen_name_canonicalization(tmp_context):
    req = Requirement("flit_core")
    version = "1.2"
    bt = bootstrapper.Bootstrapper(tmp_context)
    assert not bt._has_been_seen(req, version)
    bt._mark_as_seen(req, version)
    assert bt._has_been_seen(req, version)


def test_build_order(tmp_context):
    bt = bootstrapper.Bootstrapper(tmp_context)
    bt._add_to_build_order(
        req=Requirement("buildme>1.0"),
        version="6.0",
        source_url="url",
        source_url_type="sdist",
    )
    bt._add_to_build_order(
        req=Requirement("testdist>1.0"),
        version="1.2",
        source_url="url",
        source_url_type="sdist",
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


def test_build_order_repeats(tmp_context):
    bt = bootstrapper.Bootstrapper(tmp_context)
    bt._add_to_build_order(
        Requirement("buildme>1.0"),
        "6.0",
        "url",
        "sdist",
    )
    bt._add_to_build_order(
        Requirement("buildme>1.0"),
        "6.0",
        "url",
        "sdist",
    )
    bt._add_to_build_order(
        Requirement("buildme[extra]>1.0"),
        "6.0",
        "url",
        "sdist",
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


def test_build_order_name_canonicalization(tmp_context):
    bt = bootstrapper.Bootstrapper(tmp_context)
    bt._add_to_build_order(
        Requirement("flit-core>1.0"),
        "3.9.0",
        "url",
        "sdist",
    )
    bt._add_to_build_order(
        Requirement("flit_core>1.0"),
        "3.9.0",
        "url",
        "sdist",
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


def test_explain(tmp_context: WorkContext):
    bt = bootstrapper.Bootstrapper(tmp_context, None, old_graph)
    bt.why = [(RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0"))]
    assert bt._explain == f"{RequirementType.TOP_LEVEL} dependency foo (1.0.0)"

    bt.why = []
    assert bt._explain == ""

    bt.why = [
        (RequirementType.TOP_LEVEL, Requirement("foo"), Version("1.0.0")),
        (RequirementType.BUILD, Requirement("bar==4.0.0"), Version("4.0.0")),
    ]
    assert (
        bt._explain
        == f"{RequirementType.BUILD} dependency bar==4.0.0 (4.0.0) for {RequirementType.TOP_LEVEL} dependency foo (1.0.0)"
    )
