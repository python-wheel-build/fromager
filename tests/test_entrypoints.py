import inspect
from importlib.metadata import entry_points


def test_ep_override_methods():
    epg = entry_points(group="fromager.override_methods")
    assert epg
    for name in epg.names:
        func = epg[name].load()
        assert inspect.isfunction(func)
