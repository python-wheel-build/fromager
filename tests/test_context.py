import json

from packaging.requirements import Requirement


def test_seen(tmp_context):
    req = Requirement('testdist')
    version = '1.2'
    assert not tmp_context.has_been_seen(req, version)
    tmp_context.mark_as_seen(req, version)
    assert tmp_context.has_been_seen(req, version)


def test_seen_name_canonicalization(tmp_context):
    req = Requirement('flit_core')
    version = '1.2'
    assert not tmp_context.has_been_seen(req, version)
    tmp_context.mark_as_seen(req, version)
    assert tmp_context.has_been_seen(req, version)


def test_build_order(tmp_context):
    tmp_context.add_to_build_order(
        'build_backend', Requirement('buildme>1.0'), '6.0', ' -> buildme')
    tmp_context.add_to_build_order(
        'dependency', Requirement('testdist>1.0'), '1.2', ' -> testdist')
    contents_str = tmp_context._build_order_filename.read_text()
    contents = json.loads(contents_str)
    expected = [
        {
            'type': 'build_backend',
            'req': 'buildme>1.0',
            'dist': 'buildme',
            'version': '6.0',
            'why': ' -> buildme',
        },
        {
            'type': 'dependency',
            'req': 'testdist>1.0',
            'dist': 'testdist',
            'version': '1.2',
            'why': ' -> testdist',
        },
    ]
    assert expected == contents


def test_build_order_repeats(tmp_context):
    tmp_context.add_to_build_order(
        'build_backend', Requirement('buildme>1.0'), '6.0', ' -> buildme')
    tmp_context.add_to_build_order(
        'build_backend', Requirement('buildme>1.0'), '6.0', ' -> buildme')
    contents_str = tmp_context._build_order_filename.read_text()
    contents = json.loads(contents_str)
    expected = [
        {
            'type': 'build_backend',
            'req': 'buildme>1.0',
            'dist': 'buildme',
            'version': '6.0',
            'why': ' -> buildme',
        },
    ]
    assert expected == contents


def test_build_order_name_canonicalization(tmp_context):
    tmp_context.add_to_build_order(
        'build_backend', Requirement('flit-core>1.0'), '3.9.0', ' -> buildme')
    tmp_context.add_to_build_order(
        'build_backend', Requirement('flit_core>1.0'), '3.9.0', ' -> buildme')
    contents_str = tmp_context._build_order_filename.read_text()
    contents = json.loads(contents_str)
    expected = [
        {
            'type': 'build_backend',
            'req': 'flit-core>1.0',
            'dist': 'flit-core',
            'version': '3.9.0',
            'why': ' -> buildme',
        },
    ]
    assert expected == contents
