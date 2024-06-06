import click

from .. import overrides


@click.command()
@click.argument('dist_name', nargs=-1)
def canonicalize(dist_name):
    for name in dist_name:
        print(overrides.pkgname_to_override_module(name))
