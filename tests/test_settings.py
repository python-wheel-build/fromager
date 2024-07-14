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


def test_with_download_source():
    s = settings._parse(
        textwrap.dedent("""
    download_source:
      foo:
        url: url
        rename_to: rename
    """)
    )
    assert s.sdist_local_filename("foo") == "rename"
    assert s.sdist_local_filename("bar") is None
    assert s.sdist_download_url("foo") == "url"
    assert s.sdist_download_url("bar") is None


def test_no_download_source():
    s = settings._parse(
        textwrap.dedent("""
    pre_built:
    """)
    )
    assert s.sdist_local_filename("foo") is None
    assert s.sdist_download_url("foo") is None
