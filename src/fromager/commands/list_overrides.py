import click

from fromager import context, overrides


@click.command()
@click.pass_obj
def list_overrides(
    wkctx: context.WorkContext,
) -> None:
    """List all of the packages with overrides in the current configuration."""
    for name in overrides.list_all(
        wkctx.patches_dir, wkctx.envs_dir, wkctx.settings.packages()
    ):
        print(name)
