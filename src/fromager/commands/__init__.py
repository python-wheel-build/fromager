import importlib.metadata

import click


def _load_commands() -> list[click.Command]:
    """Load commands from fromager.cli entry points"""
    commands: list[click.Command] = []
    seen: dict[str, str] = {}

    for ep in importlib.metadata.entry_points(group="fromager.cli"):
        try:
            command: click.Command | object = ep.load()
        except Exception as e:
            raise RuntimeError(
                f"Unable to load 'fromager.cli' entry point {ep.value!r}"
            ) from e

        # target must be a click command
        if not isinstance(command, click.Command):
            raise RuntimeError(f"{ep.value!r} is not a click.Command: {command}")

        # command name and entry point name have to match
        if command.name != ep.name:
            raise ValueError(
                f"Command name {command.name!r} does not match entry "
                f"point name {ep.name!r} for {ep.value!r}"
            )

        # third party commands can conflict
        if command.name in seen:
            raise ValueError(
                f"Conflict: {ep.value!r} and {seen[ep.name]!r} define {ep.name!r}"
            )
        commands.append(command)
        seen[ep.name] = ep.value

    return commands


commands = _load_commands()
