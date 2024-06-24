import requests_mock
import resolvelib
from packaging.requirements import Requirement

from fromager import resolver

_hydra_core_simple_response = """
<!DOCTYPE html>
<html>
<head>
<meta name="pypi:repository-version" content="1.1">
<title>Links for hydra-core</title>
</head>
<body>
<h1>Links for hydra-core</h1>
<a href="https://files.pythonhosted.org/packages/6d/8e/07e42bc434a847154083b315779b0a81d567154504624e181caf2c71cd98/hydra-core-1.3.2.tar.gz#sha256=8a878ed67216997c3e9d88a8e72e7b4767e81af37afb4ea3334b269a4390a824">hydra-core-1.3.2.tar.gz</a>
<br/>
<a href="https://files.pythonhosted.org/packages/c6/50/e0edd38dcd63fb26a8547f13d28f7a008bc4a3fd4eb4ff030673f22ad41a/hydra_core-1.3.2-py3-none-any.whl#sha256=fa0238a9e31df3373b35b0bfb672c34cc92718d21f81311d8996a16de1141d8b" data-dist-info-metadata="sha256=399046cbf9ae7ebab8dfd009e2b4f748212c710a0e75ca501a72bbb2d456e2e7" data-core-metadata="sha256=399046cbf9ae7ebab8dfd009e2b4f748212c710a0e75ca501a72bbb2d456e2e7">hydra_core-1.3.2-py3-none-any.whl</a>
<br/>
</body>
</html>
<!--SERIAL 22812307-->
"""


def test_provider_choose_wheel():
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/hydra-core/",
            text=_hydra_core_simple_response,
        )

        provider = resolver.PyPIProvider(include_sdists=False)
        reporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("hydra-core")])
        assert "hydra-core" in result.mapping

        candidate = result.mapping["hydra-core"]
        assert (
            candidate.url
            == "https://files.pythonhosted.org/packages/c6/50/e0edd38dcd63fb26a8547f13d28f7a008bc4a3fd4eb4ff030673f22ad41a/hydra_core-1.3.2-py3-none-any.whl#sha256=fa0238a9e31df3373b35b0bfb672c34cc92718d21f81311d8996a16de1141d8b"
        )
        assert str(candidate.version) == "1.3.2"


def test_provider_choose_sdist():
    with requests_mock.Mocker() as r:
        r.get(
            "https://pypi.org/simple/hydra-core/",
            text=_hydra_core_simple_response,
        )

        provider = resolver.PyPIProvider(include_wheels=False)
        reporter = resolvelib.BaseReporter()
        rslvr = resolvelib.Resolver(provider, reporter)

        result = rslvr.resolve([Requirement("hydra-core")])
        assert "hydra-core" in result.mapping

        candidate = result.mapping["hydra-core"]
        assert (
            candidate.url
            == "https://files.pythonhosted.org/packages/6d/8e/07e42bc434a847154083b315779b0a81d567154504624e181caf2c71cd98/hydra-core-1.3.2.tar.gz#sha256=8a878ed67216997c3e9d88a8e72e7b4767e81af37afb4ea3334b269a4390a824"
        )
        assert str(candidate.version) == "1.3.2"
