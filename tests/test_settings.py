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
    packages:
      foo:
        download_source:
            url: url
            destination_filename: rename
    """)
    )
    assert s.download_source_destination_filename("foo") == "rename"
    assert s.download_source_destination_filename("bar") is None
    assert s.download_source_url("foo") == "url"
    assert s.download_source_url("bar") is None


def test_no_download_source():
    s = settings._parse(
        textwrap.dedent("""
    packages:
    """)
    )
    assert s.download_source_destination_filename("foo") is None
    assert s.download_source_url("foo") is None


def test_with_resolver_dist():
    s = settings._parse(
        textwrap.dedent("""
    packages:
      foo:
        resolver_dist:
            sdist_server_url: url
            include_sdists: true
            include_wheels: false
    """)
    )
    assert type(s.resolver_include_sdists("foo")) is bool
    assert s.resolver_include_sdists("foo")
    assert type(s.resolver_include_wheels("foo")) is bool
    assert not s.resolver_include_wheels("foo")
    assert s.resolver_sdist_server_url("foo") == "url"


def test_no_resolver_dist():
    s = settings._parse(
        textwrap.dedent("""
    packages:
      foo:
        download_source:
            url: url
            destination_filename: rename
    """)
    )
    assert s.resolver_include_sdists("foo") is None
    assert s.resolver_include_wheels("foo") is None
    assert s.resolver_sdist_server_url("foo") is None
