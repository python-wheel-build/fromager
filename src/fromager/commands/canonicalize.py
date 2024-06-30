import click

from .. import overrides


@click.command()
@click.argument("dist_name", nargs=-1)
def canonicalize(dist_name: list[str]):
    """convert a package name to its canonical form for use in override paths"""
    for name in dist_name:
        print(overrides.pkgname_to_override_module(name))
