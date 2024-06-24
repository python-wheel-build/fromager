import textwrap

from fromager import settings


def test_empty():
    s = settings.Settings({})
    assert s.pre_built("cuda") == set()


def test_no_pre_built():
    s = settings._parse(
        textwrap.dedent("""
    pre_built:
    """)
    )
    assert s.pre_built("cuda") == set()


def test_with_pre_built():
    s = settings._parse(
        textwrap.dedent("""
    pre_built:
      cuda:
        - a
        - b
    """)
    )
    assert s.pre_built("cuda") == set(["a", "b"])
