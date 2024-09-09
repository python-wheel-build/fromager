import json
import os

from packaging.requirements import Requirement

from fromager import context


def test_seen(tmp_context):
    req = Requirement("testdist")
    version = "1.2"
    assert not tmp_context.has_been_seen(req, version)
    tmp_context.mark_as_seen(req, version)
    assert tmp_context.has_been_seen(req, version)


def test_seen_extras(tmp_context):
    req1 = Requirement("testdist")
    req2 = Requirement("testdist[extra]")
    version = "1.2"
    assert not tmp_context.has_been_seen(req1, version)
    tmp_context.mark_as_seen(req1, version)
    assert tmp_context.has_been_seen(req1, version)
    assert not tmp_context.has_been_seen(req2, version)
    tmp_context.mark_as_seen(req2, version)
    assert tmp_context.has_been_seen(req1, version)
    assert tmp_context.has_been_seen(req2, version)


def test_seen_name_canonicalization(tmp_context):
    req = Requirement("flit_core")
    version = "1.2"
    assert not tmp_context.has_been_seen(req, version)
    tmp_context.mark_as_seen(req, version)
    assert tmp_context.has_been_seen(req, version)


def test_build_order(tmp_context):
    tmp_context.add_to_build_order(
        req=Requirement("buildme>1.0"),
        version="6.0",
        source_url="url",
        source_url_type="sdist",
    )
    tmp_context.add_to_build_order(
        req=Requirement("testdist>1.0"),
        version="1.2",
        source_url="url",
        source_url_type="sdist",
    )
    contents_str = tmp_context._build_order_filename.read_text()
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
    tmp_context.add_to_build_order(
        Requirement("buildme>1.0"),
        "6.0",
        "url",
        "sdist",
    )
    tmp_context.add_to_build_order(
        Requirement("buildme>1.0"),
        "6.0",
        "url",
        "sdist",
    )
    tmp_context.add_to_build_order(
        Requirement("buildme[extra]>1.0"),
        "6.0",
        "url",
        "sdist",
    )
    contents_str = tmp_context._build_order_filename.read_text()
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
    tmp_context.add_to_build_order(
        Requirement("flit-core>1.0"),
        "3.9.0",
        "url",
        "sdist",
    )
    tmp_context.add_to_build_order(
        Requirement("flit_core>1.0"),
        "3.9.0",
        "url",
        "sdist",
    )
    contents_str = tmp_context._build_order_filename.read_text()
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


def test_pip_constraints_args(tmp_path):
    constraints_file = tmp_path / "constraints.txt"
    constraints_file.write_text("\n")  # the file has to exist
    ctx = context.WorkContext(
        active_settings=None,
        constraints_file=constraints_file,
        patches_dir=tmp_path / "overrides/patches",
        sdists_repo=tmp_path / "sdists-repo",
        wheels_repo=tmp_path / "wheels-repo",
        work_dir=tmp_path / "work-dir",
        wheel_server_url="",
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
        wheel_server_url="",
    )
    ctx.setup()
    assert [] == ctx.pip_constraint_args
