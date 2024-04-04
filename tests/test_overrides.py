from mirror_builder import overrides
from mirror_builder.overrides import flit_core


def test_flit_core_build_wheel():
    build_wheel = overrides.find_override_method('flit_core', 'build_wheel')
    assert flit_core.build_wheel == build_wheel


def test_flit_core_build_wheel_repeat():
    build_wheel = overrides.find_override_method('flit_core', 'build_wheel')
    assert flit_core.build_wheel == build_wheel
    build_wheel2 = overrides.find_override_method('flit_core', 'build_wheel')
    assert flit_core.build_wheel == build_wheel2


def test_flit_core_no_such_override():
    build_wheel = overrides.find_override_method('flit_core', 'no_such_override')
    assert None == build_wheel


def test_nodist():
    build_wheel = overrides.find_override_method('nodist', 'no_such_override')
    assert None == build_wheel
