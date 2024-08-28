import click

from fromager import context


@click.command()
@click.pass_obj
def list_overrides(
    wkctx: context.WorkContext,
) -> None:
    """List all of the packages with overrides in the current configuration."""
    for name in sorted(wkctx.settings.list_overrides()):
        print(name)
