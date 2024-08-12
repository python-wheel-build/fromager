import pathlib
import textwrap

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

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


def test_relative_path_build_dir():
    s = settings._parse(
        textwrap.dedent("""
    packages:
      foo:
        build_dir: "./build"
    """)
    )
    sdist_root_dir = pathlib.Path("/foo/bar")
    assert s.build_dir("foo", sdist_root_dir) == sdist_root_dir / "build"


def test_only_name_build_dir():
    s = settings._parse(
        textwrap.dedent("""
    packages:
      foo:
        build_dir: "build"
    """)
    )
    sdist_root_dir = pathlib.Path("/foo/bar")
    assert s.build_dir("foo", sdist_root_dir) == sdist_root_dir / "build"


def test_absolute_path_build_dir():
    s = settings._parse(
        textwrap.dedent("""
    packages:
      foo:
        build_dir: "/tmp/build"
    """)
    )
    sdist_root_dir = pathlib.Path("/foo/bar")
    assert s.build_dir("foo", sdist_root_dir) == sdist_root_dir / "tmp" / "build"


def test_escape_sdist_root_build_dir():
    s = settings._parse(
        textwrap.dedent("""
    packages:
      foo:
        build_dir: "../tmp/build"
    """)
    )
    sdist_root_dir = pathlib.Path("/foo/bar")
    with pytest.raises(ValueError):
        str(s.build_dir("foo", sdist_root_dir)).startswith("/foo/bar")


def test_changelog():
    s = settings._parse(
        textwrap.dedent("""
    packages:
      foo:
        changelog:
          "2.1.0":
            - "rebuild abc"
            - "rebuild xyz"
    """)
    )
    assert s.build_tag("foo", Version("2.1.0")) == 2
    assert s.build_tag("foo", "2.1.0") == 2
    assert s.build_tag("foo", "3.1.0") == 0
    assert s.build_tag("bar", "2.1.0") == 0


def test_resolve_template_with_no_template():
    req = Requirement("foo==1.0")
    assert settings._resolve_template(None, req, "1.0") is None


def test_resolve_template_with_version():
    req = Requirement("foo==1.0")
    assert settings._resolve_template("url-${version}", req, "1.0") == "url-1.0"


def test_resolve_template_with_no_matching_template():
    req = Requirement("foo==1.0")
    with pytest.raises(KeyError):
        settings._resolve_template("url-${flag}", req, "1.0")
