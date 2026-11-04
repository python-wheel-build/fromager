"""Tests for package resolver configuration output."""

from unittest.mock import Mock, patch

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from fromager import context, packagesettings, resolver
from fromager.candidate import Candidate
from fromager.commands import package as package_command


def _configure_package(ctx: context.WorkContext, yaml_str: str) -> None:
    """Apply one package setting to the test context."""
    ps = packagesettings.PackageSettings.from_string("pkg", yaml_str)
    ctx.settings._package_settings[ps.name] = ps


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://pkg.test/simple/", "https://pkg.test/simple/"),
        ("https://user:pass@pkg.test/simple/", "https://pkg.test/simple/"),
        (
            "https://pkg.test/archive?private_token=SECRET",
            "https://pkg.test/archive?private_token=***",
        ),
        ("https://pkg.test/archive#token=SECRET", "https://pkg.test/archive"),
        (
            "https://user:pass@pkg.test/archive/v{version}.tar.gz?token=SECRET",
            "https://pkg.test/archive/v{version}.tar.gz?token=***",
        ),
        (
            "https://user:pass@pkg.test/archive?token=SECRET#token=SECRET",
            "https://pkg.test/archive?token=***",
        ),
        (
            "https://pkg.test/archive.tar.gz?sha=v{version}&private_token=SECRET",
            "https://pkg.test/archive.tar.gz?sha=***&private_token=***",
        ),
        (
            "https://pkg.test/archive?ref=one&ref=two&flag&empty=",
            "https://pkg.test/archive?ref=***&ref=***&flag=***&empty=***",
        ),
        (
            "https://pkg.test/archive?private%5Ftoken=SECRET%26OTHER",
            "https://pkg.test/archive?private_token=***",
        ),
    ],
)
def test_display_url(url: str, expected: str) -> None:
    """Keep query names while hiding user info, values, and fragments."""
    assert package_command._display_url(url) == expected


def test_resolve_fromager_displays_and_uses_source_config(
    tmp_context: context.WorkContext,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Display source settings and resolve through the configured provider."""
    _configure_package(
        tmp_context,
        "source:\n"
        "  provider: pypi-prebuilt\n"
        "  index_url: https://index-user:index-password@pkg.test/simple/?token=SECRET#fragment-secret\n"
        "  min_release_age: 7\n",
    )
    req = Requirement("pkg")
    candidate = Candidate(
        name=req.name,
        version=Version("1.0"),
        url="https://pkg.test/pkg-1.0-py3-none-any.whl",
    )

    with (
        patch.object(
            package_command.sources,
            "get_source_provider",
            wraps=package_command.sources.get_source_provider,
        ) as get_source_provider,
        patch.object(
            resolver.PyPIProvider,
            "find_matches",
            autospec=True,
            return_value=[candidate],
        ) as find_matches,
    ):
        versions = package_command._resolve_fromager(
            tmp_context,
            req,
            constraint=None,
            distribution_type=package_command.DistributionType.SDIST,
            sdist_server_url="https://caller.test/simple/",
        )

    output = capsys.readouterr().out
    assert "- source:" in output
    assert "  - provider: pypi-prebuilt" in output
    assert "  - resolves_prebuilt_wheel: True" in output
    assert "  - min_release_age: 7" in output
    assert "  - index_url: https://pkg.test/simple/?token=***\n" in output
    assert "index-user" not in output
    assert "index-password" not in output
    assert "SECRET" not in output
    assert "fragment-secret" not in output
    assert (
        "- distribution type 'sdist' is ignored for configured source resolvers"
        in output
    )
    assert "- resolver includes sdists:" not in output
    assert "- download url:" not in output
    assert versions == {Version("1.0")}
    get_source_provider.assert_called_once_with(
        ctx=tmp_context,
        req=req,
        sdist_server_url="https://caller.test/simple/",
    )
    find_matches.assert_called_once()
    source_provider = find_matches.call_args.args[0]
    assert source_provider.cooldown is None


@pytest.mark.parametrize(
    ("credentials", "suffix"),
    [
        ("", ""),
        (
            "SECRET_USER:SECRET_PASSWORD@",
            "?private_token=QUERY_SECRET#token=FRAGMENT_SECRET",
        ),
    ],
    ids=["public", "credentials"],
)
def test_resolve_fromager_preserves_legacy_config_output(
    tmp_context: context.WorkContext,
    capsys: pytest.CaptureFixture[str],
    credentials: str,
    suffix: str,
) -> None:
    """Display legacy URLs safely while resolving with their original values."""
    index_url = f"https://{credentials}legacy.test/simple/{suffix}"
    wheel_url = f"https://{credentials}wheels.test/simple/{suffix}"
    download_url = f"https://{credentials}pkg.test/pkg-${{version}}.tar.gz{suffix}"
    _configure_package(
        tmp_context,
        "download_source:\n"
        f"  url: {download_url}\n"
        "resolver_dist:\n"
        f"  sdist_server_url: {index_url}\n"
        "  include_sdists: true\n"
        "  include_wheels: false\n"
        "variants:\n"
        "  cpu:\n"
        f"    wheel_server_url: {wheel_url}\n"
        "    pre_built: false\n",
    )
    req = Requirement("pkg")
    candidate = Candidate(
        name=req.name,
        version=Version("1.0"),
        url="https://pkg.test/pkg-1.0.tar.gz",
    )
    provider = Mock()
    provider.cooldown = object()
    provider.find_matches.return_value = [candidate]

    with patch.object(
        package_command.sources.overrides,
        "find_and_invoke",
        return_value=provider,
    ) as find_and_invoke:
        versions = package_command._resolve_fromager(
            tmp_context,
            req,
            constraint=None,
            distribution_type=package_command.DistributionType.WHEEL,
            sdist_server_url="https://caller.test/simple/",
        )

    output = capsys.readouterr().out
    assert "- source:" not in output
    assert "- sdist server url: https://legacy.test/simple/" in output
    assert "- resolver includes sdists: True" in output
    assert "- resolver includes wheels: False" in output
    assert "- using distribution type 'wheel' (sdists: False, wheels: True)" in output
    assert "- wheel server url: https://wheels.test/simple/" in output
    assert "- download url: https://pkg.test/pkg-${version}.tar.gz" in output
    assert "- prebuilt wheel: False" in output
    if suffix:
        assert (
            "- sdist server url: https://legacy.test/simple/?private_token=***\n"
            in output
        )
        assert (
            "- wheel server url: https://wheels.test/simple/?private_token=***\n"
            in output
        )
        assert (
            "- download url: https://pkg.test/pkg-${version}.tar.gz?private_token=***\n"
            in output
        )
    for secret in ("SECRET_USER", "SECRET_PASSWORD", "QUERY_SECRET", "FRAGMENT_SECRET"):
        assert secret not in output
    assert versions == {Version("1.0")}
    assert provider.cooldown is None
    find_and_invoke.assert_called_once_with(
        req.name,
        "get_resolver_provider",
        resolver.default_resolver_provider,
        ctx=tmp_context,
        req=req,
        include_sdists=False,
        include_wheels=True,
        sdist_server_url=index_url,
        ignore_platform=False,
    )
