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
        - X
        - egg_SPAM
    """)
    )
    assert s.pre_built("cuda") == set(["a", "b", "x", "egg_spam"])


def test_with_download_source():
    s = settings._parse(
        textwrap.dedent("""
    download_source:
      foo:
        url: url
        rename_to: rename
      egg_SPAM:
        url: egg-url
        rename_to: rename-spam
    """)
    )
    assert s.sdist_local_filename("foo") == "rename"
    assert s.sdist_local_filename("bar") is None
    assert s.sdist_local_filename("egg-spam") == "rename-spam"
    assert s.sdist_local_filename("egg.spam") == "rename-spam"
    assert s.sdist_download_url("foo") == "url"
    assert s.sdist_download_url("bar") is None
    assert s.sdist_download_url("egg_spam") == "egg-url"


def test_no_download_source():
    s = settings._parse(
        textwrap.dedent("""
    pre_built:
    """)
    )
    assert s.sdist_local_filename("foo") is None
    assert s.sdist_download_url("foo") is None


def test_with_build_option():
    s = settings._parse(
        textwrap.dedent("""
    build_option:
      foo:
        cpu_scaling: 2
        memory_scaling: 5
    """)
    )
    bo = s.build_option("foo")
    assert bo is not None
    assert bo.cpu_scaling == 2
    assert bo.memory_scaling == 5
    assert s.build_option("bar") is None


def test_no_build_option():
    s = settings._parse(
        textwrap.dedent("""
    build_option:
    """)
    )
    assert s.build_option("foo") is None
